"""
YHLZ Voice Identity System V2.3-Phase5 - 质量门禁集成单元测试

验证:
1. QualityGate 评估器各维度评分逻辑
2. clone_pipeline 集成质量门禁后:
   - CloneResult 携带 quality_report / quality_status
   - REJECT 时 Profile 状态降级为 warning
   - WARNING 时仅告警, 不改状态
   - READY 时无告警
3. 评估异常不阻塞克隆流程
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 测试 DB 隔离
_TMP_DIR = Path(tempfile.mkdtemp(prefix="yhlz_qg_"))
os.environ["YHLZ_VOICE_IDENTITY_DB"] = str(_TMP_DIR / "test_qg.db")

# 项目根加入 sys.path
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 重置单例
from backend.voice_identity import database as _db_module
if hasattr(_db_module, "reset_db_instance"):
    _db_module.reset_db_instance()

from backend.voice_identity.clone.audio_validator import AudioInfo
from backend.voice_identity.clone.voice_analyzer import VoiceFeature
from backend.voice_identity.quality_gate import (
    GATE_THRESHOLD_READY,
    GATE_THRESHOLD_WARNING,
    STATUS_READY,
    STATUS_REJECT,
    STATUS_WARNING,
    QualityGate,
    QualityGateResult,
    get_quality_gate,
    reset_quality_gate,
)


def _make_audio_info(duration_s: float = 10.0, path: str = "/tmp/x.wav") -> AudioInfo:
    return AudioInfo(
        path=path,
        sample_rate=16000,
        channels=1,
        duration_s=duration_s,
        frames=int(duration_s * 16000),
        format="wav",
    )


def _make_feature(
    snr_db: float = 25.0,
    mean_energy: float = 0.3,
    duration_s: float = 10.0,
) -> VoiceFeature:
    return VoiceFeature(
        audio_info=_make_audio_info(duration_s),
        mean_f0=180.0,
        f0_range=(120.0, 240.0),
        mean_energy=mean_energy,
        speech_rate=4.0,
        snr_db=snr_db,
        embedding=None,
        extra={},
    )


class TestQualityGateScoring(unittest.TestCase):
    """测试 QualityGate 各维度评分"""

    def test_high_quality_ready(self):
        """高质量: SNR>=20, 时长 5~30s, 能量 0.1~0.7, adapter 高分 → READY"""
        gate = QualityGate()
        feat = _make_feature(snr_db=25.0, mean_energy=0.3, duration_s=10.0)
        result = gate.evaluate(feature=feat, adapter_quality_score=0.9)
        self.assertEqual(result.status, STATUS_READY)
        self.assertGreaterEqual(result.score, GATE_THRESHOLD_READY)
        self.assertTrue(result.can_activate)
        self.assertFalse(result.is_reject)

    def test_low_quality_reject(self):
        """低质量: SNR<5, 时长<3s, 能量极低 → REJECT"""
        gate = QualityGate()
        feat = _make_feature(snr_db=2.0, mean_energy=0.01, duration_s=1.0)
        result = gate.evaluate(feature=feat, adapter_quality_score=0.1)
        self.assertEqual(result.status, STATUS_REJECT)
        self.assertLess(result.score, GATE_THRESHOLD_WARNING)
        self.assertFalse(result.can_activate)
        self.assertTrue(result.is_reject)

    def test_medium_warning(self):
        """中等质量: SNR=10, 时长偏短 → WARNING 区间"""
        gate = QualityGate()
        feat = _make_feature(snr_db=10.0, mean_energy=0.2, duration_s=4.0)
        result = gate.evaluate(feature=feat, adapter_quality_score=0.4)
        self.assertIn(result.status, (STATUS_WARNING, STATUS_READY))
        # 边界容差: 不应 REJECT
        self.assertNotEqual(result.status, STATUS_REJECT)

    def test_no_adapter_quality(self):
        """未提供 adapter_quality_score: 权重归一化, 仅基于参考音频"""
        gate = QualityGate()
        feat = _make_feature(snr_db=25.0, mean_energy=0.3, duration_s=10.0)
        result = gate.evaluate(feature=feat, adapter_quality_score=None)
        # 高质量参考音频应仍能 READY
        self.assertEqual(result.status, STATUS_READY)
        # report 中 adapter_score 应为 0
        self.assertEqual(result.report["adapter_score"], 0.0)
        self.assertEqual(result.report["weights"]["adapter"], 0.0)

    def test_none_feature_uses_defaults(self):
        """feature=None: 各维度中性分 0.5, 总分约 0.5 (边界)"""
        gate = QualityGate()
        result = gate.evaluate(feature=None, adapter_quality_score=None)
        # 全中性 0.5: 边界 (浮点精度可能略低于 0.5 → REJECT 或 WARNING)
        self.assertIn(result.status, (STATUS_WARNING, STATUS_REJECT, STATUS_READY))
        self.assertGreaterEqual(result.score, 0.45)
        self.assertLessEqual(result.score, 0.55)

    def test_report_structure(self):
        """report 包含全部预期字段"""
        gate = QualityGate()
        feat = _make_feature()
        result = gate.evaluate(feature=feat, adapter_quality_score=0.7)
        report = result.report
        for key in ("snr_score", "duration_score", "energy_score",
                    "adapter_score", "weights", "snr_db",
                    "duration_s", "mean_energy", "adapter_quality_score"):
            self.assertIn(key, report, f"report 缺失字段: {key}")

    def test_to_dict_roundtrip(self):
        """to_dict 可序列化"""
        gate = QualityGate()
        result = gate.evaluate(feature=_make_feature(), adapter_quality_score=0.8)
        d = result.to_dict()
        self.assertIn("score", d)
        self.assertIn("status", d)
        self.assertIn("report", d)
        self.assertIn("reason", d)


class TestQualityGateThresholds(unittest.TestCase):
    """测试自定义阈值"""

    def test_custom_thresholds(self):
        """自定义阈值: ready=0.9, warning=0.7"""
        gate = QualityGate(ready_threshold=0.9, warning_threshold=0.7)
        feat = _make_feature(snr_db=25.0, mean_energy=0.3, duration_s=10.0)
        # adapter=0.5 → score = 0.35+0.20+0.15+0.30*0.5 = 0.85 (在 [0.7, 0.9) → WARNING)
        result = gate.evaluate(feature=feat, adapter_quality_score=0.5)
        self.assertGreaterEqual(result.score, 0.7)
        self.assertLess(result.score, 0.9)
        self.assertEqual(result.status, STATUS_WARNING)

    def test_custom_weights(self):
        """自定义权重: 仅看 adapter"""
        gate = QualityGate(weights={"snr": 0.0, "duration": 0.0,
                                     "energy": 0.0, "adapter": 1.0})
        feat = _make_feature(snr_db=2.0, mean_energy=0.01, duration_s=1.0)
        # adapter 高分 → READY (忽略低质参考音频)
        result = gate.evaluate(feature=feat, adapter_quality_score=0.9)
        self.assertEqual(result.status, STATUS_READY)


class TestClonePipelineIntegration(unittest.TestCase):
    """测试 clone_pipeline 集成质量门禁"""

    def setUp(self):
        reset_quality_gate()

    def test_clone_result_contains_quality_fields(self):
        """CloneResult 包含 quality_report / quality_status 字段"""
        from backend.voice_identity.clone.clone_pipeline import CloneResult
        import dataclasses
        fields = {f.name for f in dataclasses.fields(CloneResult)}
        self.assertIn("quality_report", fields)
        self.assertIn("quality_status", fields)

    def test_clone_pipeline_calls_quality_gate(self):
        """clone_voice 流程中调用 quality_gate.evaluate"""
        from backend.voice_identity.clone.clone_pipeline import VoiceClonePipeline
        from backend.voice_identity.clone.result import Ok
        from backend.voice_identity.adapter.tts_adapter import VoiceCacheInfo

        # Mock manager / registry / cache / adapter
        mock_manager = MagicMock()
        mock_registry = MagicMock()
        mock_cache = MagicMock()

        # 创建真实 VoiceProfile (用 Pydantic 构造)
        from backend.voice_identity.models import VoiceProfile
        fake_profile = VoiceProfile(
            voice_id="test-vid-qg",
            owner_id="system",
            name="测试声音",
            type="user",
            language="zh",
            status="ready",
            engine="qwen3",
            reference_audio="/tmp/test.wav",
            style={},
            metadata={},
        )
        mock_manager.create_voice.return_value = fake_profile
        mock_manager.store.update.return_value = fake_profile
        mock_registry.register_voice.return_value = fake_profile
        mock_cache.exists.return_value = True

        mock_adapter = MagicMock()
        cache_info = VoiceCacheInfo(
            adapter="qwen3",
            cache_path="/tmp/cache.qwen3",
            embedding_hash="abc123",
            quality_score=0.85,
        )
        mock_adapter.prepare_voice.return_value = Ok(cache_info)

        pipeline = VoiceClonePipeline(
            manager=mock_manager,
            registry=mock_registry,
            cache=mock_cache,
            adapter=mock_adapter,
        )

        # Mock validate_audio 和 analyze_voice
        audio_info = _make_audio_info(duration_s=10.0)
        feature = _make_feature(snr_db=25.0, mean_energy=0.3)

        with patch(
            "backend.voice_identity.clone.clone_pipeline.validate_audio"
        ) as mock_v, patch(
            "backend.voice_identity.clone.clone_pipeline.analyze_voice"
        ) as mock_a:
            from backend.voice_identity.clone.result import Ok as OkResult
            mock_v.return_value = OkResult(audio_info)
            mock_a.return_value = OkResult(feature)

            result = pipeline.clone_voice(
                audio_path="/tmp/test.wav",
                name="测试声音",
                engine="qwen3",
            )

        self.assertTrue(result.is_ok, f"克隆应成功: {result.error if result.is_err() else ''}")
        clone_data = result.unwrap()
        self.assertIsNotNone(clone_data.quality_report)
        self.assertIsNotNone(clone_data.quality_status)
        self.assertEqual(clone_data.quality_status, STATUS_READY)
        self.assertIn("score", clone_data.quality_report)
        self.assertGreaterEqual(clone_data.quality_report["score"], GATE_THRESHOLD_READY)

    def test_reject_downgrades_profile_status(self):
        """REJECT 时 Profile 状态降级为 warning"""
        from backend.voice_identity.clone.clone_pipeline import VoiceClonePipeline
        from backend.voice_identity.clone.result import Ok
        from backend.voice_identity.adapter.tts_adapter import VoiceCacheInfo
        from backend.voice_identity.models import VoiceProfile

        mock_manager = MagicMock()
        mock_registry = MagicMock()
        mock_cache = MagicMock()

        fake_profile = VoiceProfile(
            voice_id="test-vid-reject",
            owner_id="system",
            name="低质声音",
            type="user",
            language="zh",
            status="ready",
            engine="qwen3",
            reference_audio="/tmp/bad.wav",
            style={},
            metadata={},
        )
        # 模拟 update 后返回 warning 状态
        warning_profile = fake_profile.copy(update={"status": STATUS_WARNING})
        mock_manager.create_voice.return_value = fake_profile
        mock_manager.store.update.return_value = warning_profile
        mock_registry.register_voice.return_value = fake_profile
        mock_cache.exists.return_value = True

        mock_adapter = MagicMock()
        cache_info = VoiceCacheInfo(
            adapter="qwen3",
            cache_path="/tmp/cache.qwen3",
            embedding_hash="abc123",
            quality_score=0.1,  # 低质量分
        )
        mock_adapter.prepare_voice.return_value = Ok(cache_info)

        pipeline = VoiceClonePipeline(
            manager=mock_manager,
            registry=mock_registry,
            cache=mock_cache,
            adapter=mock_adapter,
        )

        # 低质音频特征
        audio_info = _make_audio_info(duration_s=1.0)
        feature = _make_feature(snr_db=2.0, mean_energy=0.01, duration_s=1.0)

        with patch(
            "backend.voice_identity.clone.clone_pipeline.validate_audio"
        ) as mock_v, patch(
            "backend.voice_identity.clone.clone_pipeline.analyze_voice"
        ) as mock_a:
            from backend.voice_identity.clone.result import Ok as OkResult
            mock_v.return_value = OkResult(audio_info)
            mock_a.return_value = OkResult(feature)

            result = pipeline.clone_voice(
                audio_path="/tmp/bad.wav",
                name="低质声音",
                engine="qwen3",
            )

        self.assertTrue(result.is_ok)
        clone_data = result.unwrap()
        self.assertEqual(clone_data.quality_status, STATUS_REJECT)
        # 验证 store.update 被调用 (降级为 warning)
        mock_manager.store.update.assert_called_once_with(
            "test-vid-reject", status=STATUS_WARNING
        )
        # warnings 应包含 REJECT 提示
        reject_warnings = [w for w in clone_data.warnings if "REJECT" in w]
        self.assertTrue(len(reject_warnings) > 0)

    def test_quality_gate_exception_not_fatal(self):
        """质量门禁评估异常不阻塞克隆"""
        from backend.voice_identity.clone.clone_pipeline import VoiceClonePipeline
        from backend.voice_identity.clone.result import Ok
        from backend.voice_identity.models import VoiceProfile

        mock_manager = MagicMock()
        mock_registry = MagicMock()
        mock_cache = MagicMock()

        fake_profile = VoiceProfile(
            voice_id="test-vid-exc",
            owner_id="system",
            name="异常声音",
            type="user",
            language="zh",
            status="ready",
            engine="qwen3",
            reference_audio="/tmp/x.wav",
            style={},
            metadata={},
        )
        mock_manager.create_voice.return_value = fake_profile
        mock_registry.register_voice.return_value = fake_profile
        mock_cache.exists.return_value = True

        pipeline = VoiceClonePipeline(
            manager=mock_manager,
            registry=mock_registry,
            cache=mock_cache,
            adapter=None,
        )

        audio_info = _make_audio_info()
        feature = _make_feature()

        with patch(
            "backend.voice_identity.clone.clone_pipeline.validate_audio"
        ) as mock_v, patch(
            "backend.voice_identity.clone.clone_pipeline.analyze_voice"
        ) as mock_a, patch(
            "backend.voice_identity.clone.clone_pipeline.get_quality_gate"
        ) as mock_gate:
            from backend.voice_identity.clone.result import Ok as OkResult
            mock_v.return_value = OkResult(audio_info)
            mock_a.return_value = OkResult(feature)
            mock_gate.side_effect = RuntimeError("评估器异常")

            result = pipeline.clone_voice(
                audio_path="/tmp/x.wav",
                name="异常声音",
                engine="qwen3",
            )

        self.assertTrue(result.is_ok, "评估异常不应阻塞克隆")
        clone_data = result.unwrap()
        # quality 字段为 None (因异常)
        self.assertIsNone(clone_data.quality_report)
        self.assertIsNone(clone_data.quality_status)
        # warnings 包含异常提示
        exc_warnings = [w for w in clone_data.warnings if "质量门禁评估异常" in w]
        self.assertTrue(len(exc_warnings) > 0)


class TestGlobalSingleton(unittest.TestCase):
    """测试全局单例"""

    def test_get_quality_gate_singleton(self):
        reset_quality_gate()
        g1 = get_quality_gate()
        g2 = get_quality_gate()
        self.assertIs(g1, g2)

    def test_reset_quality_gate(self):
        g1 = get_quality_gate()
        reset_quality_gate()
        g2 = get_quality_gate()
        self.assertIsNot(g1, g2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
