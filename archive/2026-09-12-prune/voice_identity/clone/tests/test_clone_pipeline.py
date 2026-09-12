"""
YHLZ Voice Identity System V2.1 - Voice Clone Pipeline 单元测试

覆盖 (对齐 V2.1 测试 Prompt):
    1. Audio Validator: 正常/不存在/空文件/错误格式/超短音频
    2. Voice Analyzer: mock 音频输入 / feature 结构
    3. Clone Pipeline: validator → profile → registry → cache 流程
    4. Service Integration: VoiceIdentityService.clone_voice() 可调用
    5. Regression: create_voice/delete_voice/activate_voice/list_voice 无影响

运行:
    venv\\Scripts\\python.exe -m unittest backend.voice_identity.clone.tests.test_clone_pipeline -v

不依赖 GPU / TTS 引擎 / 真实音频; 全程 mock + 临时 DB。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

# 项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.voice_identity.clone import (  # noqa: E402
    AudioInfo,
    Err,
    Ok,
    Result,
    VoiceClonePipeline,
    analyze_voice,
    validate_audio,
)
from backend.voice_identity.clone.clone_pipeline import CloneResult  # noqa: E402
from backend.voice_identity.database import VoiceIdentityDB  # noqa: E402
from backend.voice_identity.manager import VoiceManager  # noqa: E402
from backend.voice_identity.models import VoiceProfile  # noqa: E402
from backend.voice_identity.profile import VoiceProfileStore  # noqa: E402
from backend.voice_identity.registry import VoiceRegistry  # noqa: E402
from backend.voice_identity.service import VoiceIdentityService  # noqa: E402


# ── 工具: 生成临时 wav ──

def _make_wav(path: str, duration_s: float = 5.0, sample_rate: int = 16000) -> str:
    """生成正弦波 wav 用于测试"""
    import math
    import struct

    n_frames = int(duration_s * sample_rate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        # 440Hz 正弦 + 微弱噪声, 写入 int16
        frames = bytearray()
        for i in range(n_frames):
            v = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sample_rate))
            frames.extend(struct.pack("<h", v))
        w.writeframes(bytes(frames))
    return path


# ── 1. Audio Validator ──

class TestAudioValidator(unittest.TestCase):
    """测试 validate_audio"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_v21_av_")
        self.valid_wav = _make_wav(
            os.path.join(self.tmp, "valid.wav"), duration_s=5.0
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_valid_audio(self):
        """正常音频 → Ok(AudioInfo)"""
        r = validate_audio(self.valid_wav)
        self.assertTrue(r.is_ok, f"应通过: {r.error}")
        info = r.unwrap()
        self.assertIsInstance(info, AudioInfo)
        self.assertEqual(info.sample_rate, 16000)
        self.assertGreaterEqual(info.duration_s, 4.9)
        self.assertEqual(info.channels, 1)

    def test_nonexistent_file(self):
        """不存在文件 → Err"""
        r = validate_audio(os.path.join(self.tmp, "nope.wav"))
        self.assertTrue(r.is_err())
        self.assertIn("不存在", str(r.error))

    def test_empty_file(self):
        """空文件 → Err"""
        p = os.path.join(self.tmp, "empty.wav")
        open(p, "wb").close()
        r = validate_audio(p)
        self.assertTrue(r.is_err())
        self.assertIn("空", str(r.error))

    def test_wrong_format(self):
        """错误格式 → Err"""
        p = os.path.join(self.tmp, "bad.xyz")
        with open(p, "wb") as f:
            f.write(b"\x00" * 100)
        r = validate_audio(p)
        self.assertTrue(r.is_err())
        self.assertIn("不支持", str(r.error))

    def test_too_short_audio(self):
        """超短音频 (<3s) → Err"""
        p = _make_wav(os.path.join(self.tmp, "short.wav"), duration_s=1.0)
        r = validate_audio(p)
        self.assertTrue(r.is_err())
        self.assertIn("过短", str(r.error))

    def test_directory_path(self):
        """目录而非文件 → Err"""
        r = validate_audio(self.tmp)
        self.assertTrue(r.is_err())
        self.assertIn("目录", str(r.error))


# ── 2. Voice Analyzer ──

class TestVoiceAnalyzer(unittest.TestCase):
    """测试 analyze_voice"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_v21_va_")
        self.wav = _make_wav(
            os.path.join(self.tmp, "a.wav"), duration_s=5.0
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_analyze_returns_feature(self):
        """mock/真实音频输入 → Ok(VoiceFeature)"""
        info = validate_audio(self.wav).unwrap()
        r = analyze_voice(info)
        self.assertTrue(r.is_ok, f"分析失败: {r.error}")
        feat = r.unwrap()
        # 字段结构检查
        self.assertEqual(feat.audio_info, info)
        self.assertIsNone(feat.embedding)  # 留空待 Pipeline 填充
        self.assertIsInstance(feat.extra, dict)

    def test_feature_to_style_metadata(self):
        """to_style_metadata 返回 dict"""
        info = validate_audio(self.wav).unwrap()
        feat = analyze_voice(info).unwrap()
        style = feat.to_style_metadata()
        self.assertIsInstance(style, dict)

    def test_analyze_degraded_when_librosa_missing(self):
        """librosa 不可用时应降级返 Ok(全 None 字段)"""
        info = validate_audio(self.wav).unwrap()
        # 强制模拟 librosa 不可用
        import backend.voice_identity.clone.voice_analyzer as va
        orig = va._extract_with_librosa
        va._extract_with_librosa = lambda ai: None
        try:
            r = analyze_voice(info)
            self.assertTrue(r.is_ok)
            feat = r.unwrap()
            self.assertIsNone(feat.mean_f0)
        finally:
            va._extract_with_librosa = orig


# ── 3. Clone Pipeline ──

class TestClonePipeline(unittest.TestCase):
    """测试 VoiceClonePipeline.clone_voice 流程"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_v21_cp_")
        self.db_path = os.path.join(self.tmp, "test.db")
        self.db = VoiceIdentityDB(self.db_path)
        self.store = VoiceProfileStore(self.db)
        self.registry = VoiceRegistry(self.store)
        # mock cache: exists 返 False (模拟未注入适配器)
        self.cache = MagicMock()
        self.cache.exists.return_value = False
        self.cache.prepare.return_value = False
        self.manager = VoiceManager(
            store=self.store, registry=self.registry, cache=self.cache
        )
        self.pipeline = VoiceClonePipeline(
            manager=self.manager, registry=self.registry, cache=self.cache
        )
        self.wav = _make_wav(
            os.path.join(self.tmp, "clone.wav"), duration_s=5.0
        )

    def tearDown(self):
        import shutil
        try:
            self.db.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clone_voice_success(self):
        """完整流程: validator → analyzer → profile → registry → cache"""
        r = self.pipeline.clone_voice(
            audio_path=self.wav, name="测试声音", engine="qwen3"
        )
        self.assertTrue(r.is_ok, f"克隆失败: {r.error}")
        result = r.unwrap()
        self.assertIsInstance(result, CloneResult)
        self.assertEqual(result.profile.name, "测试声音")
        self.assertEqual(result.profile.status, "ready")
        self.assertEqual(result.profile.engine, "qwen3")
        self.assertEqual(result.profile.reference_audio, self.wav)
        # registry 已注册 (可发现)
        self.assertIsNotNone(self.registry.get_voice(result.profile.voice_id))
        # cache.prepare 被调用过 (经 manager.create_voice)
        self.cache.prepare.assert_called()

    def test_clone_voice_invalid_audio(self):
        """音频验证失败 → Err, 不创建 Profile"""
        r = self.pipeline.clone_voice(
            audio_path=os.path.join(self.tmp, "nope.wav"), name="失败"
        )
        self.assertTrue(r.is_err())
        self.assertIn("[validate]", str(r.error))
        # 没有任何 Profile 被创建
        self.assertEqual(len(self.store.list()), 0)

    def test_clone_voice_cache_failure_keeps_profile(self):
        """Cache 失败不回滚 Profile, warnings 记录"""
        # exists 返 False 模拟 cache 未建立
        r = self.pipeline.clone_voice(
            audio_path=self.wav, name="缓存失败", engine="qwen3"
        )
        self.assertTrue(r.is_ok)
        result = r.unwrap()
        self.assertFalse(result.cache_prepared)
        self.assertTrue(any("Cache" in w or "缓存" in w for w in result.warnings))
        # Profile 仍存在
        self.assertIsNotNone(self.store.get(result.profile.voice_id))

    def test_clone_voice_preview(self):
        """preview 仅验证 + 分析, 不创建 Profile"""
        r = self.pipeline.preview(self.wav)
        self.assertTrue(r.is_ok)
        info, feat = r.unwrap()
        self.assertIsInstance(info, AudioInfo)
        self.assertEqual(len(self.store.list()), 0)

    def test_clone_voice_custom_voice_id(self):
        """显式 voice_id 生效"""
        r = self.pipeline.clone_voice(
            audio_path=self.wav, name="自定义ID",
            voice_id="custom_test_id_001"
        )
        self.assertTrue(r.is_ok)
        self.assertEqual(r.unwrap().profile.voice_id, "custom_test_id_001")

    def test_clone_voice_duplicate_id_rejected(self):
        """重复 voice_id → Err (store.create 抛异常)"""
        # 第一次
        r1 = self.pipeline.clone_voice(
            audio_path=self.wav, name="第一次", voice_id="dup_001"
        )
        self.assertTrue(r1.is_ok)
        # 第二次同 ID
        r2 = self.pipeline.clone_voice(
            audio_path=self.wav, name="第二次", voice_id="dup_001"
        )
        self.assertTrue(r2.is_err())
        self.assertIn("[create_voice]", str(r2.error))


# ── 4. Service Integration ──

class TestServiceIntegration(unittest.TestCase):
    """测试 VoiceIdentityService.clone_voice() 可调用"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_v21_sv_")
        self.db_path = os.path.join(self.tmp, "test.db")
        self.service = VoiceIdentityService.create_default(db=VoiceIdentityDB(self.db_path))
        self.wav = _make_wav(
            os.path.join(self.tmp, "svc.wav"), duration_s=5.0
        )

    def tearDown(self):
        import shutil
        try:
            self.service.db.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_service_clone_voice_callable(self):
        """Service.clone_voice() 返回 Result, 可正常调用"""
        r = self.service.clone_voice(
            audio_path=self.wav, name="Service 集成测试"
        )
        self.assertIsInstance(r, Result)
        self.assertTrue(r.is_ok, f"Service 调用失败: {r.error}")
        result = r.unwrap()
        self.assertIsInstance(result, CloneResult)
        self.assertEqual(result.profile.status, "ready")

    def test_service_clone_voice_failure_no_exception(self):
        """Service.clone_voice 失败返 Err, 不抛异常"""
        r = self.service.clone_voice(
            audio_path=os.path.join(self.tmp, "nope.wav"), name="失败"
        )
        self.assertTrue(r.is_err())
        # 不抛异常
        self.assertIsInstance(r.error, str)


# ── 5. Regression ──

class TestRegression(unittest.TestCase):
    """回归测试: 已有 create/delete/activate/list 接口无影响"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_v21_rg_")
        self.db_path = os.path.join(self.tmp, "test.db")
        self.service = VoiceIdentityService.create_default(db=VoiceIdentityDB(self.db_path))
        self.wav = _make_wav(
            os.path.join(self.tmp, "reg.wav"), duration_s=5.0
        )

    def tearDown(self):
        import shutil
        try:
            self.service.db.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_voice_still_works(self):
        """create_voice 仍可用"""
        p = self.service.create_voice(name="回归测试")
        self.assertIsInstance(p, VoiceProfile)
        self.assertEqual(p.status, "ready")

    def test_delete_voice_still_works(self):
        """delete_voice 仍可用"""
        p = self.service.create_voice(name="待删除")
        ok = self.service.delete_voice(p.voice_id, soft=True)
        self.assertTrue(ok)
        # 软删后状态 deleted
        self.assertEqual(self.service.get_voice(p.voice_id).status, "deleted")

    def test_activate_voice_still_works(self):
        """activate_voice (经 select_voice) 仍可用"""
        p = self.service.create_voice(name="待激活")
        activated = self.service.select_voice(p.voice_id)
        self.assertEqual(activated.status, "active")

    def test_list_voice_still_works(self):
        """list_voice 仍可用"""
        self.service.create_voice(name="列表1")
        self.service.create_voice(name="列表2")
        lst = self.service.list_voice()
        self.assertGreaterEqual(len(lst), 2)

    def test_clone_does_not_break_existing(self):
        """克隆后, 已有接口仍正常"""
        # 先克隆一个
        r = self.service.clone_voice(audio_path=self.wav, name="克隆声音")
        self.assertTrue(r.is_ok)
        # 再用 create_voice 创建一个
        p = self.service.create_voice(name="普通创建")
        # 两个都可见
        lst = self.service.list_voice()
        voice_ids = [v.voice_id for v in lst]
        self.assertIn(r.unwrap().profile.voice_id, voice_ids)
        self.assertIn(p.voice_id, voice_ids)
        # 删除克隆声音不影响另一个
        self.service.delete_voice(r.unwrap().profile.voice_id)
        self.assertIsNotNone(self.service.get_voice(p.voice_id))


# ── 6. Result 对象 ──

class TestResult(unittest.TestCase):
    """测试 Ok/Err 链式操作"""

    def test_ok_unwrap(self):
        r = Ok(42)
        self.assertTrue(r.is_ok)
        self.assertEqual(r.unwrap(), 42)

    def test_err_unwrap_or(self):
        r = Err("失败")
        self.assertTrue(r.is_err())
        self.assertEqual(r.unwrap_or(0), 0)

    def test_map_on_ok(self):
        r = Ok(2).map(lambda x: x * 21)
        self.assertTrue(r.is_ok)
        self.assertEqual(r.unwrap(), 42)

    def test_map_on_err_passthrough(self):
        r = Err("失败").map(lambda x: x * 2)
        self.assertTrue(r.is_err())

    def test_and_then_chaining(self):
        def step1(x):
            return Ok(x + 1)

        def step2(x):
            return Ok(x * 10)

        r = Ok(1).and_then(step1).and_then(step2)
        self.assertEqual(r.unwrap(), 20)

    def test_and_then_short_circuit(self):
        def fail(_):
            return Err("中断")

        r = Ok(1).and_then(fail).and_then(lambda x: Ok(x + 1))
        self.assertTrue(r.is_err())
        self.assertEqual(r.error, "中断")

    def test_unwrap_or_raise(self):
        r = Err("boom")
        with self.assertRaises(ValueError):
            r.unwrap_or_raise(ValueError)


if __name__ == "__main__":
    unittest.main(verbosity=2)
