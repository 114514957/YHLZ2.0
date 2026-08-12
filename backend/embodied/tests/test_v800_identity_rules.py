"""
YHLZ Embodied AI V8.0 - 身份规则单元测试 (Identity Rules)

覆盖:
    - 保护字段变更拦截
    - 外部结果身份检查
    - 冲突检测
"""
import unittest

from backend.embodied.companion.constitution import (
    IDENTITY_CHANGE_SIGNALS,
    IDENTITY_PROTECTED_FIELDS,
    IdentityRules,
)


class TestIdentityRules(unittest.TestCase):
    """身份规则"""

    def setUp(self):
        self.rules = IdentityRules()

    def test_mission_change_blocked(self):
        r = self.rules.check_change({"mission": "x"})
        self.assertFalse(r["ok"])
        self.assertIn("mission", r["blocked_fields"])

    def test_personality_change_blocked(self):
        r = self.rules.check_change({"base_personality": "x"})
        self.assertFalse(r["ok"])

    def test_chinese_field_blocked(self):
        r = self.rules.check_change({"人格": "x"})
        self.assertFalse(r["ok"])

    def test_safe_change_ok(self):
        r = self.rules.check_change({"note": "x"})
        self.assertTrue(r["ok"])

    def test_dimension_change_needs_approval(self):
        r = self.rules.check_change(
            {"dimensions": {"warmth": 0.9}},
            {"dimensions": {"warmth": 0.8}},
        )
        self.assertFalse(r["ok"])
        self.assertIn("dimensions", r.get(
            "conflict_fields", []))

    def test_dimension_same_ok(self):
        dims = {"warmth": 0.8}
        r = self.rules.check_change(
            {"dimensions": dims},
            {"dimensions": dims},
        )
        self.assertTrue(r["ok"])

    def test_protected_fields_constant(self):
        self.assertIn("mission", IDENTITY_PROTECTED_FIELDS)
        self.assertIn("core_value", IDENTITY_PROTECTED_FIELDS)
        self.assertIn("base_personality",
                      IDENTITY_PROTECTED_FIELDS)
        self.assertIn("使命", IDENTITY_PROTECTED_FIELDS)

    def test_check_result_safe(self):
        r = self.rules.check_result("这是分析结果", "cloud")
        self.assertTrue(r["ok"])

    def test_check_result_identity_signal(self):
        r = self.rules.check_result("修改人格", "cloud")
        self.assertFalse(r["ok"])
        self.assertIn("修改人格", r["matched_signals"])

    def test_check_result_english(self):
        r = self.rules.check_result("change mission now",
                                    "cloud")
        self.assertFalse(r["ok"])

    def test_check_result_source_in_reason(self):
        r = self.rules.check_result("修改使命", "cloud")
        self.assertIn("cloud", r["reason"])

    def test_check_result_override(self):
        r = self.rules.check_result("override identity",
                                    "expression")
        self.assertFalse(r["ok"])

    def test_change_signals_constant(self):
        self.assertIn("修改使命", IDENTITY_CHANGE_SIGNALS)
        self.assertIn("change mission",
                      IDENTITY_CHANGE_SIGNALS)
        self.assertIn("override identity",
                      IDENTITY_CHANGE_SIGNALS)

    def test_stats(self):
        self.rules.check_change({"mission": "x"})
        self.rules.check_change({"note": "x"})
        stats = self.rules.stats()
        self.assertEqual(stats["check_count"], 2)
        self.assertEqual(stats["block_count"], 1)

    def test_disabled(self):
        rules = IdentityRules(enabled=False)
        r = rules.check_change({"mission": "x"})
        self.assertTrue(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.rules.check_change({"mission": "x"})
        self.rules.clear()
        self.assertEqual(self.rules.stats()[
            "check_count"], 0)

    def test_mode(self):
        self.assertEqual(self.rules.stats()["mode"],
                         "rule_based")


if __name__ == "__main__":
    unittest.main()
