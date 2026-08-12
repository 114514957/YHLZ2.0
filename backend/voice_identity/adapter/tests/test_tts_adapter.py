"""
YHLZ Voice Identity System V2.2 - TTS Adapter 单元测试

覆盖 (对齐 V2.2 测试 Prompt):
    1. Adapter mock 模式: prepare/synthesize 返回 Ok
    2. Qwen3 mock: prepare 成功, 返回 VoiceCacheInfo
    3. Qwen3 mock: prepare 失败 (音频不存在)
    4. Qwen3 mock: synthesize 成功, 返回 wav 路径
    5. GPT-SoVITS mock: 同上
    6. GPT-SoVITS real 模式: 缺 metadata 返 Err
    7. 注册表: register/get/list_adapters/build_adapter
    8. 配置加载: load_config + build_adapter_from_config
    9. Pipeline 集成: auto_prepare=True + adapter 注入, CloneResult 扩展字段填充

运行:
    venv\\Scripts\\python.exe -m unittest backend.voice_identity.adapter.tests.test_tts_adapter -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from backend.voice_identity.adapter import (  # noqa: E402
    GPTSoVITSAdapter,
    Qwen3TTSAdapter,
    build_adapter,
    list_adapters,
)
from backend.voice_identity.adapter.config import (  # noqa: E402
    VoiceCloneConfig,
    load_config,
    build_adapter_from_config,
)
from backend.voice_identity.adapter.tts_adapter import (  # noqa: E402
    TTSAdapter,
    VoiceCacheInfo,
)
from backend.voice_identity.clone.voice_analyzer import VoiceFeature  # noqa: E402
from backend.voice_identity.clone.audio_validator import AudioInfo, validate_audio  # noqa: E402


def _make_wav(path: str, duration_s: float = 5.0, sr: int = 16000) -> str:
    import math
    import struct
    n = int(duration_s * sr)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sr))
            frames.extend(struct.pack("<h", v))
        w.writeframes(bytes(frames))
    return path


class TestAdapterRegistry(unittest.TestCase):
    """测试 Adapter 注册表"""

    def test_list_adapters_contains_qwen3_and_gpt_sovits(self):
        names = list_adapters()
        self.assertIn("qwen3", names)
        self.assertIn("gpt_sovits", names)

    def test_build_adapter_qwen3_mock(self):
        r = build_adapter("qwen3", {"mode": "mock"})
        self.assertTrue(r.is_ok, r.error)
        self.assertIsInstance(r.unwrap(), Qwen3TTSAdapter)
        self.assertEqual(r.unwrap().name, "qwen3")

    def test_build_adapter_gpt_sovits_mock(self):
        r = build_adapter("gpt_sovits", {"mode": "mock"})
        self.assertTrue(r.is_ok, r.error)
        self.assertIsInstance(r.unwrap(), GPTSoVITSAdapter)

    def test_build_adapter_unknown_returns_err(self):
        r = build_adapter("nonexistent_engine", {})
        self.assertTrue(r.is_err())
        self.assertIn("未注册", str(r.error))

    def test_build_adapter_invalid_param_returns_err(self):
        # mode 非法
        r = build_adapter("qwen3", {"mode": "invalid_mode"})
        self.assertTrue(r.is_err())


class TestQwen3MockAdapter(unittest.TestCase):
    """测试 Qwen3 mock 模式"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_v22_q3_")
        self.wav = _make_wav(os.path.join(self.tmp, "a.wav"), 5.0)
        self.adapter = Qwen3TTSAdapter(
            mode="mock", cache_dir=os.path.join(self.tmp, "cache")
        )
        # 构造 VoiceFeature (经 validate_audio + 简化 feature)
        info_r = validate_audio(self.wav)
        self.audio_info = info_r.unwrap()
        self.feature = VoiceFeature(audio_info=self.audio_info)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prepare_success(self):
        """prepare 成功 → Ok(VoiceCacheInfo)"""
        r = self.adapter.prepare_voice(self.wav, self.feature)
        self.assertTrue(r.is_ok, r.error)
        info = r.unwrap()
        self.assertIsInstance(info, VoiceCacheInfo)
        self.assertEqual(info.adapter, "qwen3")
        self.assertIsNotNone(info.embedding_hash)
        self.assertTrue(info.embedding_hash.startswith("mock_"))
        self.assertIsNotNone(info.quality_score)
        self.assertGreater(info.quality_score, 0.0)
        self.assertLessEqual(info.quality_score, 1.0)

    def test_prepare_audio_not_exist(self):
        """prepare 失败: 音频不存在"""
        r = self.adapter.prepare_voice(
            os.path.join(self.tmp, "nope.wav"), self.feature
        )
        self.assertTrue(r.is_err())
        self.assertIn("不存在", str(r.error))

    def test_synthesize_success(self):
        """synthesize 成功 → Ok(wav 路径)"""
        r = self.adapter.synthesize("test_vid_001", "你好世界")
        self.assertTrue(r.is_ok, r.error)
        out = r.unwrap()
        self.assertTrue(os.path.exists(out))
        self.assertTrue(out.endswith(".wav"))

    def test_synthesize_empty_text(self):
        """synthesize 失败: 空文本"""
        r = self.adapter.synthesize("vid", "")
        self.assertTrue(r.is_err())
        self.assertIn("空", str(r.error))

    def test_synthesize_empty_voice_id(self):
        """synthesize 失败: 空 voice_id"""
        r = self.adapter.synthesize("", "你好")
        self.assertTrue(r.is_err())

    def test_can_serve_mock(self):
        """mock 模式 can_serve 总是 True"""
        self.assertTrue(self.adapter.can_serve())

    def test_health_check(self):
        h = self.adapter.health_check()
        self.assertEqual(h["name"], "qwen3")
        self.assertTrue(h["ok"])


class TestGPTSoVITSAdapter(unittest.TestCase):
    """测试 GPT-SoVITS mock + real 失败"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_v22_gs_")
        self.wav = _make_wav(os.path.join(self.tmp, "a.wav"), 5.0)
        self.adapter = GPTSoVITSAdapter(
            mode="mock", cache_dir=os.path.join(self.tmp, "cache")
        )
        info_r = validate_audio(self.wav)
        self.audio_info = info_r.unwrap()
        self.feature = VoiceFeature(audio_info=self.audio_info)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mock_prepare_success(self):
        r = self.adapter.prepare_voice(self.wav, self.feature)
        self.assertTrue(r.is_ok, r.error)
        info = r.unwrap()
        self.assertEqual(info.adapter, "gpt_sovits")
        self.assertTrue(info.embedding_hash.startswith("gptsv_"))

    def test_mock_synthesize_success(self):
        r = self.adapter.synthesize("vid_001", "测试")
        self.assertTrue(r.is_ok, r.error)
        self.assertTrue(os.path.exists(r.unwrap()))

    def test_real_missing_metadata_returns_err(self):
        """real 模式缺 metadata → Err"""
        real_adapter = GPTSoVITSAdapter(mode="real", gradio_url="http://129.5.0.1:9999")
        r = real_adapter.prepare_voice(self.wav, self.feature, metadata=None)
        self.assertTrue(r.is_err())
        self.assertIn("metadata", str(r.error))

    def test_real_can_serve_no_gradio(self):
        """real 模式无 Gradio 服务 → can_serve False"""
        real_adapter = GPTSoVITSAdapter(mode="real", gradio_url="http://129.5.0.1:9999")
        self.assertFalse(real_adapter.can_serve())


class TestConfigLoader(unittest.TestCase):
    """测试配置加载器"""

    def test_load_config_default(self):
        """load_config 不存在文件 → 默认配置"""
        cfg = load_config("/nonexistent/path.json")
        self.assertIsInstance(cfg, VoiceCloneConfig)
        self.assertEqual(cfg.default_engine, "qwen3")
        self.assertTrue(cfg.auto_prepare)

    def test_load_config_from_project(self):
        """从项目 voice_clone_config.json 加载"""
        cfg = load_config()
        self.assertEqual(cfg.default_engine, "qwen3")
        self.assertEqual(cfg.qwen3.mode, "mock")
        self.assertEqual(cfg.gpt_sovits.mode, "mock")

    def test_build_adapter_from_config_qwen3(self):
        """根据配置构造 qwen3 adapter"""
        cfg = load_config()
        r = build_adapter_from_config("qwen3", cfg)
        self.assertTrue(r.is_ok, r.error)
        self.assertIsInstance(r.unwrap(), Qwen3TTSAdapter)

    def test_build_adapter_from_config_gpt_sovits(self):
        r = build_adapter_from_config("gpt_sovits", load_config())
        self.assertTrue(r.is_ok, r.error)
        self.assertIsInstance(r.unwrap(), GPTSoVITSAdapter)

    def test_build_adapter_from_config_unknown(self):
        r = build_adapter_from_config("unknown_engine", load_config())
        self.assertTrue(r.is_err())


class TestPipelineWithAdapter(unittest.TestCase):
    """测试 Pipeline + Adapter 集成 (auto_prepare)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_v22_pl_")
        from backend.voice_identity.database import VoiceIdentityDB
        from backend.voice_identity.manager import VoiceManager
        from backend.voice_identity.profile import VoiceProfileStore
        from backend.voice_identity.registry import VoiceRegistry
        from unittest.mock import MagicMock
        from backend.voice_identity.clone.clone_pipeline import VoiceClonePipeline

        self.db = VoiceIdentityDB(os.path.join(self.tmp, "t.db"))
        self.store = VoiceProfileStore(self.db)
        self.registry = VoiceRegistry(self.store)
        self.cache = MagicMock()
        self.cache.exists.return_value = False
        self.manager = VoiceManager(store=self.store, registry=self.registry, cache=self.cache)
        self.adapter = Qwen3TTSAdapter(mode="mock", cache_dir=os.path.join(self.tmp, "cache"))
        self.pipeline = VoiceClonePipeline(
            manager=self.manager, registry=self.registry, cache=self.cache,
            adapter=self.adapter,
        )
        self.wav = _make_wav(os.path.join(self.tmp, "p.wav"), 5.0)

    def tearDown(self):
        import shutil
        try: self.db.close()
        except: pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clone_with_auto_prepare_fills_v22_fields(self):
        """auto_prepare=True + adapter → CloneResult 扩展字段填充"""
        r = self.pipeline.clone_voice(self.wav, "测试V22", auto_prepare=True)
        self.assertTrue(r.is_ok, r.error)
        result = r.unwrap()
        # V2.2 扩展字段
        self.assertEqual(result.adapter, "qwen3")
        self.assertIsNotNone(result.embedding_hash)
        self.assertTrue(result.embedding_hash.startswith("mock_"))
        self.assertIsNotNone(result.quality_score)
        # cache_path 在 mock 模式为 None
        self.assertIsNone(result.cache_path)

    def test_clone_with_auto_prepare_false_skips_adapter(self):
        """auto_prepare=False → 扩展字段全 None (V2.1 行为)"""
        r = self.pipeline.clone_voice(self.wav, "测试无prepare", auto_prepare=False)
        self.assertTrue(r.is_ok, r.error)
        result = r.unwrap()
        self.assertIsNone(result.adapter)
        self.assertIsNone(result.embedding_hash)
        self.assertIsNone(result.quality_score)

    def test_clone_no_adapter_auto_prepare_true_v21_compat(self):
        """无 adapter + auto_prepare=True → V2.1 兼容 (扩展字段 None)"""
        from backend.voice_identity.clone.clone_pipeline import VoiceClonePipeline
        pipeline_no_adapter = VoiceClonePipeline(
            manager=self.manager, registry=self.registry, cache=self.cache,
            adapter=None,
        )
        r = pipeline_no_adapter.clone_voice(self.wav, "无adapter", auto_prepare=True)
        self.assertTrue(r.is_ok, r.error)
        result = r.unwrap()
        self.assertIsNone(result.adapter)
        self.assertIsNone(result.quality_score)

    def test_clone_adapter_failure_keeps_profile(self):
        """Adapter.prepare 失败 → 仍返 Ok, warnings 记录, Profile 保留"""
        from backend.voice_identity.adapter.tts_adapter import TTSAdapter
        from backend.voice_identity.clone.clone_pipeline import VoiceClonePipeline
        from backend.voice_identity.clone.result import Err

        class FailingAdapter(TTSAdapter):
            name = "failing"
            def prepare_voice(self, audio_path, feature, metadata=None):
                return Err("模拟 prepare 失败")
            def synthesize(self, voice_id, text, language="zh"):
                return Err("不实现")

        pipeline = VoiceClonePipeline(
            manager=self.manager, registry=self.registry, cache=self.cache,
            adapter=FailingAdapter(),
        )
        r = pipeline.clone_voice(self.wav, "失败adapter", auto_prepare=True)
        self.assertTrue(r.is_ok, r.error)
        result = r.unwrap()
        self.assertIsNone(result.adapter)  # 失败时不填充
        self.assertTrue(any("Adapter" in w or "prepare" in w for w in result.warnings))
        # Profile 仍存在
        self.assertIsNotNone(self.store.get(result.profile.voice_id))


if __name__ == "__main__":
    unittest.main(verbosity=2)
