"""
YHLZ Embodied AI V4.4 - 策略候选排序器单元测试 (Policy Ranker)

覆盖:
    - 打分: hit_rate / acceptance_rate / recency 加权
    - 排序: 得分降序 / 同分按更新时间 / trigger 字典序 (确定性)
    - 可解释: reason 输出公式
    - select_best: 最佳策略 + 理由
    - 边界: 权重校验 / 半衰期校验 / 空候选
"""
import unittest

from backend.embodied.experience.policy import ExperiencePolicy
from backend.embodied.strategy.ranker import PolicyRanker, PolicyRankerError


def make_policy(trigger, hit_rate=None, acceptance_rate=None, updated_at=1000.0,
                version=1):
    p = ExperiencePolicy.create(trigger=trigger, strategy=f"s_{trigger}", version=version)
    p.updated_at = updated_at
    p.suggest_count = 100
    if acceptance_rate is None:
        p.accepted_count = 100
    else:
        p.accepted_count = int(100 * acceptance_rate)
    if hit_rate is None:
        p.success_count = p.accepted_count
    else:
        p.success_count = int(p.accepted_count * hit_rate)
    return p


class TestRankerScore(unittest.TestCase):

    def test_score_weights(self):
        r = PolicyRanker(hit_rate_weight=0.5, acceptance_weight=0.3, recency_weight=0.2)
        p = make_policy("t", hit_rate=0.8, acceptance_rate=0.6)
        p.updated_at = 1000.0
        # recency: 1 - (now-1000)/86400/30 ≈ 1 (now 接近)
        now = 1000.0
        score = r.score(p, now)
        self.assertAlmostEqual(score, 0.5 * 0.8 + 0.3 * 0.6 + 0.2 * 1.0, places=4)

    def test_score_no_data(self):
        r = PolicyRanker()
        p = ExperiencePolicy.create(trigger="t", strategy="s")
        p.updated_at = 0.0  # 无任何统计且无更新 → 分数 0
        self.assertEqual(r.score(p), 0.0)

    def test_recency_score_recent(self):
        r = PolicyRanker(recency_half_life_days=30.0)
        self.assertGreater(r.recency_score(1000.0, now=1000.0), 0.9)

    def test_recency_score_old(self):
        r = PolicyRanker(recency_half_life_days=30.0)
        self.assertEqual(r.recency_score(1000.0, now=1000.0 + 40 * 86400), 0.0)

    def test_recency_score_zero(self):
        r = PolicyRanker()
        self.assertEqual(r.recency_score(0.0), 0.0)

    def test_explain_contains_formula(self):
        r = PolicyRanker()
        p = make_policy("t", hit_rate=0.8, acceptance_rate=0.6)
        reason = r.explain(p, now=1000.0)
        self.assertIn("score=", reason)
        self.assertIn("hit_rate(0.80)", reason)
        self.assertIn("acceptance_rate(0.60)", reason)
        self.assertIn("recency(", reason)


class TestRankerSort(unittest.TestCase):

    def test_rank_sorted_by_score(self):
        r = PolicyRanker()
        p1 = make_policy("high", hit_rate=0.9, acceptance_rate=0.9)
        p2 = make_policy("low", hit_rate=0.1, acceptance_rate=0.1)
        ranked = r.rank([p2, p1], now=1000.0)
        self.assertEqual(ranked[0]["trigger"], "high")
        self.assertEqual(ranked[1]["trigger"], "low")
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertEqual(ranked[1]["rank"], 2)

    def test_rank_contains_reason(self):
        r = PolicyRanker()
        ranked = r.rank([make_policy("t", hit_rate=0.8)], now=1000.0)
        self.assertIn("reason", ranked[0])
        self.assertIn("score", ranked[0])

    def test_tie_break_by_updated_at(self):
        r = PolicyRanker()
        p_old = make_policy("old", hit_rate=0.5, acceptance_rate=0.5, updated_at=100.0)
        p_new = make_policy("new", hit_rate=0.5, acceptance_rate=0.5, updated_at=200.0)
        ranked = r.rank([p_old, p_new], now=1000.0)
        self.assertEqual(ranked[0]["trigger"], "new")

    def test_tie_break_by_trigger_lexical(self):
        r = PolicyRanker()
        p_a = make_policy("alpha", updated_at=100.0)
        p_b = make_policy("beta", updated_at=100.0)
        ranked = r.rank([p_b, p_a], now=1000.0)
        self.assertEqual(ranked[0]["trigger"], "alpha")

    def test_rank_deterministic(self):
        r = PolicyRanker()
        cands = [make_policy(f"t{i}", hit_rate=i / 10, acceptance_rate=i / 10)
                 for i in range(5)]
        a = [x["trigger"] for x in r.rank(cands, now=1000.0)]
        b = [x["trigger"] for x in r.rank(cands, now=1000.0)]
        self.assertEqual(a, b)

    def test_rank_empty(self):
        self.assertEqual(PolicyRanker().rank([]), [])

    def test_rank_fields(self):
        r = PolicyRanker()
        p = make_policy("t", hit_rate=0.5, acceptance_rate=0.5, version=3)
        item = r.rank([p], now=1000.0)[0]
        self.assertEqual(item["version"], 3)
        self.assertEqual(item["kind"], "failure")
        self.assertEqual(item["status"], "active")


class TestRankerBest(unittest.TestCase):

    def test_select_best(self):
        r = PolicyRanker()
        p1 = make_policy("best", hit_rate=0.9)
        p2 = make_policy("worst", hit_rate=0.1)
        best = r.select_best([p2, p1], now=1000.0)
        self.assertIsNotNone(best)
        self.assertEqual(best["best"]["trigger"], "best")
        self.assertIn("候选", best["reason"])
        self.assertIn("best", best["reason"])

    def test_select_best_none_for_empty(self):
        self.assertIsNone(PolicyRanker().select_best([]))

    def test_weights_validation(self):
        with self.assertRaises(PolicyRankerError):
            PolicyRanker(hit_rate_weight=-1)
        with self.assertRaises(PolicyRankerError):
            PolicyRanker(hit_rate_weight=0, acceptance_weight=0, recency_weight=0)
        with self.assertRaises(PolicyRankerError):
            PolicyRanker(recency_half_life_days=0)

    def test_weights_report(self):
        r = PolicyRanker(hit_rate_weight=0.6, acceptance_weight=0.3, recency_weight=0.1)
        w = r.weights()
        self.assertEqual(w["hit_rate_weight"], 0.6)
        self.assertEqual(w["acceptance_weight"], 0.3)
        self.assertEqual(w["recency_weight"], 0.1)


if __name__ == "__main__":
    unittest.main()
