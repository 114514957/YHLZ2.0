"""
M0.2 引擎适配器层单测: backend/tts/adapters/

覆盖:
1. 统一接口合规: 所有适配器均实现 generate/load/unload/health_check
2. Qwen3 适配器: 多声音透传 (M0.1 能力) / 合成正确
3. GPT-SoVITS 适配器: generate 全链路 (假 Gradio 客户端) / 权重切换 / voice_id 忽略
4. Edge 适配器: 预留接口行为
5. 工厂: create_tts_adapter / list_adapters
6. 验收证明: tts_service 的 GradioClient 来自 adapter (唯一实现, 无直接 Gradio)

运行: venv\Scripts\python.exe 对话DEMO\test_tts_adapters.py
（使用 FakeModel / 假客户端, 不连接真实服务）
"""
import asyncio
import io
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.tts.adapters import (
    create_tts_adapter,
    list_adapters,
    BaseVoiceEngineAdapter,
    Qwen3TTSAdapter,
    GPTSovitsAdapter,
    GradioClient,
    EdgeTTSAdapter,
)
from backend.tts.qwen3_tts import Qwen3TTSEngine, DEFAULT_VOICE_ID

UNIFIED_METHODS = ("generate", "load", "unload", "health_check")


def _make_wav_bytes(seconds: float = 0.5, sample_rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(np.zeros(int(seconds * sample_rate), dtype=np.int16).tobytes())
    return buf.getvalue()


class FakePrompt:
    def __init__(self, voice_id: str):
        self.voice_id = voice_id
        self.x_vector = np.full(512, float(len(voice_id)), dtype=np.float32)


class FakeQwenModel:
    def __init__(self):
        self.created = []
        self.generated = []

    def create_voice_clone_prompt(self, ref_audio, x_vector_only_mode=True):
        vid = Path(str(ref_audio)).stem
        self.created.append(vid)
        return FakePrompt(vid)

    def generate_voice_clone(self, text, language, voice_clone_prompt):
        self.generated.append((voice_clone_prompt.voice_id, text))
        return [np.zeros(2400, dtype=np.float32)], 24000


class FakeGradioClient:
    """假 Gradio 客户端: 模拟 predict/download/ensure/close"""

    def __init__(self):
        self.ensured = 0
        self.predicts = []
        self.closed = False
        self._fn_map = {"/inference": 0, "/change_sovits_weights": 1, "/change_gpt_weights": 2}

    async def ensure(self):
        self.ensured += 1

    async def close(self):
        self.closed = True

    async def predict(self, api_name: str, *args):
        self.predicts.append((api_name, args))
        if api_name == "/inference":
            return [{"url": "http://fake/audio.wav"}]
        return "ok"

    async def download_audio(self, url: str) -> bytes:
        return _make_wav_bytes()


# ---------------------------------------------------------------------------
# 1. 统一接口合规
# ---------------------------------------------------------------------------

class TestUnifiedInterface(unittest.TestCase):
    """验收核心: 未来 VIS 只需要调用 Adapter 统一接口"""

    def test_all_adapters_implement_unified_interface(self):
        for name in ("qwen3", "gpt-sovits", "edge"):
            adapter = create_tts_adapter(name)
            self.assertIsInstance(adapter, BaseVoiceEngineAdapter)
            for method in UNIFIED_METHODS:
                self.assertTrue(callable(getattr(adapter, method)), f"{name}.{method}")
            hc = adapter.health_check()
            self.assertIn("ok", hc)
            self.assertIn("name", hc)

    def test_factory_unknown_name(self):
        with self.assertRaises(ValueError):
            create_tts_adapter("nonexistent")

    def test_list_adapters(self):
        names = {a["name"] for a in list_adapters()}
        self.assertIn("qwen3-tts", names)
        self.assertIn("gpt-sovits", names)
        self.assertIn("edge-tts", names)


# ---------------------------------------------------------------------------
# 2. Qwen3 适配器
# ---------------------------------------------------------------------------

class Qwen3AdapterBase(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="adapter_qwen3_"))
        self.ref_a = str(tmp / "voice_a.wav")
        self.ref_b = str(tmp / "voice_b.wav")
        _write_wav(self.ref_a)
        _write_wav(self.ref_b)
        self.engine = Qwen3TTSEngine()
        self.model = FakeQwenModel()
        self.engine._model = self.model
        self.engine.is_loaded = True
        self.adapter = Qwen3TTSAdapter(engine=self.engine)


def _write_wav(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(np.zeros(24000, dtype=np.int16).tobytes())


class TestQwen3Adapter(Qwen3AdapterBase):
    def test_generate_default_voice(self):
        self.adapter.load_voice(ref_audio=self.ref_a)  # 默认 voice_id
        audio, sr = self.adapter.generate("你好")
        self.assertEqual(sr, 24000)
        self.assertEqual(self.model.generated[0], ("voice_a", "你好"))

    def test_multi_voice_not_overwritten(self):
        self.adapter.load_voice("voice_a", ref_audio=self.ref_a)
        self.adapter.load_voice("voice_b", ref_audio=self.ref_b)

        self.adapter.generate("A1", voice_id="voice_a")
        self.adapter.generate("B1", voice_id="voice_b")
        self.adapter.generate("A2", voice_id="voice_a")

        self.assertEqual(
            [g[0] for g in self.model.generated],
            ["voice_a", "voice_b", "voice_a"],
        )
        self.assertEqual(len(self.adapter.get_available_voices()), 2)

    def test_clear_voice(self):
        self.adapter.load_voice("voice_a", ref_audio=self.ref_a)
        self.adapter.load_voice("voice_b", ref_audio=self.ref_b)
        self.assertEqual(self.adapter.clear_voice("voice_a"), 1)
        self.assertIsNone(self.adapter.get_voice("voice_a"))
        self.assertIsNotNone(self.adapter.get_voice("voice_b"))

    def test_unload_clears_caches_and_state(self):
        self.adapter.load_voice("voice_a", ref_audio=self.ref_a)
        self.adapter.unload()
        self.assertFalse(self.adapter.is_loaded)
        self.assertFalse(self.adapter.can_serve())
        self.assertEqual(len(self.adapter.get_available_voices()), 0)


# ---------------------------------------------------------------------------
# 3. GPT-SoVITS 适配器
# ---------------------------------------------------------------------------

class TestGPTSovitsAdapter(unittest.TestCase):
    def _make_adapter(self):
        adapter = GPTSovitsAdapter(base_url="http://fake:9872/")
        fake = FakeGradioClient()
        adapter._client = fake
        adapter.is_loaded = True
        return adapter, fake

    def test_generate_full_chain(self):
        adapter, fake = self._make_adapter()
        audio, sr = adapter.generate(
            "测试文本",
            voice_id="voice_a",  # 应被忽略并告警
            ref_audio_path="d:/refs/ref.wav",
            text_lang="zh",
        )
        self.assertEqual(sr, 24000)
        self.assertGreater(len(audio), 0)
        # /inference 参数序与 GPT-SoVITS 一致
        inference = [p for p in fake.predicts if p[0] == "/inference"]
        self.assertEqual(len(inference), 1)
        args = inference[0][1]
        self.assertEqual(args[0], "测试文本")
        self.assertEqual(args[1], "zh")
        self.assertEqual(args[2]["meta"]["_type"], "gradio.FileData")
        self.assertEqual(args[5], "zh")  # 参考文本语言

    def test_generate_fallback_when_not_loaded(self):
        adapter = GPTSovitsAdapter(base_url="http://fake:9872/")
        # 不连接任何客户端, load 必然失败 → 兜底音频, 不崩溃
        audio, sr = adapter.generate("兜底")
        self.assertEqual(sr, 24000)
        self.assertGreater(len(audio), 0)

    def test_change_weights(self):
        adapter, fake = self._make_adapter()
        adapter.change_weights("sovits.pth", "gpt.ckpt", "zh")
        self.assertEqual(fake.predicts[0][0], "/change_sovits_weights")
        self.assertEqual(fake.predicts[1][0], "/change_gpt_weights")

    def test_health_check_with_fake_client(self):
        adapter, fake = self._make_adapter()
        hc = adapter.health_check()
        self.assertTrue(hc["ok"])
        self.assertEqual(hc["base_url"], "http://fake:9872/")

    def test_unload_closes_client(self):
        adapter, fake = self._make_adapter()
        adapter.unload()
        self.assertTrue(fake.closed)
        self.assertFalse(adapter.is_loaded)

    def test_gradio_client_single_implementation(self):
        """验收: 全仓库唯一 Gradio 实现位于 adapter 包"""
        tts_service = self._import_tts_service_standalone()
        self.assertIs(tts_service.GradioClient, GradioClient)
        self.assertTrue(GradioClient.__module__.endswith("gpt_sovits_adapter"))
        # tts_service 源码中不再定义 GradioClient
        import inspect
        src = inspect.getsource(tts_service)
        self.assertNotIn("class GradioClient", src)

    @staticmethod
    def _import_tts_service_standalone():
        """绕过 updates/live_stream/__init__.py 的插件 import 链 (plugin_sdk 缺失), 直接加载 tts_service"""
        import types

        root = Path(__file__).resolve().parents[1]
        pkg_dir = root / "updates"
        for name, rel in (
            ("updates", ""),
            ("updates.live_stream", "live_stream"),
            ("updates.live_stream.backend", "live_stream/backend"),
        ):
            if name not in sys.modules:
                mod = types.ModuleType(name)
                mod.__path__ = [str(pkg_dir / rel)]
                sys.modules[name] = mod
        import updates.live_stream.backend.tts_service as tts_service
        return tts_service


# ---------------------------------------------------------------------------
# 4. Edge 适配器 (预留)
# ---------------------------------------------------------------------------

class TestEdgeAdapter(unittest.TestCase):
    def test_reserved_interface(self):
        adapter = EdgeTTSAdapter()
        hc = adapter.health_check()
        self.assertTrue(hc["reserved"])
        self.assertFalse(hc["ok"])
        with self.assertRaises(NotImplementedError):
            adapter.generate("测试")
        self.assertFalse(adapter.load())
        self.assertFalse(adapter.can_serve())


if __name__ == "__main__":
    unittest.main(verbosity=2)
