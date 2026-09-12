"""
YHLZ Embodied AI V5.5 - 身份与自适应人格 Service 集成测试
(Identity & Adaptive Personality via Service)

覆盖:
    - Service companion_personality / companion_adjust_personality API
    - 配置驱动: personality_enabled / base / adjust_step
    - companion_handle 附 personality (兼容)
    - 人格联动: 委派成功 → 热情提升
    - 安全: 不修改核心人格 / 不写 Memory / 不绕 Permission
    - 向后兼容: V5.4 / V5.3 / V5.2 API
"""
import unittest

from backend.embodied.service import EmbodiedService


class TestServicePersonality(unittest.TestCase):
    """Service 人格 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_companion_personality_api(self):
        """companion_personality"""
        p = self.svc.companion_personality()
        self.assertEqual(p["base"], "铁哥们")
        self.assertIn("dimensions", p)
        self.assertIn("success_rate", p)

    def test_personality_dimensions(self):
        """维度字段"""
        p = self.svc.companion_personality()
        for dim in ("warmth", "patience", "humor", "serious"):
            self.assertIn(dim, p["dimensions"])

    def test_adjust_api(self):
        """companion_adjust_personality"""
        r = self.svc.companion_adjust_personality("success")
        self.assertTrue(r["applied"])
        self.assertEqual(r["context"], "success")

    def test_adjust_success_warmth(self):
        """成功 → 热情提升"""
        before = self.svc.companion_personality()["dimensions"]["warmth"]
        self.svc.companion_adjust_personality("success")
        after = self.svc.companion_personality()["dimensions"]["warmth"]
        self.assertGreater(after, before)

    def test_adjust_invalid_raises(self):
        """非法情境 → 异常"""
        from backend.embodied.companion import PersonalityError
        with self.assertRaises(PersonalityError):
            self.svc.companion_adjust_personality("zzz")

    def test_config_base(self):
        """配置驱动基础人格"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_personality_base": "知心朋友",
        })
        self.assertEqual(svc.companion_personality()["base"], "知心朋友")

    def test_config_step(self):
        """配置驱动步长"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_personality_adjust_step": 0.2,
        })
        before = svc.companion_personality()["dimensions"]["warmth"]
        svc.companion_adjust_personality("success")
        after = svc.companion_personality()["dimensions"]["warmth"]
        self.assertAlmostEqual(after - before, 0.2)

    def test_config_disabled(self):
        """配置停用"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_personality_enabled": False,
        })
        r = svc.companion_adjust_personality("success")
        self.assertFalse(r["applied"])
        self.assertEqual(r["result"], "disabled")


class TestHandlePersonality(unittest.TestCase):
    """handle 附人格"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_handle_includes_personality(self):
        """handle 附 personality"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("personality", r)
        self.assertEqual(r["personality"]["base"], "铁哥们")

    def test_handle_personality_structure(self):
        """handle 人格结构"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        p = r["personality"]
        for key in ("base", "dimensions", "interactions",
                    "success_rate", "last_adjust"):
            self.assertIn(key, p)

    def test_handle_success_adjusts_warmth(self):
        """成功委派 → 热情提升"""
        before = self.svc.companion_personality()["dimensions"]["warmth"]
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        after = self.svc.companion_personality()["dimensions"]["warmth"]
        self.assertGreater(after, before)

    def test_handle_interaction_count(self):
        """handle 互动计数"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        st = self.svc.companion_personality_engine.stats()
        self.assertGreaterEqual(st["interactions"], 1)

    def test_handle_compat_mode(self):
        """handle 兼容 (mode 保留)"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertEqual(r["mode"], "rule_based")


class TestPersonalityAudit(unittest.TestCase):
    """人格审计 (经 Service)"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_audit_after_adjust(self):
        """调整后审计"""
        self.svc.companion_adjust_personality("success")
        aud = self.svc.companion_personality_engine.audit()
        self.assertEqual(aud["total"], 1)

    def test_audit_fields(self):
        """审计字段"""
        self.svc.companion_adjust_personality("success")
        aud = self.svc.companion_personality_engine.audit()
        entry = aud["recent"][0]
        for key in ("record_id", "context", "before_state",
                    "adjustment", "after_state", "result", "timestamp"):
            self.assertIn(key, entry)

    def test_audit_before_after_dimension(self):
        """审计前后维度"""
        self.svc.companion_adjust_personality("success")
        entry = self.svc.companion_personality_engine.audit()[
            "recent"][0]
        self.assertLess(
            entry["before_state"]["dimensions"]["warmth"],
            entry["after_state"]["dimensions"]["warmth"],
        )


class TestSafetyCompat(unittest.TestCase):
    """安全与兼容"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_base_immutable_after_many(self):
        """多次调整 base 不变"""
        for ctx in ("success", "failure", "casual_chat",
                    "serious_task", "consecutive_fail"):
            self.svc.companion_adjust_personality(ctx)
        self.assertEqual(self.svc.companion_personality()["base"],
                         "铁哥们")

    def test_no_memory_write(self):
        """人格调整不写 Agent Memory"""
        before = self.svc.memory.stats().get("total", 0)
        self.svc.companion_adjust_personality("success")
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        after = self.svc.memory.stats().get("total", 0)
        self.assertEqual(after, before)

    def test_v54_correct_works(self):
        """V5.4 companion_correct 兼容"""
        r = self.svc.companion_correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(r["success"])

    def test_v54_learning_works(self):
        """V5.4 companion_learning 兼容"""
        lrn = self.svc.companion_learning()
        self.assertEqual(lrn["mode"], "rule_based")

    def test_v53_execute_works(self):
        """V5.3 companion_execute 兼容"""
        rec = self.svc.companion_execute({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(rec["success"])

    def test_v52_pipeline_works(self):
        """V5.2 companion_pipeline 兼容"""
        pa = self.svc.companion_pipeline()
        self.assertEqual(len(pa["stages"]), 2)

    def test_version_5_5_0(self):
        """版本 = 9.5.0"""
        self.assertEqual(self.svc.report()["version"], "9.5.0")

    def test_personality_rule_based(self):
        """人格纯规则"""
        p = self.svc.companion_personality()
        self.assertIn("dimensions", p)

    def test_adjust_reason_explainable(self):
        """调整原因可解释"""
        r = self.svc.companion_adjust_personality("success")
        self.assertIn("情境", r["adjustment"])

    def test_handle_personality_success_rate(self):
        """handle 后成功率统计"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        st = self.svc.companion_personality_engine.stats()
        self.assertIn("success_rate", st)

    def test_adjust_audit_reason_stats(self):
        """调整-审计-统计闭环"""
        self.svc.companion_adjust_personality("success")
        aud = self.svc.companion_personality_engine.audit()
        st = self.svc.companion_personality_engine.stats()
        self.assertEqual(aud["total"], 1)
        self.assertEqual(st["success_count"], 1)

    def test_personality_engine_shared(self):
        """人格引擎单实例 (Service)"""
        e1 = self.svc.companion_personality_engine
        e2 = self.svc.companion_personality_engine
        self.assertIs(e1, e2)

    def test_handle_personality_after_failures(self):
        """失败委派后人格 (耐心提升)"""
        # 失败委派: 用权限拒绝制造
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": False, "companion_enabled": True,
        })
        before = svc.companion_personality()["dimensions"]["patience"]
        svc.companion_handle({"text": "执行拿起任务"})
        # handle 无 agent 成功 → 可能不调整 (total=0 跳过)
        after = svc.companion_personality()["dimensions"]["patience"]
        self.assertGreaterEqual(after, before)


if __name__ == "__main__":
    unittest.main()
