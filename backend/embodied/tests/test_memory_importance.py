"""
YHLZ Embodied AI V6.0 - 记忆价值评分单元测试 (Memory Importance)

覆盖 (memory/memory_importance.py):
    - Importance = Identity Impact + Relationship Impact
                   + Creative Impact + Repeat Value
    - 高价值记忆禁止自动删除 (保护规则)
    - 可解释: 每维 reason / 分级
"""
import unittest

from backend.embodied.companion.memory import (
    CREATIVE_KEYWORDS,
    IDENTITY_KEYWORDS,
    ImportanceError,
    MemoryImportance,
    RELATIONSHIP_KEYWORDS,
)


def make_record(rid="exp_1", trigger="生成工程Prompt",
                lesson="经验教训", source="companion_handle",
                rtype="interaction", value=0.6):
    return {
        "id": rid, "trigger": trigger, "lesson": lesson,
        "source": source, "type": rtype, "value": value,
        "timestamp": 1000.0,
    }


class TestImportanceInit(unittest.TestCase):
    """初始化"""

    def test_default_init(self):
        m = MemoryImportance()
        self.assertIsNotNone(m)

    def test_threshold_validation_high(self):
        with self.assertRaises(ImportanceError):
            MemoryImportance(high_threshold=2.5)

    def test_threshold_validation_low(self):
        with self.assertRaises(ImportanceError):
            MemoryImportance(high_threshold=-0.1)

    def test_keyword_tables(self):
        self.assertTrue(IDENTITY_KEYWORDS)
        self.assertTrue(RELATIONSHIP_KEYWORDS)
        self.assertTrue(CREATIVE_KEYWORDS)


class TestScoreStructure(unittest.TestCase):
    """评分结构"""

    def setUp(self):
        self.scorer = MemoryImportance()

    def test_score_structure(self):
        r = self.scorer.score(make_record())
        for key in ("record_id", "importance_score", "dimensions",
                    "protected", "level", "reason"):
            self.assertIn(key, r)

    def test_score_missing_id(self):
        with self.assertRaises(ImportanceError):
            self.scorer.score({"trigger": "no id"})

    def test_score_range(self):
        r = self.scorer.score(make_record())
        self.assertGreaterEqual(r["importance_score"], 0.0)
        self.assertLessEqual(r["importance_score"], 2.0)

    def test_four_dimensions(self):
        r = self.scorer.score(make_record())
        names = {d["name"] for d in r["dimensions"]}
        self.assertEqual(names, {"identity_impact",
                                 "relationship_impact",
                                 "creative_impact", "repeat_value"})

    def test_dimension_reasons(self):
        r = self.scorer.score(make_record())
        for d in r["dimensions"]:
            self.assertTrue(d["reason"])

    def test_level_valid(self):
        r = self.scorer.score(make_record())
        self.assertIn(r["level"], ("high", "medium", "low"))

    def test_record_id_match(self):
        r = self.scorer.score(make_record(rid="exp_x"))
        self.assertEqual(r["record_id"], "exp_x")


class TestDimensionScoring(unittest.TestCase):
    """维度评分"""

    def setUp(self):
        self.scorer = MemoryImportance()

    def test_identity_keyword_boost(self):
        r1 = self.scorer.score(make_record(rid="a", lesson="普通经验"))
        r2 = self.scorer.score(make_record(
            rid="b", lesson="身份核心价值观相关",
        ))
        d1 = next(d for d in r1["dimensions"]
                  if d["name"] == "identity_impact")
        d2 = next(d for d in r2["dimensions"]
                  if d["name"] == "identity_impact")
        self.assertGreater(d2["score"], d1["score"])

    def test_confirmed_identity_boost(self):
        r = self.scorer.score(make_record(), {
            "verification_status": "CONFIRMED",
        })
        d = next(x for x in r["dimensions"]
                 if x["name"] == "identity_impact")
        self.assertGreater(d["score"], 0.0)

    def test_relationship_keyword_boost(self):
        r = self.scorer.score(make_record(rid="a",
                                          trigger="用户偏好功能"))
        d = next(x for x in r["dimensions"]
                 if x["name"] == "relationship_impact")
        self.assertGreater(d["score"], 0.0)

    def test_creative_reference_boost(self):
        r = self.scorer.score(make_record(rid="a"), {
            "referenced_by_creative": True,
        })
        d = next(x for x in r["dimensions"]
                 if x["name"] == "creative_impact")
        self.assertGreater(d["score"], 0.0)

    def test_creative_execution_source_boost(self):
        r = self.scorer.score(make_record(rid="a",
                                          source="creative_execution"))
        d = next(x for x in r["dimensions"]
                 if x["name"] == "creative_impact")
        self.assertGreater(d["score"], 0.0)

    def test_repeat_value_grows(self):
        r1 = self.scorer.score(make_record(rid="a"), {
            "occurrence_count": 1,
        })
        r2 = self.scorer.score(make_record(rid="b"), {
            "occurrence_count": 5,
        })
        d1 = next(x for x in r1["dimensions"]
                  if x["name"] == "repeat_value")
        d2 = next(x for x in r2["dimensions"]
                  if x["name"] == "repeat_value")
        self.assertGreater(d2["score"], d1["score"])

    def test_repeat_value_cap(self):
        r = self.scorer.score(make_record(rid="a"), {
            "occurrence_count": 100,
        })
        d = next(x for x in r["dimensions"]
                 if x["name"] == "repeat_value")
        self.assertLessEqual(d["score"], 0.5)


class TestProtection(unittest.TestCase):
    """保护规则"""

    def test_low_score_not_protected(self):
        s = MemoryImportance()
        r = s.score(make_record(rid="a"))
        self.assertFalse(r["protected"])

    def test_high_score_protected(self):
        s = MemoryImportance(high_threshold=0.3)
        r = s.score(make_record(rid="a", source="creative_execution",
                                trigger="用户偏好身份"))
        self.assertTrue(r["protected"])

    def test_should_protect(self):
        s = MemoryImportance(high_threshold=0.3)
        s.score(make_record(rid="a", lesson="身份核心价值"))
        self.assertTrue(s.should_protect("a"))

    def test_should_protect_false(self):
        s = MemoryImportance()
        s.score(make_record(rid="a"))
        self.assertFalse(s.should_protect("a"))

    def test_should_protect_unknown(self):
        s = MemoryImportance()
        self.assertFalse(s.should_protect("unknown_id"))

    def test_protected_ids(self):
        s = MemoryImportance(high_threshold=0.2)
        s.score(make_record(rid="a", lesson="身份核心"))
        s.score(make_record(rid="b"))
        self.assertIn("a", s.protected_ids())
        self.assertNotIn("b", s.protected_ids())

    def test_protected_reason_text(self):
        s = MemoryImportance(high_threshold=0.2)
        r = s.score(make_record(rid="a", lesson="身份核心"))
        self.assertIn("禁止自动删除", r["reason"])


class TestQueryAndStats(unittest.TestCase):
    """查询与统计"""

    def setUp(self):
        self.scorer = MemoryImportance()

    def test_get_score(self):
        self.scorer.score(make_record(rid="a"))
        r = self.scorer.get_score("a")
        self.assertEqual(r["record_id"], "a")

    def test_get_score_missing(self):
        self.assertIsNone(self.scorer.get_score("nope"))

    def test_stats_structure(self):
        self.scorer.score(make_record(rid="a"))
        st = self.scorer.stats()
        for key in ("mode", "scored_count", "protected_count",
                    "by_level", "avg_importance", "high_threshold"):
            self.assertIn(key, st)

    def test_stats_counts(self):
        s = MemoryImportance(high_threshold=0.2)
        s.score(make_record(rid="a", lesson="身份核心"))
        s.score(make_record(rid="b"))
        st = s.stats()
        self.assertEqual(st["scored_count"], 2)
        self.assertGreaterEqual(st["protected_count"], 1)

    def test_avg_importance(self):
        self.scorer.score(make_record(rid="a"))
        self.scorer.score(make_record(rid="b"))
        st = self.scorer.stats()
        self.assertGreaterEqual(st["avg_importance"], 0.0)

    def test_clear(self):
        self.scorer.score(make_record(rid="a"))
        self.assertEqual(self.scorer.clear(), 1)
        self.assertEqual(self.scorer.stats()["scored_count"], 0)

    def test_clear_empty(self):
        self.assertEqual(self.scorer.clear(), 0)


class TestEdgeCases(unittest.TestCase):
    """边界"""

    def test_score_does_not_mutate(self):
        s = MemoryImportance()
        rec = make_record(rid="a")
        before = dict(rec)
        s.score(rec, {"occurrence_count": 3})
        self.assertEqual(rec, before)

    def test_no_context(self):
        s = MemoryImportance()
        r = s.score(make_record(rid="a"), None)
        self.assertGreaterEqual(r["importance_score"], 0.0)

    def test_empty_occurrence_default_one(self):
        s = MemoryImportance()
        r = s.score(make_record(rid="a"), {"occurrence_count": 0})
        self.assertGreaterEqual(r["importance_score"], 0.0)

    def test_unicode_keywords(self):
        s = MemoryImportance()
        r = s.score(make_record(rid="a", trigger="信任与偏好"))
        d = next(x for x in r["dimensions"]
                 if x["name"] == "relationship_impact")
        self.assertGreater(d["score"], 0.0)


if __name__ == "__main__":
    unittest.main()
