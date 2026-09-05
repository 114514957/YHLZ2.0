"""Unit tests for the FunASR paraformer-zh-streaming provider adapter."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path

import numpy as np

from backend.asr_provider_port import ASRProviderError
from backend.streaming_asr_bridge import ASRStreamUpdateKind
from backend.target_funasr_asr import (
    CHUNK_STRIDE,
    FunasrASRConfig,
    FunasrOnlineASRProvider,
)
from backend.target_chain import CancellationSignal


class _FakeEngine:
    def __init__(self):
        self.calls = []

    def generate_incremental(self, audio, cache, is_final):
        self.calls.append((len(audio), is_final))
        if is_final:
            return [{"text": "进步始于思想，元亨开拓未来"}]
        return [{"text": "进步始于思想"}]


class _SlowEngine(_FakeEngine):
    def generate_incremental(self, audio, cache, is_final):
        self.calls.append((len(audio), is_final))
        if not is_final:
            time.sleep(0.02)
            return [{"text": ""}]
        return [{"text": "元亨，能听到吗"}]


import time  # noqa: E402
import tempfile  # noqa: E402


def _model_dir() -> Path:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "model.pt").touch()
    return tmp


def _provider(engine):
    return FunasrOnlineASRProvider(
        FunasrASRConfig(model_dir=_model_dir(), min_available_memory_bytes=0),
        engine_factory=lambda: engine,
        available_memory_reader=lambda: 4 * 1024 ** 3,
    )


class FunasrProviderTests(unittest.TestCase):
    def test_stream_yields_partial_then_final(self) -> None:
        provider = _provider(_FakeEngine())
        provider.start()
        provider.open_stream("s1", 1, 16000, 1, CancellationSignal())
        samples = np.zeros(CHUNK_STRIDE, dtype="float32")
        all_updates = provider.push_audio("s1", samples, 16000, CancellationSignal())
        all_updates += provider.push_audio(
            "s1", samples[: CHUNK_STRIDE // 2], 16000, CancellationSignal()
        )
        kinds = [u.kind for u in all_updates]
        self.assertIn(ASRStreamUpdateKind.PARTIAL, kinds)
        final = provider.finish_stream("s1", CancellationSignal())
        self.assertEqual(final.kind, ASRStreamUpdateKind.FINAL)
        self.assertEqual(final.text, "进步始于思想，元亨开拓未来")
        self.assertEqual(provider.health()["state"], "ready")
        provider.stop("done")

    def test_engine_failure_is_stable_error(self) -> None:
        class Boom(_FakeEngine):
            def generate_incremental(self, *a, **k):
                raise RuntimeError("boom")

        provider = _provider(Boom())
        provider.start()
        provider.open_stream("s2", 1, 16000, 1, CancellationSignal())
        with self.assertRaises(ASRProviderError) as ctx:
            provider.push_audio("s2", np.zeros(CHUNK_STRIDE, dtype="float32"), 16000, CancellationSignal())
        self.assertEqual(ctx.exception.code, "ASR-FUNASR-INFERENCE")

    def test_format_guard(self) -> None:
        provider = _provider(_FakeEngine())
        provider.start()
        with self.assertRaises(ASRProviderError) as ctx:
            provider.open_stream("s3", 1, 44100, 1, CancellationSignal())
        self.assertEqual(ctx.exception.code, "ASR-STREAM-FORMAT")

    def test_missing_asset_rejected_at_config(self) -> None:
        with self.assertRaises(ValueError):
            FunasrASRConfig(model_dir=Path("__no_such_model__"))

    def test_health_and_snapshot(self) -> None:
        provider = _provider(_FakeEngine())
        self.assertEqual(provider.health()["provider_id"], "funasr-paraformer-online")
        self.assertIn("active_streams", provider.snapshot())
        self.assertIn("streaming", provider.health())


if __name__ == "__main__":
    unittest.main()
