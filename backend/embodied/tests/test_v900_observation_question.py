"""
YHLZ Embodied AI V9.0 - 观察与问题发现单元测试 (Observation & Question)

覆盖:
    - ObservationLayer: 观察采集/类型/统计
    - QuestionDiscoveryEngine: 问题发现/importance
"""
import unittest

from backend.embodied.companion.research_engine import (
    IMPORTANCE_WEIGHTS,
    ObservationLayer,
    QuestionDiscoveryEngine,
)
from backend.embodied.companion.research_engine.observation import (
    OBSERVATION_TYPES,
    ObservationError,
)


class TestObservationLayer(unittest.TestCase):
    """观察层"""

    def setUp(self):
        self.layer = ObservationLayer()

    def test_observe_structure(self):
        obs = self.layer.observe("user_need", "提升体验",
                                 "user")
        for key in ("observation_id", "type", "content",
                    "source", "timestamp"):
            self.assertIn(key, obs)
        self.assertTrue(obs["observation_id"].startswith(
            "ob_"))

    def test_observe_all_types(self):
        for t in OBSERVATION_TYPES:
            obs = self.layer.observe(t, f"内容_{t}")
            self.assertEqual(obs["type"], t)

    def test_invalid_type(self):
        with self.assertRaises(ObservationError):
            self.layer.observe("bogus", "x")

    def test_from_knowledge_gaps(self):
        n = self.layer.from_knowledge_gaps(
            ["缺口A", "缺口B", ""],
        )
        self.assertEqual(n, 2)

    def test_observations_filter(self):
        self.layer.observe("user_need", "a")
        self.layer.observe("knowledge_gap", "b")
        needs = self.layer.observations("user_need")
        self.assertEqual(len(needs), 1)
        self.assertEqual(needs[0]["type"], "user_need")

    def test_observations_order(self):
        self.layer.observe("user_need", "旧")
        self.layer.observe("user_need", "新")
        items = self.layer.observations("user_need")
        self.assertEqual(items[0]["content"], "新")

    def test_stats(self):
        self.layer.observe("user_need", "a")
        self.layer.observe("knowledge_gap", "b")
        stats = self.layer.stats()
        self.assertEqual(stats["observation_count"], 2)
        self.assertEqual(stats["by_type"]["user_need"], 1)

    def test_disabled(self):
        layer = ObservationLayer(enabled=False)
        obs = layer.observe("user_need", "x")
        self.assertFalse(obs["ok"])
        self.assertIn("停用", obs["reason"])

    def test_clear(self):
        self.layer.observe("user_need", "a")
        n = self.layer.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.layer.stats()[
            "observation_count"], 0)

    def test_types_constant(self):
        self.assertEqual(OBSERVATION_TYPES,
                         ["knowledge_gap", "user_need",
                          "long_term_goal", "unresolved"])


class TestQuestionDiscovery(unittest.TestCase):
    """问题发现"""

    def setUp(self):
        self.layer = ObservationLayer()
        self.engine = QuestionDiscoveryEngine(layer=self.layer)

    def test_discover_questions(self):
        self.layer.observe("user_need", "提升伙伴体验")
        questions = self.engine.discover()
        self.assertGreaterEqual(len(questions), 1)

    def test_question_structure(self):
        self.layer.observe("knowledge_gap", "记忆保持")
        q = self.engine.discover()[0]
        for key in ("question_id", "question", "importance",
                    "reason", "expected_value"):
            self.assertIn(key, q)
        self.assertTrue(q["question_id"].startswith("qs_"))

    def test_question_format(self):
        self.layer.observe("user_need", "提升体验")
        q = self.engine.discover()[0]
        self.assertIn("如何解决", q["question"])

    def test_importance_user_need_highest(self):
        self.layer.observe("user_need", "需求")
        self.layer.observe("knowledge_gap", "缺口")
        questions = self.engine.discover()
        user_q = next(
            q for q in questions
            if "需求" in q["question"]
        )
        gap_q = next(
            q for q in questions
            if "缺口" in q["question"]
        )
        self.assertGreater(user_q["importance"],
                           gap_q["importance"])

    def test_importance_values(self):
        self.assertEqual(IMPORTANCE_WEIGHTS["user_need"], 0.9)
        self.assertEqual(
            IMPORTANCE_WEIGHTS["long_term_goal"], 0.8)
        self.assertEqual(
            IMPORTANCE_WEIGHTS["unresolved"], 0.7)
        self.assertEqual(
            IMPORTANCE_WEIGHTS["knowledge_gap"], 0.6)

    def test_expected_value(self):
        self.layer.observe("user_need", "a")
        q = self.engine.discover()[0]
        self.assertIn("用户体验", q["expected_value"])

    def test_reason_explainable(self):
        self.layer.observe("knowledge_gap", "缺口")
        q = self.engine.discover()[0]
        self.assertIn("知识缺口", q["reason"])

    def test_sorted_by_importance(self):
        self.layer.observe("knowledge_gap", "低")
        self.layer.observe("user_need", "高")
        questions = self.engine.discover()
        self.assertGreaterEqual(
            questions[0]["importance"],
            questions[-1]["importance"])

    def test_no_observation_no_questions(self):
        self.assertEqual(self.engine.discover(), [])

    def test_max_questions(self):
        engine = QuestionDiscoveryEngine(
            layer=self.layer, max_questions=2,
        )
        for i in range(5):
            self.layer.observe("knowledge_gap", f"缺口{i}")
        self.assertLessEqual(len(engine.discover()), 2)

    def test_stats(self):
        self.layer.observe("user_need", "a")
        self.engine.discover()
        stats = self.engine.stats()
        self.assertGreaterEqual(stats["question_count"], 1)
        self.assertEqual(stats["observation_count"], 1)
        self.assertIn("weights", stats)

    def test_disabled(self):
        engine = QuestionDiscoveryEngine(enabled=False)
        self.layer.observe("user_need", "a")
        self.assertEqual(engine.discover(), [])

    def test_clear(self):
        self.layer.observe("user_need", "a")
        self.engine.discover()
        n = self.engine.clear()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(self.engine.stats()[
            "question_count"], 0)


if __name__ == "__main__":
    unittest.main()
