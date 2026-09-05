"""Contract tests for the isolated local target VAD provider."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.target_vad import (
    SileroVADConfig,
    TargetVADProvider,
    VADProviderError,
    VADProviderState,
    load_vad_asset_spec,
    verify_vad_asset,
)


class _Session:
    def __init__(self, probabilities, *, invalid_state: bool = False) -> None:
        self._probabilities = iter(probabilities)
        self.invalid_state = invalid_state
        self.inputs = []

    def get_inputs(self):
        return [SimpleNamespace(name=name) for name in ("input", "state", "sr")]

    def run(self, _outputs, feeds):
        self.inputs.append({name: np.asarray(value).copy() for name, value in feeds.items()})
        state = np.ones((1, 1, 1), dtype=np.float32) if self.invalid_state else feeds["state"] + 1
        return [np.asarray([[next(self._probabilities)]], dtype=np.float32), state]


class _BrokenSession(_Session):
    def run(self, _outputs, feeds):
        raise RuntimeError("inference broke")


def _write_manifest(directory: Path, *, digest: str) -> Path:
    manifest = directory / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": [
                    {
                        "filename": "silero_vad.onnx",
                        "version": "v6.2.1",
                        "source": "https://example.test/silero_vad.onnx",
                        "license": "MIT",
                        "sha256": digest,
                        "input_contract": "input:float32[1,576],state:float32[2,1,128],sr:int64[]",
                        "output_contract": "probability:float32[1,1],state:float32[2,1,128]",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


class TargetVADProviderTests(unittest.TestCase):
    def _setup_asset(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        asset = root / "silero_vad.onnx"
        asset.write_bytes(b"verified-onnx-placeholder")
        manifest = _write_manifest(root, digest=hashlib.sha256(asset.read_bytes()).hexdigest())
        config = SileroVADConfig(
            asset_dir=root,
            manifest_path=manifest,
            min_speech_windows=1,
            min_silence_windows=2,
        )
        return temporary, root, asset, manifest, config

    def test_manifest_and_asset_are_verified_without_network_access(self):
        temporary, root, asset, manifest, _config = self._setup_asset()
        try:
            spec = load_vad_asset_spec(manifest)
            verified_spec, verified_path = verify_vad_asset(root, manifest)
            self.assertEqual(spec.filename, "silero_vad.onnx")
            self.assertEqual(verified_spec.sha256, spec.sha256)
            self.assertEqual(verified_path, asset)
        finally:
            temporary.cleanup()

    def test_manifest_rejects_unsafe_asset_path_and_hash_mismatch(self):
        temporary, root, asset, manifest, _config = self._setup_asset()
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
            raw["assets"][0]["filename"] = "../outside.onnx"
            manifest.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(VADProviderError) as unsafe:
                load_vad_asset_spec(manifest)
            self.assertEqual(unsafe.exception.code, "VAD-ASSET-MANIFEST-INVALID")

            _write_manifest(root, digest="0" * 64)
            with self.assertRaises(VADProviderError) as mismatch:
                verify_vad_asset(root, manifest)
            self.assertEqual(mismatch.exception.code, "VAD-ASSET-SHA256-MISMATCH")
            self.assertTrue(asset.exists())
        finally:
            temporary.cleanup()

    def test_stream_context_hysteresis_and_stop_are_observable(self):
        temporary, _root, _asset, _manifest, config = self._setup_asset()
        try:
            session = _Session((0.9, 0.1, 0.1))
            provider = TargetVADProvider(config, session_factory=lambda path, providers: session)
            provider.start()
            frame = np.zeros(512, dtype=np.float32)
            self.assertTrue(provider.detect_speech(frame, 16_000))
            self.assertTrue(provider.detect_speech(frame, 16_000))
            self.assertFalse(provider.detect_speech(frame, 16_000))
            self.assertEqual(session.inputs[0]["input"].shape, (1, 576))
            self.assertTrue(np.all(session.inputs[0]["input"][0, :64] == 0))
            self.assertTrue(np.all(session.inputs[1]["state"] == 1))
            health = provider.health()
            self.assertEqual(health["state"], VADProviderState.READY.value)
            self.assertEqual(health["metrics"]["speech_starts"], 1)
            self.assertEqual(health["metrics"]["speech_ends"], 1)
            self.assertFalse(provider.wait_stopped(0))
            provider.stop("test")
            self.assertTrue(provider.wait_stopped(0))
            self.assertEqual(provider.state, VADProviderState.STOPPED)
            self.assertEqual(provider.health()["metrics"]["pending_samples"], 0)
        finally:
            temporary.cleanup()

    def test_bad_capture_format_fails_closed_without_corrupting_ready_session(self):
        temporary, _root, _asset, _manifest, config = self._setup_asset()
        try:
            provider = TargetVADProvider(config, session_factory=lambda path, providers: _Session((0.9,)))
            provider.start()
            with self.assertRaises(VADProviderError) as stereo:
                provider.detect_speech(np.zeros((512, 2), dtype=np.float32), 16_000)
            self.assertEqual(stereo.exception.code, "VAD-FORMAT-CHANNELS")
            with self.assertRaises(VADProviderError) as rate:
                provider.detect_speech(np.zeros(512, dtype=np.float32), 48_000)
            self.assertEqual(rate.exception.code, "VAD-SAMPLE-RATE")
            self.assertEqual(provider.state, VADProviderState.READY)
            self.assertEqual(provider.health()["metrics"]["format_failures"], 2)
        finally:
            temporary.cleanup()

    def test_inference_failure_marks_provider_failed_and_never_reports_ready(self):
        temporary, _root, _asset, _manifest, config = self._setup_asset()
        try:
            provider = TargetVADProvider(config, session_factory=lambda path, providers: _BrokenSession(()))
            provider.start()
            with self.assertRaises(VADProviderError) as failure:
                provider.detect_speech(np.zeros(512, dtype=np.float32), 16_000)
            self.assertEqual(failure.exception.code, "VAD-INFERENCE-FAILED")
            self.assertEqual(provider.state, VADProviderState.FAILED)
            self.assertTrue(provider.wait_stopped(0))
            self.assertEqual(provider.health()["last_error_code"], "VAD-INFERENCE-FAILED")
        finally:
            temporary.cleanup()

    def test_invalid_model_state_is_rejected(self):
        temporary, _root, _asset, _manifest, config = self._setup_asset()
        try:
            provider = TargetVADProvider(
                config,
                session_factory=lambda path, providers: _Session((0.9,), invalid_state=True),
            )
            provider.start()
            with self.assertRaises(VADProviderError) as result:
                provider.detect_speech(np.zeros(512, dtype=np.float32), 16_000)
            self.assertEqual(result.exception.code, "VAD-OUTPUT-INVALID")
            self.assertEqual(provider.state, VADProviderState.FAILED)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
