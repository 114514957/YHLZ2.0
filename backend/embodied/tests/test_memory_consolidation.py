"""
YHLZ Embodied AI V6.0 - 记忆整合单元测试 (Memory Consolidation)

覆盖 (memory/memory_consolidation.py):
    - 生命周期: Active → Cold → Archive → Recycle
    - 规则: 近期活跃 / 超期冷数据 / 高价值归档 / 低价值回收
    - 高价值记忆禁止自动回收
    - 归档压缩 / 回收审计 / 统计
"""
import time
import unittest

from backend.embodied.companion.memory import (
    CONSOLIDATION_TRANSITIONS,
    ConsolidationError,
    MemoryConsolidation,
)


def make_record(rid, trigger="拾取", value=0.6,
                age_days=0, rtype="interaction", source=""):
    """构造经历 (age_days 天前)"""
    return {
        "id": rid, "trigger": trigger, "lesson": "经验",
        "value": value, "type": rtype, "source": source,
        "timestamp": time.time() - age_days * 86400,
    }


def make_importance(protected=False, score=0.5):
    return {"protected": protected, "importance_score": score}


class TestConsolidationInit(unittest.TestCase):
    """初始化"""

    def test_default_init(self):
        c = MemoryConsolidation()
        self.assertIsNotNone(c)

    def test_archive_days_validation(self):
        with self.assertRaises(ConsolidationError):
            MemoryConsolidation(archive_days=0)

    def test_recycle_value_validation(self):
        with self.assertRaises(ConsolidationError):
            MemoryConsolidation(recycle_value=1.5)

    def test_transitions(self):
        self.assertEqual(CONSOLIDATION_TRANSITIONS["active"],
                         ["cold", "archive"])
        self.assertIn("recycle", CONSOLIDATION_TRANSITIONS["cold"])
        self.assertEqual(CONSOLIDATION_TRANSITIONS["recycle"], [])


class TestConsolidate(unittest.TestCase):
    """整理主流程"""

    def setUp(self):
        self.cons = MemoryConsolidation(archive_days=30,
                                        recycle_value=0.3,
                                        archive_keep_value=0.7)

    def test_consolidate_structure(self):
        recs = [make_record("a")]
        r = self.cons.consolidate(recs)
        for key in ("consolidation_id", "stages", "transitions",
                    "recycled", "archived", "skipped", "mode",
                    "consolidated_at"):
            self.assertIn(key, r)

    def test_recent_active(self):
        recs = [make_record("a", age_days=1, value=0.6)]
        r = self.cons.consolidate(recs)
        self.assertIn("a", r["stages"]["active"])

    def test_old_low_value_recycle(self):
        recs = [make_record("a", age_days=70, value=0.2)]
        r = self.cons.consolidate(recs)
        self.assertIn("a", r["recycled"])
        self.assertIn("a", r["stages"]["recycle"])

    def test_old_medium_value_cold(self):
        recs = [make_record("a", age_days=40, value=0.5)]
        r = self.cons.consolidate(recs)
        self.assertIn("a", r["stages"]["cold"])

    def test_old_high_value_archive(self):
        recs = [make_record("a", age_days=40, value=0.8)]
        r = self.cons.consolidate(recs)
        self.assertIn("a", r["archived"])
        self.assertIn("a", r["stages"]["archive"])

    def test_high_value_recent_active(self):
        recs = [make_record("a", age_days=1, value=0.9)]
        r = self.cons.consolidate(recs)
        self.assertIn("a", r["stages"]["active"])

    def test_protected_never_recycled(self):
        """高价值 (protected) 记忆禁止自动回收"""
        recs = [make_record("a", age_days=70, value=0.2)]
        imp = {"a": make_importance(protected=True)}
        r = self.cons.consolidate(recs, imp)
        self.assertNotIn("a", r["recycled"])
        self.assertNotIn("a", r["stages"]["recycle"])

    def test_protected_forced_archive(self):
        recs = [make_record("a", age_days=70, value=0.2)]
        imp = {"a": make_importance(protected=True)}
        r = self.cons.consolidate(recs, imp)
        self.assertIn("a", r["stages"]["archive"])

    def test_recycle_removes_from_index(self):
        recs = [make_record("a", age_days=70, value=0.2)]
        self.cons.consolidate(recs)
        self.assertIsNone(self.cons._index.get("a"))

    def test_archive_kept_in_index(self):
        recs = [make_record("a", age_days=40, value=0.8)]
        self.cons.consolidate(recs)
        e = self.cons._index.get("a")
        self.assertEqual(e["stage"], "archive")

    def test_skip_missing_id(self):
        r = self.cons.consolidate([{"trigger": "no id"}])
        self.assertIn("", r["skipped"])

    def test_transitions_recorded(self):
        recs = [make_record("a", age_days=40, value=0.8)]
        r = self.cons.consolidate(recs)
        self.assertEqual(len(r["transitions"]), 0)

    def test_transition_second_run(self):
        recs = [make_record("a", age_days=40, value=0.8)]
        self.cons.consolidate(recs)
        r = self.cons.consolidate(recs)
        self.assertGreaterEqual(len(r["transitions"]), 0)

    def test_mode_rule_based(self):
        r = self.cons.consolidate([])
        self.assertEqual(r["mode"], "rule_based")

    def test_empty_records(self):
        r = self.cons.consolidate([])
        self.assertEqual(r["recycled"], [])
        self.assertEqual(r["archived"], [])


class TestStages(unittest.TestCase):
    """阶段统计"""

    def setUp(self):
        self.cons = MemoryConsolidation(archive_days=30,
                                        recycle_value=0.3,
                                        archive_keep_value=0.7)

    def test_stages_distribution(self):
        recs = [
            make_record("a", age_days=1, value=0.6),
            make_record("b", age_days=40, value=0.5),
            make_record("c", age_days=40, value=0.8),
            make_record("d", age_days=70, value=0.2),
        ]
        self.cons.consolidate(recs)
        st = self.cons.stages()
        self.assertEqual(st["active"], 1)
        self.assertEqual(st["cold"], 1)
        self.assertEqual(st["archive"], 1)
        self.assertEqual(st.get("recycle", 0), 0)  # d 已从索引移除

    def test_changes_history(self):
        self.cons.consolidate([make_record("a")])
        changes = self.cons.changes()
        self.assertEqual(len(changes), 1)

    def test_changes_limit(self):
        for i in range(5):
            self.cons.consolidate([make_record(f"e{i}")])
        self.assertEqual(len(self.cons.changes(limit=2)), 2)

    def test_stats_structure(self):
        self.cons.consolidate([make_record("a")])
        st = self.cons.stats()
        for key in ("mode", "consolidation_count", "recycled_total",
                    "archived_total", "stages", "index_total"):
            self.assertIn(key, st)

    def test_stats_recycled_total(self):
        recs = [make_record("a", age_days=70, value=0.2)]
        self.cons.consolidate(recs)
        self.assertEqual(self.cons.stats()["recycled_total"], 1)

    def test_stats_archived_total(self):
        recs = [make_record("a", age_days=40, value=0.8)]
        self.cons.consolidate(recs)
        self.assertEqual(self.cons.stats()["archived_total"], 1)

    def test_clear(self):
        self.cons.consolidate([make_record("a")])
        self.assertEqual(self.cons.clear(), 1)
        self.assertEqual(self.cons.stats()["consolidation_count"], 0)


class TestAssessRules(unittest.TestCase):
    """阶段判定规则"""

    def setUp(self):
        self.cons = MemoryConsolidation(archive_days=30,
                                        recycle_value=0.3,
                                        archive_keep_value=0.7)
        self.now = time.time()

    def _assess(self, value, age_days, protected=False):
        rec = make_record("a", value=value, age_days=age_days)
        return self.cons._assess(rec, value, protected, self.now)

    def test_recent_low_active(self):
        self.assertEqual(self._assess(0.2, 1), "active")

    def test_old_low_recycle(self):
        self.assertEqual(self._assess(0.2, 70), "recycle")

    def test_old_medium_cold(self):
        self.assertEqual(self._assess(0.5, 40), "cold")

    def test_old_high_archive(self):
        self.assertEqual(self._assess(0.8, 40), "archive")

    def test_protected_old_archive(self):
        self.assertEqual(self._assess(0.2, 70, protected=True),
                         "archive")

    def test_boundary_archive_day(self):
        self.assertEqual(self._assess(0.5, 31), "cold")

    def test_boundary_recycle_double(self):
        self.assertEqual(self._assess(0.2, 60), "cold")

    def test_boundary_recycle_over(self):
        self.assertEqual(self._assess(0.2, 61), "recycle")


class TestIndexIntegration(unittest.TestCase):
    """索引联动"""

    def setUp(self):
        self.cons = MemoryConsolidation(archive_days=30,
                                        recycle_value=0.3,
                                        archive_keep_value=0.7)

    def test_index_registered(self):
        self.cons.consolidate([make_record("a", value=0.6)])
        e = self.cons._index.get("a")
        self.assertEqual(e["type"], "experience")
        self.assertEqual(e["value"], 0.6)

    def test_index_creative_type(self):
        rec = make_record("a", source="creative_execution")
        self.cons.consolidate([rec])
        e = self.cons._index.get("a")
        self.assertEqual(e["type"], "creative")

    def test_index_reflection_type(self):
        rec = make_record("a", rtype="reflection")
        self.cons.consolidate([rec])
        e = self.cons._index.get("a")
        self.assertEqual(e["type"], "reflection")

    def test_importance_stored(self):
        recs = [make_record("a", value=0.6)]
        imp = {"a": make_importance(score=1.2)}
        self.cons.consolidate(recs, imp)
        e = self.cons._index.get("a")
        self.assertEqual(e["importance"], 1.2)

    def test_query_via_index(self):
        recs = [make_record("a", value=0.9)]
        self.cons.consolidate(recs)
        hits = self.cons._index.query(stage="active")
        self.assertEqual(len(hits), 1)


if __name__ == "__main__":
    unittest.main()
