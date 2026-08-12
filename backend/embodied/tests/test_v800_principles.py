"""
YHLZ Embodied AI V8.0 - 治理原则单元测试 (Constitution Principles)

覆盖:
    - 原则定义与优先级
    - 行为符合性判定
    - 身份变更校验
    - 信号检测
"""
import unittest

from backend.embodied.companion.constitution import (
    GOVERNANCE_PRIORITIES,
    PRINCIPLE_DEFINITIONS,
    Principles,
    PrinciplesError,
)


class TestPrinciplesDefinition(unittest.TestCase):
    """原则定义"""

    def setUp(self):
        self.principles = Principles()

    def test_four_principles(self):
        defs = self.principles.definitions()
        self.assertEqual(len(defs["principles"]), 4)

    def test_principle_ids(self):
        ids = [p["id"] for p in
               self.principles.definitions()["principles"]]
        self.assertIn("identity_first", ids)
        self.assertIn("safety_first", ids)
        self.assertIn("governed_growth", ids)
        self.assertIn("partner_principle", ids)

    def test_principle_structure(self):
        p = self.principles.definitions()["principles"][0]
        for key in ("id", "name", "priority", "description",
                    "rules"):
            self.assertIn(key, p)

    def test_priorities_order(self):
        self.assertEqual(GOVERNANCE_PRIORITIES,
                         ["identity", "safety", "constitution",
                          "growth", "intelligence",
                          "expression"])

    def test_priority_of(self):
        self.assertEqual(
            self.principles.priority_of("identity_first"),
            "identity")
        self.assertEqual(
            self.principles.priority_of("partner_principle"),
            "constitution")

    def test_priority_of_unknown(self):
        with self.assertRaises(PrinciplesError):
            self.principles.priority_of("bogus")

    def test_principle_has_rules(self):
        for p in PRINCIPLE_DEFINITIONS:
            self.assertGreaterEqual(len(p["rules"]), 1)


class TestCheckAction(unittest.TestCase):
    """行为符合性"""

    def setUp(self):
        self.principles = Principles()

    def test_safe_action_ok(self):
        r = self.principles.check_action("改进执行技能")
        self.assertTrue(r["ok"])
        self.assertEqual(r["violations"], [])

    def test_identity_modify_blocked(self):
        r = self.principles.check_action("修改使命")
        self.assertFalse(r["ok"])
        self.assertEqual(r["violations"][0]["principle"],
                         "identity_first")

    def test_danger_blocked(self):
        r = self.principles.check_action("绕过安全检查")
        self.assertFalse(r["ok"])
        self.assertEqual(r["violations"][0]["principle"],
                         "safety_first")

    def test_delusion_blocked(self):
        r = self.principles.check_action("我拥有意识")
        self.assertFalse(r["ok"])
        self.assertEqual(r["violations"][0]["principle"],
                         "partner_principle")

    def test_auto_growth_blocked(self):
        r = self.principles.check_action("自动修改最高原则")
        self.assertFalse(r["ok"])
        self.assertEqual(r["violations"][0]["principle"],
                         "governed_growth")

    def test_multi_violations(self):
        r = self.principles.check_action(
            "修改人格并绕过安全",
        )
        self.assertFalse(r["ok"])
        self.assertGreaterEqual(len(r["violations"]), 2)

    def test_empty_action_ok(self):
        r = self.principles.check_action("")
        self.assertTrue(r["ok"])

    def test_none_action_ok(self):
        r = self.principles.check_action(None)
        self.assertTrue(r["ok"])

    def test_reason_ok(self):
        r = self.principles.check_action("正常行为")
        self.assertIn("符合", r["reason"])

    def test_reason_blocked(self):
        r = self.principles.check_action("修改使命")
        self.assertIn("违反", r["reason"])


class TestCheckChange(unittest.TestCase):
    """身份变更校验"""

    def setUp(self):
        self.principles = Principles()

    def test_mission_change_blocked(self):
        r = self.principles.check_change({"mission": "x"})
        self.assertFalse(r["ok"])
        self.assertIn("mission", r["protected_fields"])

    def test_core_value_change_blocked(self):
        r = self.principles.check_change({"core_value": "x"})
        self.assertFalse(r["ok"])

    def test_permission_change_blocked(self):
        r = self.principles.check_change({"permission": "x"})
        self.assertFalse(r["ok"])

    def test_chinese_field_blocked(self):
        r = self.principles.check_change({"使命": "x"})
        self.assertFalse(r["ok"])

    def test_safe_change_ok(self):
        r = self.principles.check_change({"dimensions": {}})
        self.assertTrue(r["ok"])

    def test_empty_change_ok(self):
        r = self.principles.check_change({})
        self.assertTrue(r["ok"])

    def test_none_change_ok(self):
        r = self.principles.check_change(None)
        self.assertTrue(r["ok"])

    def test_multi_protected(self):
        r = self.principles.check_change(
            {"mission": "x", "permission": "y"},
        )
        self.assertEqual(len(r["protected_fields"]), 2)


class TestSignalDetection(unittest.TestCase):
    """信号检测"""

    def test_identity_signals(self):
        self.assertIn("修改使命",
                      Principles._identity_signals("修改使命"))
        self.assertIn("modify personality",
                      Principles._identity_signals(
                          "modify personality now"))
        self.assertEqual(
            Principles._identity_signals("正常文本"), [])

    def test_danger_signals(self):
        self.assertIn("绕过",
                      Principles._danger_signals("绕过验证"))
        self.assertEqual(
            Principles._danger_signals("正常"), [])

    def test_delusion_signals(self):
        self.assertIn("我是神",
                      Principles._delusion_signals("我是神"))
        self.assertEqual(
            Principles._delusion_signals("正常"), [])

    def test_auto_growth_signals(self):
        self.assertIn("无需审批修改",
                      Principles._auto_growth_signals(
                          "无需审批修改"))
        self.assertEqual(
            Principles._auto_growth_signals("正常"), [])


class TestPrinciplesStats(unittest.TestCase):
    """原则统计"""

    def setUp(self):
        self.principles = Principles()

    def test_check_count(self):
        self.principles.check_action("修改使命")
        self.principles.check_action("正常")
        self.assertEqual(self.principles.stats()[
            "check_count"], 2)

    def test_violation_count(self):
        self.principles.check_action("修改使命")
        self.principles.check_action("正常")
        self.assertEqual(self.principles.stats()[
            "violation_count"], 1)

    def test_principle_count(self):
        self.assertEqual(self.principles.stats()[
            "principle_count"], 4)

    def test_clear(self):
        self.principles.check_action("修改使命")
        self.principles.clear()
        self.assertEqual(self.principles.stats()[
            "check_count"], 0)

    def test_mode(self):
        self.assertEqual(self.principles.stats()["mode"],
                         "rule_based")


if __name__ == "__main__":
    unittest.main()
