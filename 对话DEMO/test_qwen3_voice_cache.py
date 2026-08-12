"""
M0.1 多声音缓存单测: backend/tts/qwen3_tts.py 单值 _prompt_cache → Dict[str, Cache]

覆盖:
1. 单声音: load_voice_cache 正常, synthesize 使用对应 prompt
2. 多声音: A 加载 → B 加载 → A 重新调用, A 缓存未被 B 覆盖
3. 旧接口兼容: synthesize(text) / synthesize(text, voice=...) 无 voice_id 参数
4. 缓存管理接口: get_voice_cache / clear_voice_cache / get_voice_cache_stats
5. 回退: 未知 voice_id 回退默认 voice

运行: venv\Scripts\python.exe 对话DEMO\test_qwen3_voice_cache.py
（使用 FakeModel, 不加载真实模型 / 不占用 GPU）
"""
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.tts.qwen3_tts import Qwen3TTSEngine, DEFAULT_VOICE_ID


def _make_fake_wav(path: str):
    """生成一个真实的 1s 静音 wav, 通过引擎的文件存在性校验"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(np.zeros(24000, dtype=np.int16).tobytes())
    return str(path)


class FakePrompt:
    """模拟 create_voice_clone_prompt 返回值"""

    def __init__(self, voice_id: str):
        self.voice_id = voice_id
        self.x_vector = np.full(512, float(len(voice_id)), dtype=np.float32)


class FakeModel:
    """模拟 Qwen3TTSModel: 记录提取/合成调用, 返回确定性结果"""

    def __init__(self):
        self.created = []    # [(voice_id, ref_audio, x_vector_only_mode), ...]
        self.generated = []  # [(voice_id, text), ...]

    def create_voice_clone_prompt(self, ref_audio, x_vector_only_mode=True):
        voice_id = os.path.basename(str(ref_audio)).replace(".wav", "")
        self.created.append((voice_id, ref_audio, x_vector_only_mode))
        return FakePrompt(voice_id)

    def generate_voice_clone(self, text, language, voice_clone_prompt):
        self.generated.append((voice_clone_prompt.voice_id, text))
        return [np.zeros(2400, dtype=np.float32)], 24000


class VoiceCacheTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="qwen3_voice_cache_")
        cls.ref_a = _make_fake_wav(os.path.join(cls._tmpdir.name, "voice_a.wav"))
        cls.ref_b = _make_fake_wav(os.path.join(cls._tmpdir.name, "voice_b.wav"))
        cls.ref_default = _make_fake_wav(os.path.join(cls._tmpdir.name, "default.wav"))

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def setUp(self):
        self.engine = Qwen3TTSEngine()
        self.model = FakeModel()
        self.engine._model = self.model
        self.engine.is_loaded = True


class TestSingleVoice(VoiceCacheTestBase):
    """单声音: 正常加载与合成"""

    def test_load_cache_and_synthesize(self):
        cache = self.engine.load_voice_cache(
            "voice_a", ref_audio=self.ref_a
        )
        self.assertIsNotNone(cache)
        # 缓存结构: prompt / embedding / metadata
        self.assertIn("prompt", cache)
        self.assertIn("embedding", cache)
        self.assertIn("metadata", cache)
        self.assertEqual(cache["metadata"]["voice_id"], "voice_a")
        self.assertEqual(cache["metadata"]["ref_audio"], self.ref_a)

        audio, sr = self.engine.synthesize("你好", voice_id="voice_a")
        self.assertEqual(sr, 24000)
        self.assertGreater(len(audio), 0)
        self.assertEqual(self.model.generated[0], ("voice_a", "你好"))

    def test_load_failure_when_ref_audio_missing(self):
        cache = self.engine.load_voice_cache(
            "ghost", ref_audio=r"d:\nonexistent\missing.wav"
        )
        self.assertIsNone(cache)
        self.assertIsNone(self.engine.get_voice_cache("ghost"))


class TestMultiVoiceNoOverwrite(VoiceCacheTestBase):
    """多声音: A 加载 → B 加载 → A 重新调用, A 缓存不被 B 覆盖"""

    def test_a_cache_survives_b_load(self):
        self.engine.load_voice_cache("voice_a", ref_audio=self.ref_a)
        self.engine.load_voice_cache("voice_b", ref_audio=self.ref_b)

        # 缓存各自独立, 数量为 2
        self.assertEqual(len(self.engine._voice_caches), 2)
        self.assertIsNot(
            self.engine.get_voice_cache("voice_a")["prompt"],
            self.engine.get_voice_cache("voice_b")["prompt"],
        )

        # A → B → A 交替合成, 每次都用对的声音
        self.engine.synthesize("文本A", voice_id="voice_a")
        self.engine.synthesize("文本B", voice_id="voice_b")
        self.engine.synthesize("文本A2", voice_id="voice_a")

        self.assertEqual(
            [g[0] for g in self.model.generated],
            ["voice_a", "voice_b", "voice_a"],
        )
        # 每次 A 调用使用同一个 prompt 对象 (未被 B 覆盖/替换)
        prompt_a = self.engine.get_voice_cache("voice_a")["prompt"]
        self.assertEqual(self.model.generated[0][0], prompt_a.voice_id)
        self.assertEqual(self.model.generated[2][0], prompt_a.voice_id)

    def test_embedding_isolation(self):
        self.engine.load_voice_cache("voice_a", ref_audio=self.ref_a)
        self.engine.load_voice_cache("voice_b", ref_audio=self.ref_b)
        emb_a = self.engine.get_voice_cache("voice_a")["embedding"]
        emb_b = self.engine.get_voice_cache("voice_b")["embedding"]
        self.assertIsNot(emb_a, emb_b)


class TestBackwardCompat(VoiceCacheTestBase):
    """旧接口兼容: 不带 voice_id 的调用行为不变"""

    def test_synthesize_without_voice_id_uses_default(self):
        self.engine.load_voice_cache(DEFAULT_VOICE_ID, ref_audio=self.ref_default)
        audio, sr = self.engine.synthesize("旧接口调用")
        self.assertEqual(sr, 24000)
        self.assertEqual(self.model.generated[0], ("default", "旧接口调用"))

    def test_synthesize_with_voice_param_maps_to_voice_id(self):
        self.engine.load_voice_cache("voice_a", ref_audio=self.ref_a)
        audio, sr = self.engine.synthesize("带 voice 参数", voice="voice_a")
        self.assertEqual(self.model.generated[0], ("voice_a", "带 voice 参数"))

    def test_voice_id_wins_over_voice(self):
        self.engine.load_voice_cache("voice_a", ref_audio=self.ref_a)
        self.engine.load_voice_cache("voice_b", ref_audio=self.ref_b)
        self.engine.synthesize(
            "同时传参", voice="voice_a", voice_id="voice_b"
        )
        self.assertEqual(self.model.generated[0], ("voice_b", "同时传参"))

    def test_default_warmup_keeps_behavior(self):
        self.engine.load_voice_cache(DEFAULT_VOICE_ID, ref_audio=self.ref_default)
        self.engine._warmup_prompt()  # 已有缓存, 应跳过不重复提取
        self.assertEqual(len(self.model.created), 1)
        self.assertEqual(self.engine._prompt_cache, self.engine.get_voice_cache(DEFAULT_VOICE_ID)["prompt"])


class TestUnknownVoiceFallback(VoiceCacheTestBase):
    """未知 voice_id 回退默认 voice"""

    def test_fallback_to_default(self):
        self.engine.load_voice_cache(DEFAULT_VOICE_ID, ref_audio=self.ref_default)
        audio, sr = self.engine.synthesize("未知声音", voice_id="ghost")
        self.assertEqual(self.model.generated[0], ("default", "未知声音"))

    def test_no_cache_returns_mock_audio(self):
        # 没有任何缓存, 且未加载模型时走 mock 兜底 (不崩溃)
        self.engine._model = None
        self.engine.is_loaded = False
        audio, sr = self.engine.synthesize("无缓存兜底")
        self.assertEqual(sr, 24000)
        self.assertEqual(len(audio), int(max(0.5, len("无缓存兜底") * 0.05) * 24000))


class TestCacheManagement(VoiceCacheTestBase):
    """缓存管理接口: get / clear / stats"""

    def test_clear_single_voice(self):
        self.engine.load_voice_cache("voice_a", ref_audio=self.ref_a)
        self.engine.load_voice_cache("voice_b", ref_audio=self.ref_b)
        n = self.engine.clear_voice_cache("voice_a")
        self.assertEqual(n, 1)
        self.assertIsNone(self.engine.get_voice_cache("voice_a"))
        self.assertIsNotNone(self.engine.get_voice_cache("voice_b"))
        self.assertEqual(self.engine.clear_voice_cache("voice_a"), 0)  # 不存在返回 0

    def test_clear_all(self):
        self.engine.load_voice_cache("voice_a", ref_audio=self.ref_a)
        self.engine.load_voice_cache("voice_b", ref_audio=self.ref_b)
        n = self.engine.clear_voice_cache()
        self.assertEqual(n, 2)
        self.assertEqual(len(self.engine._voice_caches), 0)

    def test_stats(self):
        self.engine.load_voice_cache(DEFAULT_VOICE_ID, ref_audio=self.ref_default)
        self.engine.load_voice_cache("voice_b", ref_audio=self.ref_b)
        stats = self.engine.get_voice_cache_stats()
        self.assertEqual(stats["count"], 2)
        self.assertEqual(set(stats["voice_ids"]), {"default", "voice_b"})
        self.assertTrue(stats["has_default"])


class TestStreamCompat(VoiceCacheTestBase):
    """流式接口透传 voice_id"""

    def test_stream_passes_voice_id(self):
        self.engine.load_voice_cache("voice_a", ref_audio=self.ref_a)
        chunks = []

        async def run():
            async for audio, sr in self.engine.stream_synthesize_text(
                "流式测试", voice_id="voice_a"
            ):
                chunks.append((audio, sr))

        import asyncio
        asyncio.run(run())
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][1], 24000)
        self.assertEqual(self.model.generated[0], ("voice_a", "流式测试"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

