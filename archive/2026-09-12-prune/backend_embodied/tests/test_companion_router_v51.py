"""
YHLZ Embodied AI V5.1 - 路由加权打分单元测试 (Weighted Routing)

覆盖 (router.py V5.1):
    - 关键词权重打分: KEYWORD_WEIGHTS (复合 3.0 / 核心 2.0 / 默认 1.0)
    - detect_capabilities: 得分计算 / 多关键词累加 / 得分排序
    - Top-K 路由: 按得分取前 N 能力域 (可配置)
    - RouteResult 增强: scores / weighted_keywords (可解释打分)
    - 参数校验: top_k <= 0 → RouterError
    - 回退: 无命中 → 默认 (带分数标记)
"""
import unittest

from backend.embodied.companion import (
    DEFAULT_KEYWORD_WEIGHT,
    DEFAULT_ROUTE_TOP_K,
    CompanionRouter,
    KEYWORD_WEIGHTS,
    RouterError,
    SpecialistRegistry,
)


def ok_handler(request):
    return {"ok": True}


def make_router(top_k=3):
    reg = SpecialistRegistry()
    for cap in ("perception", "reasoning", "experience", "planning",
                "long_horizon", "governance"):
        reg.register_simple(f"{cap}_agent", cap, ok_handler)
    return CompanionRouter(reg, top_k=top_k)


class TestKeywordWeights(unittest.TestCase):
    """关键词权重表"""

    def test_composite_weight(self):
        """复合词权重 = 3.0"""
        self.assertEqual(KEYWORD_WEIGHTS["长期目标"], 3.0)
        self.assertEqual(KEYWORD_WEIGHTS["为什么失败"], 3.0)
        self.assertEqual(KEYWORD_WEIGHTS["多目标"], 3.0)

    def test_core_weight(self):
        """核心词权重 = 2.0"""
        self.assertEqual(KEYWORD_WEIGHTS["扫描"], 2.0)
        self.assertEqual(KEYWORD_WEIGHTS["规划"], 2.0)
        self.assertEqual(KEYWORD_WEIGHTS["整理"], 2.0)
        self.assertEqual(KEYWORD_WEIGHTS["治理"], 2.0)

    def test_default_weight(self):
        """默认权重 = 1.0"""
        self.assertEqual(DEFAULT_KEYWORD_WEIGHT, 1.0)

    def test_default_topk(self):
        """默认 Top-K = 3"""
        self.assertEqual(DEFAULT_ROUTE_TOP_K, 3)


class TestDetectScored(unittest.TestCase):
    """加权打分检测"""

    def setUp(self):
        self.router = make_router()

    def test_score_sum(self):
        """多关键词得分累加"""
        hits = self.router.detect_capabilities("扫描环境")
        perception = next(h for h in hits
                          if h["capability"] == "perception")
        # 扫描(2.0) + 环境(1.0) = 3.0
        self.assertEqual(perception["score"], 3.0)

    def test_score_core_word(self):
        """核心词得分"""
        hits = self.router.detect_capabilities("做个规划")
        planning = next(h for h in hits
                        if h["capability"] == "planning")
        self.assertEqual(planning["score"], 2.0)

    def test_score_composite(self):
        """复合词得分更高"""
        hits = self.router.detect_capabilities("制定长期目标")
        lh = next(h for h in hits
                  if h["capability"] == "long_horizon")
        # 长期目标(3.0) + 长期(1.0) = 4.0
        self.assertGreaterEqual(lh["score"], 3.0)

    def test_keywords_listed(self):
        """命中关键词明细 (含权重)"""
        hits = self.router.detect_capabilities("扫描环境")
        perception = next(h for h in hits
                          if h["capability"] == "perception")
        kws = {k["keyword"] for k in perception["keywords"]}
        self.assertIn("扫描", kws)
        self.assertIn("环境", kws)
        self.assertTrue(all(k["weight"] > 0
                            for k in perception["keywords"]))

    def test_sort_desc(self):
        """得分降序排序"""
        hits = self.router.detect_capabilities("扫描环境并整理房间")
        scores = [h["score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_reason_explainable(self):
        """命中原因含权重明细"""
        hits = self.router.detect_capabilities("扫描")
        self.assertIn("命中", hits[0]["reason"])
        self.assertIn("权重", hits[0]["reason"])

    def test_no_hit_empty(self):
        """无命中 → 空"""
        self.assertEqual(self.router.detect_capabilities("zzz"), [])

    def test_score_present_all(self):
        """所有命中含 score"""
        hits = self.router.detect_capabilities("扫描并整理")
        self.assertTrue(all("score" in h for h in hits))


class TestRouteTopK(unittest.TestCase):
    """Top-K 路由"""

    def setUp(self):
        self.router = make_router(top_k=3)

    def test_route_scores_field(self):
        """RouteResult 含 scores (可解释打分)"""
        r = self.router.route({"text": "扫描并整理"})
        self.assertIn("scores", r)
        self.assertEqual(len(r["scores"]), len(r["capabilities"]))
        self.assertTrue(all("score" in s for s in r["scores"]))

    def test_route_weighted_keywords(self):
        """RouteResult 含 weighted_keywords"""
        r = self.router.route({"text": "扫描"})
        self.assertIn("weighted_keywords", r)
        self.assertTrue(all("keywords" in w
                            for w in r["weighted_keywords"]))

    def test_topk_limits_capabilities(self):
        """Top-K 限制能力域数量"""
        # 构造 4+ 能力域命中: 扫描(perception) 整理(long_horizon)
        # 规划(planning) 治理(governance) 全部命中
        text = "扫描并整理规划治理"
        r = self.router.route({"text": text})
        self.assertLessEqual(len(r["capabilities"]), 3)

    def test_topk_1(self):
        """Top-1 只取得分最高"""
        router = make_router(top_k=1)
        r = router.route({"text": "扫描并整理"})
        self.assertEqual(len(r["capabilities"]), 1)

    def test_topk_5(self):
        """Top-5 全取"""
        router = make_router(top_k=5)
        r = router.route({"text": "扫描并整理规划治理"})
        self.assertLessEqual(len(r["capabilities"]), 5)

    def test_topk_highest_first(self):
        """Top-K 得分最高优先"""
        # 扫描(perception 3.0) 整理(long_horizon 2.0)
        r = self.router.route({"text": "扫描环境并整理"})
        self.assertEqual(r["capabilities"][0], "perception")

    def test_route_reason_has_topk(self):
        """路由原因含 Top-K 说明"""
        r = self.router.route({"text": "扫描"})
        self.assertIn("Top-3", r["reason"])
        self.assertIn("得分", r["reason"])

    def test_fallback_scores(self):
        """回退默认带分数"""
        r = self.router.route({"text": "zzz"})
        self.assertTrue(r["fallback"])
        self.assertEqual(len(r["scores"]), 2)
        self.assertTrue(all(s["score"] == 1.0 for s in r["scores"]))

    def test_invalid_topk_raises(self):
        """top_k <= 0 → RouterError"""
        reg = SpecialistRegistry()
        with self.assertRaises(RouterError):
            CompanionRouter(reg, top_k=0)

    def test_custom_topk(self):
        """自定义 Top-K"""
        router = make_router(top_k=2)
        r = router.route({"text": "扫描并整理规划"})
        self.assertLessEqual(len(r["capabilities"]), 2)

    def test_assigned_agents_still_correct(self):
        """Top-K 后分派 Agent 正确"""
        r = self.router.route({"text": "扫描"})
        self.assertEqual(r["assigned_agents"], ["perception_agent"])


if __name__ == "__main__":
    unittest.main()
