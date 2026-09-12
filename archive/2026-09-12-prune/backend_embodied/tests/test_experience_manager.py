"""
YHLZ Embodied AI V5.7 - 经历管理器单元测试 (Experience Manager)

覆盖 (experience_manager.py + extractor + query + audit):
    - 生命周期: store/retrieve/update/decay/forget
    - 经验抽取: 成功/失败/关系/决策/工程 (5 类型)
    - 查询: 类型/相关检索/最佳教训
    - Reflection Report: Observation/发现/Suggestion
    - 审计: 操作追踪
    - 经历影响行为: relevant 供参考
"""
import unittest

from backend.embodied.companion.experience import (
    ExperienceManager,
    ExperienceRecord,
)


class TestManagerLifecycle(unittest.TestCase):
    """管理器生命周期"""

    def setUp(self):
        self.mgr = ExperienceManager()

    def test_store_retrieve(self):
        """存储检索"""
        rec = ExperienceRecord.create(type="failure", trigger="拾取失败",
                                      lesson="先扫描再拾取")
        d = self.mgr.store(rec)
        self.assertEqual(d["id"], rec.id)
        got = self.mgr.retrieve(rec.id)
        self.assertEqual(got["lesson"], "先扫描再拾取")

    def test_retrieve_missing(self):
        """检索不存在 → None"""
        self.assertIsNone(self.mgr.retrieve("nope"))

    def test_update(self):
        """更新"""
        rec = ExperienceRecord.create(type="failure", trigger="t",
                                      lesson="l")
        self.mgr.store(rec)
        updated = self.mgr.update(rec.id, lesson="新教训", value=0.9)
        self.assertEqual(updated["lesson"], "新教训")
        self.assertEqual(updated["value"], 0.9)

    def test_forget(self):
        """遗忘"""
        rec = ExperienceRecord.create(type="failure", trigger="t",
                                      lesson="l")
        self.mgr.store(rec)
        self.assertTrue(self.mgr.forget(rec.id))
        self.assertIsNone(self.mgr.retrieve(rec.id))

    def test_decay(self):
        """衰减"""
        rec = ExperienceRecord.create(type="failure", trigger="t",
                                      lesson="l", value=0.6)
        self.mgr.store(rec)
        forgotten = self.mgr.decay(decay_rate=0.5, min_value=0.2)
        self.assertEqual(forgotten, [])
        self.assertEqual(self.mgr.stats()["total"], 1)

    def test_clear(self):
        """清空"""
        rec = ExperienceRecord.create(type="failure", trigger="t",
                                      lesson="l")
        self.mgr.store(rec)
        self.assertEqual(self.mgr.clear(), 1)
        self.assertEqual(self.mgr.stats()["total"], 0)


class TestExtractor(unittest.TestCase):
    """经验抽取"""

    def setUp(self):
        self.mgr = ExperienceManager()

    def test_store_from_event_success(self):
        """成功事件 → improvement 经验"""
        d = self.mgr.store_from_event(
            success=True, trigger="拾取台灯", source="run_goal",
        )
        self.assertEqual(d["type"], "improvement")
        self.assertIn("可复用", d["lesson"])

    def test_store_from_event_failure(self):
        """失败事件 → failure 经验"""
        d = self.mgr.store_from_event(
            success=False, trigger="拾取幽灵", source="run_goal",
        )
        self.assertEqual(d["type"], "failure")
        self.assertIn("调整策略", d["lesson"])

    def test_store_relationship_experience(self):
        """关系经验"""
        d = self.mgr.store_relationship_experience(
            trust_level=0.7, interaction_count=25,
        )
        self.assertEqual(d["type"], "interaction")
        self.assertIn("维持稳定互动", d["lesson"])

    def test_store_engineering_experience(self):
        """工程经验"""
        d = self.mgr.store_engineering_experience(
            trigger="完成V5.6开发", lesson="关系系统独立于人格",
            result="测试通过",
        )
        self.assertEqual(d["type"], "engineering")
        self.assertEqual(d["lesson"], "关系系统独立于人格")

    def test_failure_confidence(self):
        """失败经验置信度"""
        d = self.mgr.store_from_event(
            success=False, trigger="t", source="x",
        )
        self.assertGreaterEqual(d["confidence"], 0.5)

    def test_success_confidence(self):
        """成功经验置信度"""
        d = self.mgr.store_from_event(
            success=True, trigger="t", source="x",
        )
        self.assertGreaterEqual(d["confidence"], 0.8)


class TestQuery(unittest.TestCase):
    """经验查询"""

    def setUp(self):
        self.mgr = ExperienceManager()
        self.mgr.store_from_event(success=False, trigger="拾取失败")
        self.mgr.store_from_event(success=True, trigger="扫描成功")
        self.mgr.store_engineering_experience(
            trigger="开发", lesson="先设计后编码",
        )

    def test_by_type(self):
        """按类型查询"""
        failures = self.mgr.by_type("failure")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["type"], "failure")

    def test_by_type_invalid(self):
        """非法类型 → 异常"""
        from backend.embodied.companion.experience import (
            ExperienceQueryError,
        )
        with self.assertRaises(ExperienceQueryError):
            self.mgr.by_type("hack")

    def test_relevant(self):
        """相关检索"""
        results = self.mgr.relevant(trigger="拾取")
        self.assertGreaterEqual(len(results), 1)
        self.assertIn("score", results[0])
        self.assertIn("reason", results[0])

    def test_relevant_type_filter(self):
        """相关检索类型过滤"""
        results = self.mgr.relevant(trigger="开发", type="engineering")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["record"]["type"], "engineering")

    def test_relevant_no_match(self):
        """无相关 → 空"""
        results = self.mgr.relevant(trigger="zzz")
        self.assertEqual(results, [])

    def test_stats(self):
        """统计"""
        st = self.mgr.stats()
        self.assertEqual(st["total"], 3)
        self.assertIn("engineering", st["by_type"])


class TestReflection(unittest.TestCase):
    """反思报告"""

    def setUp(self):
        self.mgr = ExperienceManager()

    def test_reflection_empty(self):
        """空经历 → 报告"""
        r = self.mgr.reflection_report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertIn("observation", r)
        self.assertIn("findings", r)
        self.assertIn("suggestion", r)

    def test_reflection_with_experiences(self):
        """有经历 → 报告含统计"""
        self.mgr.store_from_event(success=True, trigger="扫描")
        self.mgr.store_from_event(success=False, trigger="拾取")
        r = self.mgr.reflection_report()
        self.assertTrue(r["findings"])
        self.assertIn("2 条经历", r["findings"][0])

    def test_reflection_failure_suggestion(self):
        """高频失败 → 建议"""
        for _ in range(5):
            self.mgr.store_from_event(success=False, trigger="拾取失败")
        r = self.mgr.reflection_report()
        self.assertIn("拾取失败", r["suggestion"])
        self.assertIn("建议", r["suggestion"])


class TestAudit(unittest.TestCase):
    """审计"""

    def setUp(self):
        self.mgr = ExperienceManager()

    def test_audit_after_ops(self):
        """操作后审计"""
        self.mgr.store_from_event(success=True, trigger="扫描")
        self.mgr.store_from_event(success=False, trigger="拾取")
        aud = self.mgr.audit()
        self.assertEqual(aud["total"], 4)  # extract + store ×2
        self.assertEqual(aud["mode"], "rule_based")

    def test_audit_by_action(self):
        """审计动作分布"""
        self.mgr.store_from_event(success=True, trigger="扫描")
        aud = self.mgr.audit()
        self.assertIn("extract", aud["by_action"])
        self.assertIn("store", aud["by_action"])


class TestInfluenceBehavior(unittest.TestCase):
    """经历影响未来行为"""

    def setUp(self):
        self.mgr = ExperienceManager()

    def test_lesson_available(self):
        """经验教训可查 (供行为参考)"""
        self.mgr.store_from_event(
            success=False, trigger="拾取失败",
            action="pick", result="position_mismatch",
        )
        results = self.mgr.relevant(trigger="拾取", limit=1)
        self.assertEqual(len(results), 1)
        lesson = results[0]["record"]["lesson"]
        self.assertTrue(lesson)

    def test_best_lesson(self):
        """最佳教训"""
        self.mgr.store_from_event(success=False, trigger="拾取失败")
        from backend.embodied.companion.experience import ExperienceQuery
        from backend.embodied.companion.experience import ExperienceStore
        query = ExperienceQuery(self.mgr._store)
        lesson = query.best_lesson("拾取")
        self.assertTrue(lesson)

    def test_relevant_score_ranking(self):
        """相关度排序"""
        self.mgr.store_from_event(success=False, trigger="拾取失败",
                                  result="position_mismatch")
        self.mgr.store_engineering_experience(
            trigger="开发", lesson="无关经验",
        )
        results = self.mgr.relevant(trigger="拾取")
        if len(results) > 1:
            scores = [r["score"] for r in results]
            self.assertEqual(scores, sorted(scores, reverse=True))

    def test_decision_experience(self):
        """决策经验"""
        from backend.embodied.companion.experience import (
            ExperienceExtractor,
        )
        ex = ExperienceExtractor()
        rec = ex.extract_from_decision(
            trigger="选策略", decision="用A方案", outcome="成功",
            success=True,
        )
        self.assertEqual(rec.type, "decision")
        self.assertIn("可复用", rec.lesson)

    def test_decision_failure(self):
        """决策失败经验"""
        from backend.embodied.companion.experience import (
            ExperienceExtractor,
        )
        ex = ExperienceExtractor()
        rec = ex.extract_from_decision(
            trigger="选策略", decision="用B方案", outcome="失败",
            success=False,
        )
        self.assertIn("需调整", rec.lesson)

    def test_relationship_observation_experience(self):
        """关系观察经验"""
        d = self.mgr.store_relationship_experience(
            trust_level=0.3, interaction_count=5,
        )
        self.assertEqual(d["type"], "interaction")
        self.assertIn("提升", d["lesson"])

    def test_extract_engineering_confidence(self):
        """工程经验置信度"""
        from backend.embodied.companion.experience import (
            ExperienceExtractor,
        )
        rec = ExperienceExtractor().extract_engineering(
            trigger="t", lesson="l", confidence=0.95,
        )
        self.assertEqual(rec.confidence, 0.95)

    def test_extract_source_field(self):
        """抽取来源字段"""
        d = self.mgr.store_from_event(
            success=True, trigger="扫描", source="run_goal",
        )
        self.assertEqual(d["source"], "run_goal")


class TestQueryMore(unittest.TestCase):
    """查询更多场景"""

    def setUp(self):
        self.mgr = ExperienceManager()
        self.mgr.store_from_event(success=False, trigger="拾取失败",
                                  action="pick", result="位置不对")
        self.mgr.store_engineering_experience(
            trigger="开发", lesson="先设计",
        )

    def test_by_keyword(self):
        """关键词查询"""
        from backend.embodied.companion.experience import (
            ExperienceQuery,
        )
        q = ExperienceQuery(self.mgr._store)
        results = q.by_keyword("拾取")
        self.assertGreaterEqual(len(results), 1)

    def test_by_value(self):
        """价值查询"""
        from backend.embodied.companion.experience import (
            ExperienceQuery,
        )
        q = ExperienceQuery(self.mgr._store)
        results = q.by_value(min_value=0.7)
        self.assertGreaterEqual(len(results), 1)

    def test_by_value_invalid(self):
        """价值范围校验"""
        from backend.embodied.companion.experience import (
            ExperienceQuery,
            ExperienceQueryError,
        )
        q = ExperienceQuery(self.mgr._store)
        with self.assertRaises(ExperienceQueryError):
            q.by_value(min_value=1.5)

    def test_recent(self):
        """近期经验"""
        from backend.embodied.companion.experience import (
            ExperienceQuery,
        )
        q = ExperienceQuery(self.mgr._store)
        results = q.recent(limit=1)
        self.assertEqual(len(results), 1)

    def test_best_lesson_empty(self):
        """无相关 → 空教训"""
        from backend.embodied.companion.experience import (
            ExperienceQuery,
        )
        q = ExperienceQuery(self.mgr._store)
        self.assertEqual(q.best_lesson("zzz"), "")


class TestReflectionMore(unittest.TestCase):
    """反思更多场景"""

    def setUp(self):
        self.mgr = ExperienceManager()

    def test_reflection_type_distribution(self):
        """反思含类型分布"""
        self.mgr.store_from_event(success=True, trigger="扫描")
        self.mgr.store_engineering_experience(
            trigger="开发", lesson="l",
        )
        r = self.mgr.reflection_report()
        self.assertIn("类型分布", r["findings"][0])

    def test_reflection_low_value_finding(self):
        """反思含低价值统计"""
        r = self.mgr.reflection_report()
        self.assertTrue(any("低价值" in f for f in r["findings"]))


if __name__ == "__main__":
    unittest.main()
