"""节点A 联合流式：一个音频 turn 走同一目标链（租约 + 内容队列 + 一个 Qwen 工作实例）。

Isolated tests (no real model / device).  Proves the chain seam added in
`TargetVoiceChain.submit_transcript(audio=...)` drives an audio-aware reasoner
and that first-segment PCM reaches playback before the last LLM delta.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
import wave
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.audio_reasoner import AudioReasoner  # noqa: E402
from backend.session_kernel import ProviderCapabilities  # noqa: E402
from backend.target_chain import TargetVoiceChain  # noqa: E402


def _make_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)  # 100ms of silence


class _FakeLLM:
    """Minimal conforming LLMProviderPort for isolated tests."""

    def __init__(self, script) -> None:
        self.script = list(script)
        self.calls: list = []

    async def stream_chat(self, messages, *, signal=None, temperature=0.7,
                          max_tokens=256, tools=None, tool_choice=None):
        self.calls.append(messages)
        deltas = self.script.pop(0) if self.script else []
        for d in deltas:
            if signal is not None and signal.is_cancelled():
                return
            yield d

    def abort(self, reason: str = "interrupt") -> None:
        pass

    async def wait_stopped(self, timeout_s: float) -> bool:
        return True

    def stop(self, reason: str = "shutdown") -> None:
        pass

    def health(self) -> dict:
        return {"available": True}


class _WaitingProvider:
    """Yields first delta, waits until playback started, then the last delta."""

    def __init__(self, played, order) -> None:
        self.played = played
        self.order = order

    async def stream_chat(self, messages, *, signal=None, temperature=0.7,
                          max_tokens=256, tools=None, tool_choice=None):
        yield "这是能先开始播放的第一句话。"
        await asyncio.wait_for(self.played.wait(), 1)
        self.order.append("last_delta")
        yield "这是后面才生成的第二句话。"

    def abort(self, reason: str = "interrupt") -> None:
        pass

    async def wait_stopped(self, timeout_s: float) -> bool:
        return True

    def stop(self, reason: str = "shutdown") -> None:
        pass

    def health(self) -> dict:
        return {"available": True}


class AudioChainSeamTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_turn_gets_lease_and_input_audio(self):
        provider = _FakeLLM([["你好，世界。"]])
        chain = TargetVoiceChain(reasoner=AudioReasoner(provider))
        chain.start(ProviderCapabilities(continuous_capture=True))
        wav = Path(tempfile.mkdtemp()) / "a.wav"
        _make_wav(wav)

        sub = await chain.submit_transcript("元亨（语音）", source="microphone",
                                            audio=[str(wav)])
        self.assertIsNotNone(sub.task)
        outcome = await asyncio.wait_for(sub.task, 5)
        self.assertEqual(outcome.status, "completed")
        self.assertTrue(sub.lease.turn_id)               # real generation lease
        content = provider.calls[0][-1]["content"]
        self.assertIsInstance(content, list)
        self.assertTrue(any(p.get("type") == "input_audio" for p in content))
        await chain.shutdown()

    async def test_text_turn_unaffected_without_audio(self):
        provider = _FakeLLM([["纯文本回答。"]])
        chain = TargetVoiceChain(reasoner=AudioReasoner(provider))
        chain.start(ProviderCapabilities(continuous_capture=True))
        sub = await chain.submit_transcript("元亨你好", source="microphone")
        outcome = await asyncio.wait_for(sub.task, 5)
        self.assertEqual(outcome.status, "completed")
        self.assertIsInstance(provider.calls[0][-1]["content"], str)
        await chain.shutdown()

    async def test_audio_turn_joint_streaming_pcm_before_last_delta(self):
        from backend.target_composition import (
            TargetVoiceComposition, TargetVoiceCompositionConfig,
        )
        from backend.test_tts_segmented_provider import FakeProvider
        from backend.tts_qwen_provider import QwenTTSConfig

        raw = FakeProvider()
        played = asyncio.Event()
        order: list[str] = []

        class Playback:
            async def play(self, chunk, lease, signal):
                order.append("pcm")
                played.set()
                return True

            async def finish(self, lease, signal):
                return True

        composition = TargetVoiceComposition(
            TargetVoiceCompositionConfig(qwen=QwenTTSConfig(model_dir=Path("C:/fake")),
                                         segmented_tts_enabled=True),
            reasoner=AudioReasoner(_WaitingProvider(played, order)),
            playback=Playback(),
            provider_factory=lambda config: raw,
        )
        composition.chain.start(ProviderCapabilities(continuous_capture=True))
        wav = Path(tempfile.mkdtemp()) / "a.wav"
        _make_wav(wav)

        sub = await composition.chain.submit_transcript(
            "元亨（语音）", source="test", audio=[str(wav)])
        outcome = await asyncio.wait_for(sub.task, 3)
        self.assertEqual(outcome.status, "completed")
        self.assertLess(order.index("pcm"), order.index("last_delta"))
        self.assertGreaterEqual(len(raw.sessions), 2)   # multi-segment, one worker
        await composition.chain.shutdown()


class WorkbenchAudioSubmitTests(unittest.IsolatedAsyncioTestCase):
    """daemon/workbench 音频入口：submit_audio 走同一目标链（ledger 0540）。"""

    async def test_adapter_submit_audio_routes_to_chain(self):
        from backend.target_workbench_adapter import TargetWorkbenchAdapter

        provider = _FakeLLM([["音频收到。"]])
        chain = TargetVoiceChain(reasoner=AudioReasoner(provider))
        chain.start(ProviderCapabilities(continuous_capture=True))
        adapter = TargetWorkbenchAdapter(chain=chain)
        wav = Path(tempfile.mkdtemp()) / "a.wav"
        _make_wav(wav)
        result = await adapter.submit_audio([str(wav)], text="元亨（语音）",
                                            source="daemon_audio")
        self.assertEqual(result.status, "completed")
        content = provider.calls[0][-1]["content"]
        self.assertTrue(any(p.get("type") == "input_audio" for p in content))
        await chain.shutdown()

    async def test_adapter_submit_audio_rejects_empty(self):
        from backend.target_workbench_adapter import TargetWorkbenchAdapter

        chain = TargetVoiceChain(reasoner=AudioReasoner(_FakeLLM([])))
        adapter = TargetWorkbenchAdapter(chain=chain)
        result = await adapter.submit_audio([], text="元亨")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "EMPTY-AUDIO")


if __name__ == "__main__":
    unittest.main()

