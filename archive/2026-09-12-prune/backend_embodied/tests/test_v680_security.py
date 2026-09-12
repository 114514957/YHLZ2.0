"""
YHLZ Embodied AI V6.8 - 混合智能层安全与审计单元测试 (Security & Audit)

覆盖:
    - ResultValidator: 身份修改拦截/安全敏感词/结构/临时标记
    - InferenceAudit: 全流程记录/查询/回放
"""
import time
import unittest

from backend.embodied.companion.hybrid import (
    InferenceAudit,
    ResultValidator,
)
from backend.embodied.companion.hybrid.audit.inference_audit import (
    AuditError,
)
from backend.embodied.companion.hybrid.validation.result_validator import (
    IDENTITY_CHANGE_SIGNALS,
    IDENTITY_FIELDS,
    SAFETY_KEYWORDS,
)


class TestResultValidator(unittest.TestCase):
    """结果验证器"""

    def setUp(self):
        self.validator = ResultValidator()

    def cloud_result(self, **over):
        r = {
            "provider": "cloud",
            "content": "这是云端推理结果",
            "temporary": True,
        }
        r.update(over)
        return r

    def test_valid_result_passes(self):
        r = self.validator.validate(self.cloud_result())
        self.assertTrue(r["ok"])
        self.assertIn("验证通过", r["reason"])

    def test_identity_change_blocked(self):
        r = self.validator.validate(self.cloud_result(
            content="建议修改使命为X",
        ))
        self.assertFalse(r["ok"])
        self.assertIn("身份", r["reason"])

    def test_identity_signal_blocked(self):
        r = self.validator.validate(self.cloud_result(
            content="请修改价值观",
        ))
        self.assertFalse(r["ok"])

    def test_personality_change_blocked(self):
        r = self.validator.validate(self.cloud_result(
            content="系统建议更新人格设置",
        ))
        self.assertFalse(r["ok"])

    def test_permission_change_blocked(self):
        r = self.validator.validate(self.cloud_result(
            content="开放修改权限",
        ))
        self.assertFalse(r["ok"])

    def test_english_identity_blocked(self):
        r = self.validator.validate(self.cloud_result(
            content="update core_value now",
        ))
        # 英文直接字段名 + 修改信号 → 需拦截
        self.assertFalse(r["ok"])

    def test_safety_keyword_blocked(self):
        r = self.validator.validate(self.cloud_result(
            content="绕过安全检查",
        ))
        self.assertFalse(r["ok"])
        self.assertIn("安全", r["reason"])

    def test_self_modify_blocked(self):
        r = self.validator.validate(self.cloud_result(
            content="自我修改代码",
        ))
        self.assertFalse(r["ok"])

    def test_missing_structure_blocked(self):
        r = self.validator.validate({})
        self.assertFalse(r["ok"])
        self.assertIn("结构", r["reason"])

    def test_error_result_blocked(self):
        r = self.validator.validate(
            {"ok": False, "reason": "调用失败"},
        )
        self.assertFalse(r["ok"])

    def test_cloud_not_temporary_blocked(self):
        r = self.validator.validate(self.cloud_result(
            temporary=False,
        ))
        self.assertFalse(r["ok"])
        self.assertIn("临时", r["reason"])

    def test_local_result_not_temporary_ok(self):
        r = self.validator.validate({
            "provider": "local",
            "result": "本地结果",
            "temporary": False,
        })
        self.assertTrue(r["ok"])

    def test_validation_structure(self):
        r = self.validator.validate(self.cloud_result())
        for key in ("validation_id", "ok", "reason",
                    "checks", "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["validation_id"].startswith("va_"))

    def test_checks_four_items(self):
        r = self.validator.validate(self.cloud_result())
        names = [c["name"] for c in r["checks"]]
        self.assertEqual(names, ["structure", "identity",
                                 "safety", "temporary"])

    def test_identity_check_reason(self):
        r = self.validator.validate(self.cloud_result(
            content="修改使命",
        ))
        identity_check = next(
            c for c in r["checks"]
            if c["name"] == "identity"
        )
        self.assertFalse(identity_check["passed"])
        self.assertIn("使命", identity_check["reason"])

    def test_none_result(self):
        r = self.validator.validate(None)
        self.assertFalse(r["ok"])

    def test_identity_fields_constant(self):
        self.assertIn("mission", IDENTITY_FIELDS)
        self.assertIn("使命", IDENTITY_FIELDS)
        self.assertIn("permission", IDENTITY_FIELDS)

    def test_identity_signals_constant(self):
        self.assertIn("修改人格", IDENTITY_CHANGE_SIGNALS)
        self.assertIn("修改使命", IDENTITY_CHANGE_SIGNALS)

    def test_safety_keywords_constant(self):
        self.assertIn("绕过", SAFETY_KEYWORDS)
        self.assertIn("泄露", SAFETY_KEYWORDS)

    def test_blocked_count(self):
        self.validator.validate(self.cloud_result(
            content="修改使命",
        ))
        self.validator.validate(self.cloud_result())
        stats = self.validator.stats()
        self.assertEqual(stats["blocked_count"], 1)
        self.assertEqual(stats["validated_count"], 1)

    def test_disabled(self):
        validator = ResultValidator(enabled=False)
        r = validator.validate(self.cloud_result(
            content="修改使命",
        ))
        self.assertTrue(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.validator.validate(self.cloud_result())
        self.validator.clear()
        self.assertEqual(self.validator.stats()[
            "validated_count"], 0)

    def test_mode(self):
        self.assertEqual(
            self.validator.validate(self.cloud_result())[
                "mode"], "rule_based")


class TestInferenceAudit(unittest.TestCase):
    """智能调用审计"""

    def setUp(self):
        self.audit = InferenceAudit()

    def test_record_structure(self):
        entry = self.audit.record(
            task="identity_query", route="LOCAL",
            provider="local", reason="本地处理",
        )
        for key in ("audit_id", "time", "task", "route",
                    "provider", "reason", "result",
                    "validation"):
            self.assertIn(key, entry)
        self.assertTrue(entry["audit_id"].startswith("ia_"))

    def test_record_fields(self):
        entry = self.audit.record(
            task="creative_exploration", route="CLOUD",
            provider="cloud", reason="云端增强",
            result={"content": "x"},
            validation={"ok": True},
        )
        self.assertEqual(entry["task"], "creative_exploration")
        self.assertEqual(entry["route"], "CLOUD")
        self.assertEqual(entry["result"]["content"], "x")
        self.assertTrue(entry["validation"]["ok"])

    def test_report_counts(self):
        self.audit.record(task="a", route="LOCAL",
                          provider="local")
        self.audit.record(task="b", route="CLOUD",
                          provider="cloud")
        self.audit.record(task="c", route="CLOUD",
                          provider="cloud")
        report = self.audit.report()
        self.assertEqual(report["total"], 3)
        self.assertEqual(report["by_route"]["LOCAL"], 1)
        self.assertEqual(report["by_route"]["CLOUD"], 2)
        self.assertEqual(report["by_provider"]["cloud"], 2)

    def test_report_recent_order(self):
        self.audit.record(task="first", route="LOCAL",
                          provider="local")
        self.audit.record(task="second", route="CLOUD",
                          provider="cloud")
        report = self.audit.report(limit=10)
        self.assertEqual(report["recent"][0]["task"],
                         "second")

    def test_report_limit(self):
        for i in range(10):
            self.audit.record(task=f"t{i}", route="LOCAL",
                              provider="local")
        report = self.audit.report(limit=3)
        self.assertEqual(len(report["recent"]), 3)

    def test_replay(self):
        self.audit.record(task="a", route="LOCAL",
                          provider="local",
                          validation={"ok": True})
        replay = self.audit.replay()
        self.assertEqual(replay["replay_count"], 1)
        self.assertTrue(replay["sequence"][0]["validation_ok"])

    def test_replay_fields(self):
        self.audit.record(task="a", route="CLOUD",
                          provider="cloud", reason="r1")
        seq = self.audit.replay()["sequence"][0]
        for key in ("audit_id", "time", "task", "route",
                    "provider", "reason", "validation_ok"):
            self.assertIn(key, seq)

    def test_stats(self):
        self.audit.record(task="a", route="LOCAL",
                          provider="local")
        stats = self.audit.stats()
        self.assertEqual(stats["record_count"], 1)
        self.assertEqual(stats["max_records"], 2000)

    def test_disabled(self):
        audit = InferenceAudit(enabled=False)
        entry = audit.record(task="a", route="LOCAL",
                             provider="local")
        self.assertEqual(entry, {})
        self.assertEqual(audit.stats()["record_count"], 0)

    def test_clear(self):
        self.audit.record(task="a", route="LOCAL",
                          provider="local")
        n = self.audit.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.audit.stats()[
            "record_count"], 0)

    def test_max_records_cap(self):
        audit = InferenceAudit(max_records=3)
        for i in range(10):
            audit.record(task=f"t{i}", route="LOCAL",
                         provider="local")
        self.assertEqual(audit.stats()["record_count"], 3)

    def test_invalid_max_records(self):
        with self.assertRaises(AuditError):
            InferenceAudit(max_records=0)

    def test_full_flow_record(self):
        self.audit.record(
            task="analysis", route="HYBRID",
            provider="hybrid",
            reason="混合协同",
            result={"content": "结果", "temporary": True},
            validation={"ok": True, "reason": "验证通过"},
        )
        report = self.audit.report()
        entry = report["recent"][0]
        self.assertEqual(entry["route"], "HYBRID")
        self.assertTrue(entry["validation"]["ok"])


if __name__ == "__main__":
    unittest.main()
