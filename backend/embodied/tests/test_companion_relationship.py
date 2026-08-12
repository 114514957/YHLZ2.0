"""
YHLZ Embodied AI V5.6 - 伙伴关系状态单元测试 (Relationship State)

覆盖 (relationship.py):
    - RelationshipState: trust/familiarity/communication_style/stage
    - 关系阶段: stranger/acquaintance/familiar/close/companion
    - 关系更新: 成功 → trust 提升 / 失败 → trust 下降
    - 长期稳定: trust>=0.6 且互动>=20 → familiarity 提升
    - 人格联动: 长期稳定 → warmth 建议 / 连续失败 → patience 建议
    - 参数校验: trust/familiarity 范围 / 非法沟通风格
"""
import unittest

from backend.embodied.companion import (
    COMMUNICATION_STYLES,
    FAMILIARITY_STEP,
    RelationshipError,
    RelationshipManager,
    RelationshipState,
    STAGE_THRESHOLDS,
    TRUST_STEP,
)


class TestRelationshipState(unittest.TestCase):
    """关系状态"""

    def test_default_state(self):
        """默认状态"""
        rel = RelationshipManager().relationship()
        self.assertEqual(rel["trust_level"], 0.5)
        self.assertEqual(rel["communication_style"], "casual")
        self.assertEqual(rel["interaction_count"], 0)

    def test_state_structure(self):
        """状态结构"""
        rel = RelationshipManager().relationship()
        for key in ("trust_level", "familiarity",
                    "communication_style", "interaction_count",
                    "relationship_stage"):
            self.assertIn(key, rel)

    def test_stage_familiar(self):
        """trust 0.5 → familiar"""
        state = RelationshipState(trust_level=0.5)
        self.assertEqual(state.relationship_stage, "familiar")

    def test_stage_stranger(self):
        """trust 0.1 → stranger"""
        state = RelationshipState(trust_level=0.1)
        self.assertEqual(state.relationship_stage, "stranger")

    def test_stage_acquaintance(self):
        """trust 0.3 → acquaintance"""
        state = RelationshipState(trust_level=0.3)
        self.assertEqual(state.relationship_stage, "acquaintance")

    def test_stage_close(self):
        """trust 0.7 → close"""
        state = RelationshipState(trust_level=0.7)
        self.assertEqual(state.relationship_stage, "close")

    def test_stage_companion(self):
        """trust 0.9 → companion"""
        state = RelationshipState(trust_level=0.9)
        self.assertEqual(state.relationship_stage, "companion")

    def test_stage_thresholds(self):
        """阶段阈值递增"""
        mins = [t["min"] for t in STAGE_THRESHOLDS]
        self.assertEqual(mins, sorted(mins))

    def test_communication_styles(self):
        """沟通风格白名单"""
        self.assertEqual(set(COMMUNICATION_STYLES),
                         {"casual", "warm", "formal", "playful"})

    def test_invalid_trust_raises(self):
        """trust 越界 → RelationshipError"""
        with self.assertRaises(RelationshipError):
            RelationshipState(trust_level=1.5)

    def test_invalid_style_raises(self):
        """非法沟通风格 → RelationshipError"""
        with self.assertRaises(RelationshipError):
            RelationshipState(communication_style="robot")


class TestRelationshipUpdate(unittest.TestCase):
    """关系更新"""

    def setUp(self):
        self.mgr = RelationshipManager()

    def test_update_success(self):
        """成功 → trust 提升"""
        before = self.mgr.relationship()["trust_level"]
        r = self.mgr.update(success=True)
        self.assertTrue(r["updated"])
        self.assertGreater(r["trust_level"], before)
        self.assertAlmostEqual(r["trust_level"] - before, TRUST_STEP)

    def test_update_failure(self):
        """失败 → trust 下降"""
        before = self.mgr.relationship()["trust_level"]
        r = self.mgr.update(success=False)
        self.assertLess(r["trust_level"], before)

    def test_update_interaction_count(self):
        """互动计数"""
        self.mgr.update(success=True)
        self.mgr.update(success=True)
        rel = self.mgr.relationship()
        self.assertEqual(rel["interaction_count"], 2)

    def test_update_changes_explainable(self):
        """更新原因可解释"""
        r = self.mgr.update(success=True)
        self.assertTrue(r["changes"])
        self.assertIn("成功互动", r["changes"][0])

    def test_update_success_breaks_failure_streak(self):
        """成功中断连续失败"""
        self.mgr.update(success=False)
        self.mgr.update(success=False)
        self.mgr.update(success=True)
        rel = self.mgr.relationship()
        self.assertEqual(rel["consecutive_failures"], 0)

    def test_update_stage_progression(self):
        """多次成功 → 阶段提升"""
        for _ in range(10):
            self.mgr.update(success=True)
        stage = self.mgr.relationship()["relationship_stage"]
        self.assertIn(stage, ("familiar", "close", "companion"))

    def test_update_disabled(self):
        """停用不更新"""
        mgr = RelationshipManager(enabled=False)
        r = mgr.update(success=True)
        self.assertFalse(r["updated"])
        self.assertIn("停用", r["reason"])

    def test_trust_upper_bound(self):
        """trust 上限 1.0"""
        state = RelationshipState(trust_level=0.99)
        mgr = RelationshipManager()
        mgr._state = state
        mgr.update(success=True)
        self.assertLessEqual(mgr.relationship()["trust_level"], 1.0)


class TestLongTermStable(unittest.TestCase):
    """长期稳定互动"""

    def test_familiarity_promoted(self):
        """trust>=0.6 且互动>=20 → familiarity 提升"""
        state = RelationshipState(trust_level=0.7, familiarity=0.3)
        mgr = RelationshipManager()
        mgr._state = state
        for _ in range(20):
            mgr.update(success=True)
        rel = mgr.relationship()
        self.assertGreater(rel["familiarity"], 0.3)
        self.assertTrue(mgr._state.long_term_stable)

    def test_familiarity_step(self):
        """熟悉度步长"""
        self.assertEqual(FAMILIARITY_STEP, 0.02)

    def test_not_stable_early(self):
        """互动不足 → 不提升熟悉度"""
        state = RelationshipState(trust_level=0.7, familiarity=0.3)
        mgr = RelationshipManager()
        mgr._state = state
        for _ in range(5):
            mgr.update(success=True)
        rel = mgr.relationship()
        self.assertEqual(rel["familiarity"], 0.3)


class TestPersonalityLink(unittest.TestCase):
    """人格-关系联动"""

    def setUp(self):
        self.mgr = RelationshipManager()

    def test_no_suggestion_initial(self):
        """初始无建议"""
        self.assertEqual(self.mgr.personality_adjustment(), [])

    def test_consecutive_fail_suggestion(self):
        """连续失败 → patience 建议"""
        self.mgr.update(success=False)
        self.mgr.update(success=False)
        suggestions = self.mgr.personality_adjustment()
        self.assertTrue(any("consecutive_fail" in s
                            for s in suggestions))

    def test_long_term_suggestion(self):
        """长期稳定 → warmth 建议"""
        state = RelationshipState(trust_level=0.7, familiarity=0.3)
        mgr = RelationshipManager()
        mgr._state = state
        for _ in range(20):
            mgr.update(success=True)
        suggestions = mgr.personality_adjustment()
        self.assertTrue(any("long_term_trust" in s
                            for s in suggestions))

    def test_suggestion_explainable(self):
        """建议可解释"""
        self.mgr.update(success=False)
        self.mgr.update(success=False)
        suggestions = self.mgr.personality_adjustment()
        self.assertIn("建议 patience", suggestions[0])


class TestValidation(unittest.TestCase):
    """校验"""

    def test_thresholds(self):
        """阈值暴露"""
        th = RelationshipManager().thresholds()
        self.assertEqual(th["trust_step"], TRUST_STEP)
        self.assertEqual(th["familiarity_step"], FAMILIARITY_STEP)
        self.assertTrue(th["enabled"])

    def test_reset(self):
        """重置"""
        mgr = RelationshipManager()
        mgr.update(success=True)
        mgr.reset()
        self.assertEqual(mgr.relationship()["interaction_count"], 0)
        self.assertEqual(mgr.relationship()["trust_level"], 0.5)


if __name__ == "__main__":
    unittest.main()
