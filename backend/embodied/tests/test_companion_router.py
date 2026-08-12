"""
YHLZ Embodied AI V5.0 - 内部消息路由单元测试 (Companion Router)

覆盖 (router.py):
    - detect_capabilities: 关键词 → 能力域 (可解释命中)
    - route: 请求 → 专业 Agent 分派 (确定性)
    - 各能力域关键词路由 (perception/reasoning/experience/planning/
      long_horizon/governance)
    - 多关键词组合路由
    - 路由回退: 无法识别意图 → 默认委派 (perception + experience)
    - 参数校验: 非法注册中心
"""
import unittest

from backend.embodied.companion import (
    FALLBACK_CAPABILITIES,
    CompanionRouter,
    INTENT_KEYWORDS,
    ROUTE_RULE_VERSION,
    RouterError,
    SpecialistRegistry,
)


def ok_handler(request):
    return {"ok": True}


def make_router():
    reg = SpecialistRegistry()
    for cap in ("perception", "reasoning", "experience", "planning",
                "long_horizon", "governance"):
        reg.register_simple(f"{cap}_agent", cap, ok_handler)
    return CompanionRouter(reg)


class TestDetectCapabilities(unittest.TestCase):
    """意图关键词检测"""

    def setUp(self):
        self.router = make_router()

    def test_perception_keyword(self):
        """观察 → perception"""
        hits = self.router.detect_capabilities("观察一下环境")
        caps = {h["capability"] for h in hits}
        self.assertIn("perception", caps)

    def test_reasoning_keyword(self):
        """为什么 → reasoning"""
        hits = self.router.detect_capabilities("为什么失败了")
        caps = {h["capability"] for h in hits}
        self.assertIn("reasoning", caps)

    def test_experience_keyword(self):
        """策略 → experience"""
        hits = self.router.detect_capabilities("有什么策略建议")
        caps = {h["capability"] for h in hits}
        self.assertIn("experience", caps)

    def test_planning_keyword(self):
        """规划 → planning"""
        hits = self.router.detect_capabilities("做个规划")
        caps = {h["capability"] for h in hits}
        self.assertIn("planning", caps)

    def test_long_horizon_keyword(self):
        """整理 → long_horizon"""
        hits = self.router.detect_capabilities("帮我整理房间")
        caps = {h["capability"] for h in hits}
        self.assertIn("long_horizon", caps)

    def test_governance_keyword(self):
        """治理 → governance"""
        hits = self.router.detect_capabilities("策略治理健康检查")
        caps = {h["capability"] for h in hits}
        self.assertIn("governance", caps)

    def test_english_keywords(self):
        """英文关键词"""
        hits = self.router.detect_capabilities("scan the room")
        caps = {h["capability"] for h in hits}
        self.assertIn("perception", caps)

    def test_hit_has_reason(self):
        """命中含可解释原因 (V5.1: 加权打分结构)"""
        hits = self.router.detect_capabilities("扫描")
        self.assertTrue(all("reason" in h for h in hits))
        self.assertTrue(all("keywords" in h for h in hits))
        self.assertTrue(all("score" in h for h in hits))
        self.assertTrue(all(kw.get("weight", 0) > 0
                            for h in hits for kw in h["keywords"]))

    def test_no_hit(self):
        """无命中 → 空列表"""
        hits = self.router.detect_capabilities("zzzz")
        self.assertEqual(hits, [])

    def test_keyword_table_nonempty(self):
        """关键词表覆盖全部能力域"""
        for cap in ("perception", "reasoning", "experience", "planning",
                    "long_horizon", "governance"):
            self.assertTrue(INTENT_KEYWORDS[cap], f"{cap} 无关键词")


class TestRoute(unittest.TestCase):
    """路由分派"""

    def setUp(self):
        self.router = make_router()

    def test_route_structure(self):
        """路由输出结构"""
        r = self.router.route({"text": "扫描"})
        for key in ("request_text", "rule_version", "capabilities",
                    "assigned_agents", "fallback", "reason"):
            self.assertIn(key, r)
        self.assertEqual(r["rule_version"], ROUTE_RULE_VERSION)

    def test_route_perception(self):
        """扫描 → perception_agent"""
        r = self.router.route({"text": "扫描环境"})
        self.assertEqual(r["capabilities"], ["perception"])
        self.assertIn("perception_agent", r["assigned_agents"])
        self.assertFalse(r["fallback"])

    def test_route_long_horizon(self):
        """整理房间 → long_horizon_agent"""
        r = self.router.route({"text": "帮我整理房间"})
        self.assertIn("long_horizon_agent", r["assigned_agents"])

    def test_route_multi_capability(self):
        """多关键词 → 多能力域"""
        r = self.router.route({"text": "扫描后整理房间并规划预算"})
        caps = set(r["capabilities"])
        self.assertTrue({"perception", "long_horizon", "planning"}
                        <= caps)

    def test_route_intent_field(self):
        """intent 字段作为意图源"""
        r = self.router.route({"intent": "扫描"})
        self.assertIn("perception", r["capabilities"])

    def test_route_query_field(self):
        """query 字段作为意图源"""
        r = self.router.route({"query": "为什么失败"})
        self.assertIn("reasoning", r["capabilities"])

    def test_route_fallback(self):
        """无命中 → 回退默认"""
        r = self.router.route({"text": "zzz"})
        self.assertTrue(r["fallback"])
        self.assertEqual(set(r["capabilities"]),
                         set(FALLBACK_CAPABILITIES))
        self.assertIn("回退", r["reason"])

    def test_route_reason_explainable(self):
        """路由原因可解释"""
        r = self.router.route({"text": "扫描"})
        self.assertIn("路由规则", r["reason"])

    def test_route_no_registered_agent(self):
        """无已启用 Agent → 占位"""
        reg = SpecialistRegistry()
        router = CompanionRouter(reg)
        r = router.route({"text": "扫描"})
        self.assertEqual(r["assigned_agents"], ["<无已启用专业 Agent>"])

    def test_route_ignores_disabled(self):
        """停用 Agent 不参与分派"""
        reg = SpecialistRegistry()
        reg.register_simple("p1", "perception", ok_handler)
        reg.register_simple("p2", "perception", ok_handler)
        reg.set_enabled("p2", False)
        router = CompanionRouter(reg)
        r = router.route({"text": "扫描"})
        self.assertEqual(r["assigned_agents"], ["p1"])

    def test_invalid_registry_raises(self):
        """非法注册中心 → RouterError"""
        with self.assertRaises(RouterError):
            CompanionRouter(None)

    def test_rule_version_config(self):
        """规则版本可配置"""
        reg = SpecialistRegistry()
        router = CompanionRouter(reg, rule_version="v2")
        r = router.route({"text": "扫描"})
        self.assertEqual(r["rule_version"], "v2")


if __name__ == "__main__":
    unittest.main()
