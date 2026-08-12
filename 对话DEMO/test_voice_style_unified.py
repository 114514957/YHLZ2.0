"""
M0.5 VoiceStyle 统一接口单测: Emotion → VoiceStyle → TTS Adapter

覆盖:
1. VoiceStyle 数据结构: 字段默认值 / to_dict / from_dict / merge
2. EMOTION_STYLE_MAP: 五情绪全覆盖 + 未知情绪回退
3. emotion_classifier 输出 VoiceStyle: emotion_to_voice_style / text_to_voice_style
4. 适配器接收 VoiceStyle (验收):
   - Qwen3TTSAdapter: voice_style.speed → rate 字符串翻译
   - GPTSovitsAdapter: voice_style.speed → speed_factor 数值翻译
5. 禁止 emotion 逻辑进入具体 TTS: 适配器只消费数值字段, emotion 标签不参与决策
6. 向后兼容: voice_style=None 时适配器走原路径, 不报错

运行: venv\Scripts\python.exe 对话DEMO\test_voice_style_unified.py
（使用 FakeModel / 假客户端, 不连接真实服务, 不依赖 GPU）
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
try:
    from unittest.mock import AsyncMock
except ImportError:
    AsyncMock = None  # Python <3.8 兜底

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from backend.tts.voice_style import (
    VoiceStyle,
    DEFAULT_VOICE_STYLE,
    EMOTION_STYLE_MAP,
    get_style_for_emotion,
    speed_to_rate,
)
from backend.emotion_classifier import (
    emotion_to_voice_style,
    text_to_voice_style,
    classify_emotion,
)


# ======================================================================
# 1. VoiceStyle 数据结构
# ======================================================================

class TestVoiceStyleDataclass(unittest.TestCase):

    def test_default_values(self):
        vs = VoiceStyle()
        self.assertEqual(vs.emotion, "neutral")
        self.assertEqual(vs.speed, 1.0)
        self.assertEqual(vs.pitch, 0.0)
        self.assertEqual(vs.energy, 1.0)

    def test_default_voice_style_constant(self):
        self.assertIsInstance(DEFAULT_VOICE_STYLE, VoiceStyle)
        self.assertEqual(DEFAULT_VOICE_STYLE.emotion, "neutral")
        self.assertEqual(DEFAULT_VOICE_STYLE.speed, 1.0)

    def test_to_dict_matches_task_example(self):
        """任务要求示例: {emotion, speed, pitch, energy}"""
        vs = VoiceStyle(emotion="happy", speed=1.1, pitch=3, energy=1.2)
        d = vs.to_dict()
        self.assertEqual(d, {"emotion": "happy", "speed": 1.1, "pitch": 3, "energy": 1.2})

    def test_from_dict_full(self):
        d = {"emotion": "sad", "speed": 0.9, "pitch": -2, "energy": 0.8}
        vs = VoiceStyle.from_dict(d)
        self.assertEqual(vs.emotion, "sad")
        self.assertEqual(vs.speed, 0.9)
        self.assertEqual(vs.pitch, -2.0)
        self.assertEqual(vs.energy, 0.8)

    def test_from_dict_none_returns_default(self):
        vs = VoiceStyle.from_dict(None)
        self.assertEqual(vs, DEFAULT_VOICE_STYLE)

    def test_from_dict_empty_returns_default(self):
        vs = VoiceStyle.from_dict({})
        self.assertEqual(vs, DEFAULT_VOICE_STYLE)

    def test_from_dict_partial_fills_defaults(self):
        vs = VoiceStyle.from_dict({"emotion": "happy"})
        self.assertEqual(vs.emotion, "happy")
        self.assertEqual(vs.speed, 1.0)  # 缺失回填
        self.assertEqual(vs.pitch, 0.0)
        self.assertEqual(vs.energy, 1.0)

    def test_merge_override_non_default(self):
        base = VoiceStyle(emotion="neutral", speed=1.0, pitch=0.0, energy=1.0)
        override = VoiceStyle(emotion="happy", speed=1.1, pitch=3, energy=1.2)
        merged = base.merge(override)
        self.assertEqual(merged.emotion, "happy")
        self.assertEqual(merged.speed, 1.1)
        self.assertEqual(merged.pitch, 3.0)
        self.assertEqual(merged.energy, 1.2)

    def test_merge_none_returns_self(self):
        base = VoiceStyle(emotion="calm", speed=0.95)
        merged = base.merge(None)
        self.assertEqual(merged, base)

    def test_merge_keeps_base_for_default_overrides(self):
        """override 默认值字段不覆盖 base 的自定义值"""
        base = VoiceStyle(emotion="happy", speed=1.1, pitch=3, energy=1.2)
        override = VoiceStyle()  # 全默认
        merged = base.merge(override)
        # override 全是默认值 → 保留 base
        self.assertEqual(merged.emotion, "happy")
        self.assertEqual(merged.speed, 1.1)


# ======================================================================
# 2. EMOTION_STYLE_MAP + 工具函数
# ======================================================================

class TestEmotionStyleMap(unittest.TestCase):

    def test_five_emotions_present(self):
        for e in ["happy", "calm", "sad", "angry", "neutral"]:
            self.assertIn(e, EMOTION_STYLE_MAP)

    def test_each_entry_has_four_fields(self):
        for emotion, style in EMOTION_STYLE_MAP.items():
            self.assertIn("emotion", style)
            self.assertIn("speed", style)
            self.assertIn("pitch", style)
            self.assertIn("energy", style)

    def test_get_style_for_emotion_happy(self):
        vs = get_style_for_emotion("happy")
        self.assertEqual(vs.emotion, "happy")
        self.assertEqual(vs.speed, 1.1)
        self.assertEqual(vs.pitch, 3.0)
        self.assertEqual(vs.energy, 1.2)

    def test_get_style_for_emotion_unknown_falls_back_neutral(self):
        vs = get_style_for_emotion("nonexistent_emotion")
        self.assertEqual(vs.emotion, "neutral")
        self.assertEqual(vs.speed, 1.0)

    def test_speed_to_rate_positive(self):
        self.assertEqual(speed_to_rate(1.1), "+10%")

    def test_speed_to_rate_zero(self):
        self.assertEqual(speed_to_rate(1.0), "+0%")

    def test_speed_to_rate_negative(self):
        self.assertEqual(speed_to_rate(0.9), "-10%")

    def test_speed_to_rate_rounds(self):
        self.assertEqual(speed_to_rate(1.155), "+16%")  # round(15.5) = 16


# ======================================================================
# 3. emotion_classifier 输出 VoiceStyle
# ======================================================================

class TestEmotionClassifierVoiceStyleOutput(unittest.TestCase):

    def test_emotion_to_voice_style_happy(self):
        vs = emotion_to_voice_style("happy")
        self.assertIsInstance(vs, VoiceStyle)
        self.assertEqual(vs.emotion, "happy")
        self.assertEqual(vs.speed, 1.1)

    def test_emotion_to_voice_style_unknown(self):
        vs = emotion_to_voice_style("xxx")
        self.assertEqual(vs.emotion, "neutral")
        self.assertEqual(vs.speed, 1.0)

    def test_text_to_voice_style_happy_text(self):
        """含 happy 关键词文本 → VoiceStyle(happy)"""
        vs = text_to_voice_style("哈哈太好了真棒", enabled=True, confidence_threshold=0.5)
        self.assertEqual(vs.emotion, "happy")
        self.assertEqual(vs.speed, 1.1)
        self.assertEqual(vs.pitch, 3.0)

    def test_text_to_voice_style_disabled_returns_default(self):
        vs = text_to_voice_style("哈哈太好了", enabled=False)
        self.assertEqual(vs, DEFAULT_VOICE_STYLE)

    def test_text_to_voice_style_empty_returns_default(self):
        vs = text_to_voice_style("", enabled=True)
        self.assertEqual(vs, DEFAULT_VOICE_STYLE)

    def test_text_to_voice_style_low_confidence_falls_back(self):
        """无情绪关键词文本 → 低置信度 → 回退默认"""
        vs = text_to_voice_style("今天天气不错", enabled=True, confidence_threshold=0.9)
        self.assertEqual(vs, DEFAULT_VOICE_STYLE)

    def test_text_to_voice_style_with_explicit_fallback(self):
        fallback = VoiceStyle(emotion="calm", speed=0.95)
        vs = text_to_voice_style("今天天气不错", enabled=True, confidence_threshold=0.9, fallback=fallback)
        self.assertEqual(vs.emotion, "calm")

    def test_emotion_output_is_voicestyle_not_string(self):
        """验收: Emotion 系统输出 VoiceStyle 对象, 不再是 Edge 音色字符串"""
        vs = text_to_voice_style("哈哈", enabled=True)
        self.assertIsInstance(vs, VoiceStyle)
        # 不应返回 Edge-TTS 音色 ID
        self.assertNotIn("zh-CN", vs.emotion)


# ======================================================================
# 4. Qwen3TTSAdapter 接收 VoiceStyle (验收)
# ======================================================================

class TestQwen3AdapterVoiceStyle(unittest.TestCase):
    """验收: Qwen3 适配器可接收统一 VoiceStyle 结构"""

    def _make_adapter_with_fake_engine(self):
        from backend.tts.adapters.qwen3_adapter import Qwen3TTSAdapter
        fake_engine = MagicMock()
        fake_engine.is_loaded = True
        fake_engine.synthesize.return_value = (np.zeros(100, dtype=np.float32), 24000)
        adapter = Qwen3TTSAdapter(engine=fake_engine)
        return adapter, fake_engine

    def test_generate_accepts_voice_style_without_error(self):
        adapter, fake_engine = self._make_adapter_with_fake_engine()
        vs = VoiceStyle(emotion="happy", speed=1.1, pitch=3, energy=1.2)
        audio, sr = adapter.generate("测试", voice_style=vs)
        self.assertEqual(sr, 24000)
        fake_engine.synthesize.assert_called_once()

    def test_voice_style_speed_translates_to_rate(self):
        """voice_style.speed=1.1 → rate='+10%' 传给底层 synthesize"""
        adapter, fake_engine = self._make_adapter_with_fake_engine()
        vs = VoiceStyle(speed=1.1)
        adapter.generate("测试", voice_style=vs)
        _, kwargs = fake_engine.synthesize.call_args
        self.assertEqual(kwargs.get("rate"), "+10%")

    def test_voice_style_speed_09_translates_to_negative_rate(self):
        adapter, fake_engine = self._make_adapter_with_fake_engine()
        vs = VoiceStyle(speed=0.9)
        adapter.generate("测试", voice_style=vs)
        _, kwargs = fake_engine.synthesize.call_args
        self.assertEqual(kwargs.get("rate"), "-10%")

    def test_voice_style_none_keeps_default_rate(self):
        """voice_style=None → 走原路径, rate='+0%'"""
        adapter, fake_engine = self._make_adapter_with_fake_engine()
        adapter.generate("测试", voice_style=None)
        _, kwargs = fake_engine.synthesize.call_args
        self.assertEqual(kwargs.get("rate"), "+0%")

    def test_voice_style_emotion_not_passed_to_engine(self):
        """验收: emotion 标签不进入底层引擎 (只消费数值字段)"""
        adapter, fake_engine = self._make_adapter_with_fake_engine()
        vs = VoiceStyle(emotion="happy", speed=1.1)
        adapter.generate("测试", voice_style=vs)
        args, kwargs = fake_engine.synthesize.call_args
        # synthesize 签名: (text, voice=, rate=, voice_id=, **kwargs)
        # emotion 不应出现在任何参数中
        all_args = list(args) + list(kwargs.keys())
        self.assertNotIn("emotion", all_args)
        self.assertNotIn("happy", all_args)

    def test_voice_style_pitch_ignored_silently(self):
        """Qwen3 不支持 pitch, 静默忽略不报错"""
        adapter, fake_engine = self._make_adapter_with_fake_engine()
        vs = VoiceStyle(pitch=5.0)
        # 不应抛异常
        audio, sr = adapter.generate("测试", voice_style=vs)
        self.assertEqual(sr, 24000)


# ======================================================================
# 5. GPTSovitsAdapter 接收 VoiceStyle (验收)
# ======================================================================

class TestGPTSovitsAdapterVoiceStyle(unittest.TestCase):
    """验收: GPT-SoVITS 适配器可接收统一 VoiceStyle 结构"""

    def _make_adapter_with_fake_client(self):
        from backend.tts.adapters.gpt_sovits_adapter import GPTSovitsAdapter
        adapter = GPTSovitsAdapter(base_url="http://fake:9872/")
        adapter.is_loaded = True
        fake_client = MagicMock()
        # predict / download_audio 是 async, 必须用 AsyncMock (否则 asyncio.run 报错)
        if AsyncMock is not None:
            fake_client.predict = AsyncMock(return_value=[{"url": "http://fake/audio.wav"}])
            fake_client.download_audio = AsyncMock(return_value=_make_wav_bytes())
        else:
            # Python <3.8 兜底: 用返回协程的普通 Mock
            async def _predict(*a, **k):
                return [{"url": "http://fake/audio.wav"}]
            async def _download(*a, **k):
                return _make_wav_bytes()
            fake_client.predict = _predict
            fake_client.download_audio = _download
        adapter._client = fake_client
        return adapter, fake_client

    def test_generate_accepts_voice_style_without_error(self):
        adapter, fake_client = self._make_adapter_with_fake_client()
        vs = VoiceStyle(emotion="happy", speed=1.1, pitch=3, energy=1.2)
        audio, sr = adapter.generate("测试", voice_style=vs)
        self.assertGreater(len(audio), 0)
        fake_client.predict.assert_called_once()

    def test_voice_style_speed_translates_to_speed_factor(self):
        """voice_style.speed=1.1 → speed_factor=1.1 传给 Gradio predict"""
        adapter, fake_client = self._make_adapter_with_fake_client()
        vs = VoiceStyle(speed=1.1)
        adapter.generate("测试", voice_style=vs)
        # predict 的第 13 个位置参数 (index 12) 是 speed_factor
        args = fake_client.predict.call_args[0]
        self.assertEqual(args[12], 1.1)  # speed_factor

    def test_voice_style_speed_09_translates(self):
        adapter, fake_client = self._make_adapter_with_fake_client()
        vs = VoiceStyle(speed=0.9)
        adapter.generate("测试", voice_style=vs)
        args = fake_client.predict.call_args[0]
        self.assertEqual(args[12], 0.9)

    def test_voice_style_none_uses_default_speed_factor(self):
        """voice_style=None → speed_factor 默认 1.0"""
        adapter, fake_client = self._make_adapter_with_fake_client()
        adapter.generate("测试", voice_style=None)
        args = fake_client.predict.call_args[0]
        self.assertEqual(args[12], 1.0)

    def test_voice_style_emotion_not_passed_to_gradio(self):
        """验收: emotion 标签不进入 Gradio predict 调用"""
        adapter, fake_client = self._make_adapter_with_fake_client()
        vs = VoiceStyle(emotion="angry", speed=1.05)
        adapter.generate("测试", voice_style=vs)
        args = fake_client.predict.call_args[0]
        # predict 参数列表中不应含 emotion 字符串
        for arg in args:
            self.assertNotEqual(arg, "angry")
            self.assertNotEqual(arg, "emotion")

    def test_voice_style_pitch_ignored_silently(self):
        """GPT-SoVITS 不支持 pitch, 静默忽略不报错"""
        adapter, fake_client = self._make_adapter_with_fake_client()
        vs = VoiceStyle(pitch=-2.0, speed=1.0)
        audio, sr = adapter.generate("测试", voice_style=vs)
        self.assertGreater(len(audio), 0)

    def test_explicit_speed_factor_overridden_by_voice_style(self):
        """voice_style 优先于 params 中的 speed_factor (统一接口覆盖私有参数)"""
        adapter, fake_client = self._make_adapter_with_fake_client()
        vs = VoiceStyle(speed=1.2)
        adapter.generate("测试", voice_style=vs, speed_factor=0.5)
        args = fake_client.predict.call_args[0]
        self.assertEqual(args[12], 1.2)  # voice_style 覆盖


# ======================================================================
# 6. 统一结构验收: 两适配器接收同一 VoiceStyle
# ======================================================================

class TestUnifiedVoiceStyleAcceptance(unittest.TestCase):
    """验收核心: 同一 VoiceStyle 对象可被 Qwen3 + GPT-SoVITS 同时接收"""

    def test_same_voicestyle_accepted_by_both_adapters(self):
        from backend.tts.adapters.qwen3_adapter import Qwen3TTSAdapter
        from backend.tts.adapters.gpt_sovits_adapter import GPTSovitsAdapter

        # 同一 VoiceStyle (来自 emotion 系统)
        shared_style = text_to_voice_style("哈哈太棒了", enabled=True, confidence_threshold=0.3)
        self.assertEqual(shared_style.emotion, "happy")

        # Qwen3 接收
        fake_qwen = MagicMock()
        fake_qwen.is_loaded = True
        fake_qwen.synthesize.return_value = (np.zeros(100, dtype=np.float32), 24000)
        qwen_adapter = Qwen3TTSAdapter(engine=fake_qwen)
        audio_q, sr_q = qwen_adapter.generate("测试", voice_style=shared_style)
        self.assertEqual(sr_q, 24000)

        # GPT-SoVITS 接收
        gpt_adapter = GPTSovitsAdapter(base_url="http://fake:9872/")
        gpt_adapter.is_loaded = True
        fake_client = MagicMock()
        if AsyncMock is not None:
            fake_client.predict = AsyncMock(return_value=[{"url": "http://fake/a.wav"}])
            fake_client.download_audio = AsyncMock(return_value=_make_wav_bytes())
        else:
            async def _p(*a, **k):
                return [{"url": "http://fake/a.wav"}]
            async def _d(*a, **k):
                return _make_wav_bytes()
            fake_client.predict = _p
            fake_client.download_audio = _d
        gpt_adapter._client = fake_client
        audio_g, sr_g = gpt_adapter.generate("测试", voice_style=shared_style)
        self.assertGreater(len(audio_g), 0)

        # 两者均成功接收同一 VoiceStyle, 无异常
        self.assertEqual(shared_style.speed, 1.1)
        # Qwen3 翻译为 rate='+10%'
        self.assertEqual(fake_qwen.synthesize.call_args.kwargs.get("rate"), "+10%")
        # GPT-SoVITS 翻译为 speed_factor=1.1
        self.assertEqual(fake_client.predict.call_args[0][12], 1.1)


def _make_wav_bytes(seconds: float = 0.1, sample_rate: int = 32000) -> bytes:
    """生成最小 WAV 字节 (供 GPT-SoVITS 解码)"""
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(np.zeros(int(seconds * sample_rate), dtype=np.int16).tobytes())
    return buf.getvalue()


# ======================================================================
# 7. 禁止 emotion 逻辑进入具体 TTS (代码静态检查)
# ======================================================================

class TestNoEmotionLogicInAdapters(unittest.TestCase):
    """验收: 适配器源码中不导入/不调用 emotion_classifier, 不做情绪分类"""

    def test_qwen3_adapter_does_not_import_emotion_classifier(self):
        import backend.tts.adapters.qwen3_adapter as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("emotion_classifier", src)
        self.assertNotIn("classify_emotion", src)
        self.assertNotIn("resolve_voice_for_emotion", src)

    def test_gpt_sovits_adapter_does_not_import_emotion_classifier(self):
        import backend.tts.adapters.gpt_sovits_adapter as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("emotion_classifier", src)
        self.assertNotIn("classify_emotion", src)
        self.assertNotIn("resolve_voice_for_emotion", src)

    def test_qwen3_adapter_uses_only_numeric_fields(self):
        """适配器源码引用 voice_style.speed, 不引用 voice_style.emotion 做决策"""
        import backend.tts.adapters.qwen3_adapter as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn("voice_style.speed", src)
        # emotion 字段不应被用于条件判断
        self.assertNotIn("voice_style.emotion ==", src)
        self.assertNotIn("emotion_to_voice_style", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
