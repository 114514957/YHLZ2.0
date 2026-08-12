"""
YHLZ Embodied AI V5.7 - 经历记忆 Service 集成测试
(Experience Memory via Service)

覆盖:
    - Service experience API (stats/relevant/reflection/audit)
    - handle 联动记录经历 (Interaction → Relationship → Personality → Experience)
    - 配置驱动: experience_enabled / max_records / decay_rate
    - 成长能力验证: 记录/抽取/查询/影响行为
    - 安全: 不写 Agent Memory / 不替代决策
    - 向后兼容
"""
import unittest

from backend.embodied.service import EmbodiedService


class TestServiceExperience(unittest.TestCase):
    """Service 经历 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_experience_stats_api(self):
        """companion_experience_stats"""
        st = self.svc.companion_experience_stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertIn("total", st)
        self.assertIn("by_type", st)

    def test_experience_relevant_api(self):
        """companion_experience_relevant"""
        results = self.svc.companion_experience_relevant("扫描")
        self.assertIsInstance(results, list)

    def test_experience_reflection_api(self):
        """companion_experience_reflection"""
        r = self.svc.companion_experience_reflection()
        for key in ("observation", "findings", "suggestion"):
            self.assertIn(key, r)

    def test_experience_audit_api(self):
        """companion_experience_audit"""
        aud = self.svc.companion_experience_audit()
        self.assertEqual(aud["mode"], "rule_based")
        self.assertIn("by_action", aud)

    def test_config_max_records(self):
        """配置驱动上限"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_experience_max_records": 5,
        })
        self.assertEqual(
            svc.companion_experience._store._max_records, 5)


class TestGrowthLoop(unittest.TestCase):
    """成长闭环 (handle 联动)"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_handle_records_experience(self):
        """handle 记录经历"""
        before = self.svc.companion_experience_stats()["total"]
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        after = self.svc.companion_experience_stats()["total"]
        self.assertGreater(after, before)

    def test_handle_experience_type(self):
        """handle 经历类型 (成功 → improvement)"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        st = self.svc.companion_experience_stats()
        self.assertGreaterEqual(st["by_type"].get("improvement", 0), 1)

    def test_experience_queryable_after_handle(self):
        """handle 后经验可查 (影响行为)"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        results = self.svc.companion_experience_relevant("扫描")
        self.assertGreaterEqual(len(results), 1)

    def test_full_growth_chain(self):
        """完整成长链: 互动 → 关系 → 人格 → 经历"""
        for _ in range(3):
            self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        # 关系更新
        rel = self.svc.companion_relationship()
        self.assertGreaterEqual(rel["interaction_count"], 3)
        # 人格调整
        p = self.svc.companion_personality()
        self.assertGreaterEqual(p["dimensions"]["warmth"], 0.8)
        # 经历记录
        st = self.svc.companion_experience_stats()
        self.assertGreaterEqual(st["total"], 3)
        # 反思报告
        ref = self.svc.companion_experience_reflection()
        self.assertTrue(ref["findings"])


class TestSafetyCompatV57(unittest.TestCase):
    """安全与兼容"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_no_memory_write(self):
        """经历不写 Agent Memory"""
        before = self.svc.memory.stats().get("total", 0)
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.svc.companion_experience_reflection()
        after = self.svc.memory.stats().get("total", 0)
        self.assertEqual(after, before)

    def test_no_chat_content(self):
        """经历不含完整聊天"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        st = self.svc.companion_experience_stats()
        # 只存统计与教训, 不含聊天字段
        self.assertIn("total", st)
        self.assertNotIn("chat", st)

    def test_v56_relationship_works(self):
        """V5.6 companion_relationship 兼容"""
        rel = self.svc.companion_relationship()
        self.assertIn("trust_level", rel)

    def test_v56_stability_works(self):
        """V5.6 companion_personality_stability 兼容"""
        st = self.svc.companion_personality_stability()
        self.assertIn("decay", st)

    def test_v55_personality_works(self):
        """V5.5 companion_personality 兼容"""
        p = self.svc.companion_personality()
        self.assertEqual(p["base"], "铁哥们")

    def test_v54_correct_works(self):
        """V5.4 companion_correct 兼容"""
        r = self.svc.companion_correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(r["success"])

    def test_version_5_7_0(self):
        """版本 = 9.5.0"""
        self.assertEqual(self.svc.report()["version"], "9.5.0")

    def test_experience_not_decision(self):
        """经历不替代决策 (handle 返回结构不变)"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertEqual(r["mode"], "rule_based")
        self.assertIn("aggregated", r)

    def test_experience_audit_tracks(self):
        """经历审计追踪"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        aud = self.svc.companion_experience_audit()
        self.assertGreaterEqual(aud["total"], 2)  # extract + store
        self.assertIn("extract", aud["by_action"])

    def test_experience_lesson_queryable(self):
        """经验教训可查 (影响行为)"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        results = self.svc.companion_experience_relevant("扫描")
        self.assertTrue(all("lesson" in r["record"]
                            for r in results))

    def test_experience_reflection_suggestion(self):
        """反思建议非空"""
        r = self.svc.companion_experience_reflection()
        self.assertTrue(r["suggestion"])


if __name__ == "__main__":
    unittest.main()
