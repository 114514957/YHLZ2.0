"""Tests for the verified local Sherpa online ASR provider."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from backend.asr_provider_port import (
    ASRProviderError,
    ASRProviderState,
    ASRStreamUpdateKind,
    is_streaming_asr_provider_port,
)
from backend.target_chain import CancellationSignal
from backend.target_sherpa_asr import (
    DEFAULT_ASR_ASSET_DIR,
    DEFAULT_ASR_MANIFEST_PATH,
    SherpaOnlineASRConfig,
    SherpaOnlineASRProvider,
    verify_sherpa_asr_asset,
)


_RUNTIME_NAMES = (
    "encoder-epoch-99-avg-1.int8.onnx",
    "decoder-epoch-99-avg-1.int8.onnx",
    "joiner-epoch-99-avg-1.int8.onnx",
    "tokens.txt",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _make_asset(root: Path) -> tuple[Path, Path]:
    directory = "test-streaming-model"
    asset_dir = root / directory
    asset_dir.mkdir()
    files = {name: ("asset-" + name).encode("ascii") for name in _RUNTIME_NAMES}
    for name, content in files.items():
        (asset_dir / name).write_bytes(content)
    manifest = {
        "schema_version": 1,
        "provider": {"id": "sherpa-onnx-online-transducer"},
        "assets": [
            {
                "directory": directory,
                "version": "test-v1",
                "source": "https://example.test/model.tar.bz2",
                "model_origin": "https://example.test/origin",
                "license": "Apache-2.0",
                "archive": {
                    "filename": "model.tar.bz2",
                    "bytes": 1,
                    "sha256": "0" * 64,
                },
                "runtime_files": [
                    {
                        "filename": name,
                        "bytes": len(content),
                        "sha256": _sha256(content),
                    }
                    for name, content in files.items()
                ],
            }
        ],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return asset_dir, manifest_path


class _NativeStream:
    def __init__(self) -> None:
        self.pending = False
        self.finished = False
        self.accepted = []

    def accept_waveform(self, sample_rate: int, samples: np.ndarray) -> None:
        self.accepted.append((sample_rate, samples.copy()))
        self.pending = True

    def input_finished(self) -> None:
        self.finished = True
        self.pending = True


class _Result:
    def __init__(self, text: str) -> None:
        self.text = text


class _NativeRecognizer:
    def __init__(self) -> None:
        self.streams = []
        self.decode_calls = 0

    def create_stream(self) -> _NativeStream:
        stream = _NativeStream()
        self.streams.append(stream)
        return stream

    @staticmethod
    def is_ready(stream: _NativeStream) -> bool:
        return stream.pending

    def decode_stream(self, stream: _NativeStream) -> None:
        self.decode_calls += 1
        stream.pending = False

    @staticmethod
    def get_result(stream: _NativeStream) -> _Result:
        return _Result("最终结果" if stream.finished else "临时结果")


class SherpaOnlineASRProviderTests(unittest.TestCase):
    def _provider(
        self,
        root: Path,
        *,
        available_memory: int = 3 * 1024 * 1024 * 1024,
    ) -> tuple[SherpaOnlineASRProvider, _NativeRecognizer]:
        asset_dir, manifest_path = _make_asset(root)
        recognizer = _NativeRecognizer()
        config = SherpaOnlineASRConfig(
            asset_dir=asset_dir,
            manifest_path=manifest_path,
            partial_interval_ms=0,
            min_available_memory_bytes=2 * 1024 * 1024 * 1024,
        )
        provider = SherpaOnlineASRProvider(
            config,
            recognizer_factory=lambda _config, _path: recognizer,
            available_memory_reader=lambda: available_memory,
        )
        return provider, recognizer

    def test_verified_provider_emits_partial_then_final_without_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, recognizer = self._provider(Path(directory))
            self.assertTrue(is_streaming_asr_provider_port(provider))
            provider.start()
            self.assertEqual(provider.state, ASRProviderState.READY)
            signal = CancellationSignal()
            provider.open_stream("stream-1", 3, 16_000, 1, signal)
            updates = provider.push_audio(
                "stream-1", np.zeros(1600, dtype=np.float32), 16_000, signal
            )
            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0].kind, ASRStreamUpdateKind.PARTIAL)
            self.assertEqual(updates[0].text, "临时结果")
            final = provider.finish_stream("stream-1", signal)
            self.assertEqual(final.kind, ASRStreamUpdateKind.FINAL)
            self.assertEqual(final.text, "最终结果")
            self.assertTrue(provider.wait_stopped(0))
            self.assertEqual(recognizer.decode_calls, 2)
            health = provider.health()
            self.assertTrue(health["asset"]["verified"])
            self.assertEqual(health["metrics"]["partial_updates"], 1)
            self.assertEqual(health["metrics"]["final_updates"], 1)
            self.assertNotIn("text", health)
            self.assertEqual(list(Path(directory).rglob("*.wav")), [])
            provider.stop()

    def test_interrupt_releases_active_stream_and_is_observable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, _ = self._provider(Path(directory))
            provider.start()
            signal = CancellationSignal()
            provider.open_stream("stream-1", 1, 16_000, 1, signal)
            self.assertFalse(provider.wait_stopped(0))
            provider.interrupt("barge_in")
            self.assertTrue(provider.wait_stopped(0))
            self.assertEqual(provider.health()["metrics"]["cancelled_streams"], 1)
            with self.assertRaises(ASRProviderError) as context:
                provider.push_audio(
                    "stream-1", np.zeros(1600, dtype=np.float32), 16_000, signal
                )
            self.assertEqual(context.exception.code, "ASR-STREAM-NOT-FOUND")

    def test_resource_gate_fails_closed_before_factory_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            asset_dir, manifest_path = _make_asset(Path(directory))
            factory_calls = []
            provider = SherpaOnlineASRProvider(
                SherpaOnlineASRConfig(
                    asset_dir=asset_dir,
                    manifest_path=manifest_path,
                    min_available_memory_bytes=2,
                ),
                recognizer_factory=lambda _config, _path: factory_calls.append(True),
                available_memory_reader=lambda: 1,
            )
            with self.assertRaises(ASRProviderError) as context:
                provider.start()
            self.assertEqual(context.exception.code, "ASR-RESOURCE-BUDGET")
            self.assertEqual(factory_calls, [])
            self.assertEqual(provider.state, ASRProviderState.FAILED)
            self.assertFalse(provider.health()["available"])

    def test_format_mismatch_never_reaches_native_recognizer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider, recognizer = self._provider(Path(directory))
            provider.start()
            signal = CancellationSignal()
            provider.open_stream("stream-1", 1, 16_000, 1, signal)
            with self.assertRaises(ASRProviderError) as context:
                provider.push_audio("stream-1", np.zeros(1600, dtype=np.float32), 48_000, signal)
            self.assertEqual(context.exception.code, "ASR-STREAM-SAMPLE-RATE")
            self.assertEqual(recognizer.streams[0].accepted, [])

    def test_real_downloaded_asset_matches_its_tracked_manifest(self) -> None:
        spec, path = verify_sherpa_asr_asset(DEFAULT_ASR_ASSET_DIR, DEFAULT_ASR_MANIFEST_PATH)
        self.assertEqual(path, DEFAULT_ASR_ASSET_DIR)
        self.assertEqual(spec.license, "Apache-2.0")
        self.assertEqual(len(spec.runtime_files), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
