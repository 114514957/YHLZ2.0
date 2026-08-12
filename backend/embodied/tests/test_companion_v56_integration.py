"""
YHLZ Embodied AI V5.6 - 关系与人格稳定 Service 集成测试
(Relationship & Personality Stability via Service)

覆盖:
    - Service companion_relationship / companion_relationship_update /
      companion_personality_stability API
    - 配置驱动: decay_enabled / relationship_enabled / window_days / decay_rate
    - companion_handle 附 relationship + personality + window_stats
    - 审计升级: PersonalityAuditRecord 含 relationship_context/decay_reason/
      window_statistics
    - 集成流程: Interaction → Relationship → Personality → Response
    - 安全: 不写 Memory / 核心人格不变
    - 向后兼容
"""
import unittest

from backend.embodied.service import EmbodiedService


class TestServiceRelationship(unittest.TestCase):
    """Service 关系 API"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_companion_relationship_api(self):
        """companion_relationship"""
        rel = self.svc.companion_relationship()
        for key in ("trust_level", "familiarity",
                    "communication_style", "relationship_stage"):
            self.assertIn(key, rel)

    def test_relationship_default_trust(self):
        """默认信任 0.5"""
        rel = self.svc.companion_relationship()
        self.assertEqual(rel["trust_level"], 0.5)

    def test_relationship_update_api(self):
        """companion_relationship_update"""
        r = self.svc.companion_relationship_update(success=True)
        self.assertTrue(r["updated"])
        self.assertGreater(r["trust_level"], 0.5)

    def test_relationship_update_failure(self):
        """失败更新"""
        r = self.svc.companion_relationship_update(success=False)
        self.assertLess(r["trust_level"], 0.5)

    def test_personality_stability_api(self):
        """companion_personality_stability"""
        st = self.svc.companion_personality_stability()
        for key in ("current", "base", "decay",
                    "adjust_history", "relationship"):
            self.assertIn(key, st)

    def test_stability_decay_fields(self):
        """衰减状态字段"""
        st = self.svc.companion_personality_stability()
        decay = st["decay"]
        for key in ("mode", "enabled", "decay_rate", "base",
                    "current", "total_offset", "per_dimension",
                    "stable"):
            self.assertIn(key, decay)

    def test_stability_base_immutable(self):
        """基础人格不变"""
        st = self.svc.companion_personality_stability()
        self.assertEqual(st["base"]["warmth"], 0.8)

    def test_window_stats_api(self):
        """companion_window_stats"""
        ws = self.svc.companion_window_stats(days=7)
        self.assertEqual(ws["window_days"], 7)
        self.assertEqual(ws["mode"], "rule_based")

    def test_window_stats_30(self):
        """30 天窗口"""
        ws = self.svc.companion_window_stats(days=30)
        self.assertEqual(ws["window_days"], 30)


class TestHandleV56(unittest.TestCase):
    """handle 增强"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_handle_includes_relationship(self):
        """handle 附 relationship"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("relationship", r)
        self.assertIn("trust_level", r["relationship"])

    def test_handle_includes_personality(self):
        """handle 附 personality (V5.5 兼容)"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("personality", r)
        self.assertEqual(r["personality"]["base"], "铁哥们")

    def test_handle_includes_window_stats(self):
        """handle 附 window_stats"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("window_stats", r)
        self.assertIn("recent_success_rate", r["window_stats"])

    def test_handle_updates_relationship(self):
        """handle 更新关系"""
        before = self.svc.companion_relationship()["interaction_count"]
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        after = self.svc.companion_relationship()["interaction_count"]
        self.assertGreater(after, before)

    def test_handle_updates_window(self):
        """handle 更新窗口统计"""
        before = self.svc.companion_window_stats(days=7)[
            "recent_interaction_count"]
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        after = self.svc.companion_window_stats(days=7)[
            "recent_interaction_count"]
        self.assertGreater(after, before)


class TestIntegrationFlow(unittest.TestCase):
    """集成流程: Interaction → Relationship → Personality → Response"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_full_flow(self):
        """完整流程"""
        # 多次成功互动
        for _ in range(5):
            self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        # 关系: 互动计数增加
        rel = self.svc.companion_relationship()
        self.assertGreaterEqual(rel["interaction_count"], 5)
        # 人格: 成功 → 热情提升
        p = self.svc.companion_personality()
        self.assertGreaterEqual(p["dimensions"]["warmth"], 0.8)
        # 响应: 含关系+人格
        resp = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("relationship", resp)
        self.assertIn("personality", resp)

    def test_relationship_personality_link(self):
        """关系-人格联动 (连续失败 → patience)"""
        # 用权限拒绝制造失败
        svc = EmbodiedService()
        svc.load_config({"embodied_enabled": False,
                         "companion_enabled": True})
        before = svc.companion_personality()["dimensions"]["patience"]
        for _ in range(3):
            svc.companion_handle({"text": "执行拿起任务"})
        after = svc.companion_personality()["dimensions"]["patience"]
        self.assertGreaterEqual(after, before)


class TestAuditUpgrade(unittest.TestCase):
    """审计升级"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_audit_upgraded_fields(self):
        """审计含 V5.6 字段"""
        self.svc.companion_adjust_personality("success")
        aud = self.svc.companion_personality_engine.audit()
        entry = aud["recent"][0]
        for key in ("relationship_context", "decay_reason",
                    "window_statistics"):
            self.assertIn(key, entry)

    def test_audit_new_fields_defaults(self):
        """新字段默认空"""
        self.svc.companion_adjust_personality("success")
        entry = self.svc.companion_personality_engine.audit()[
            "recent"][0]
        self.assertEqual(entry["relationship_context"], {})
        self.assertEqual(entry["decay_reason"], "")
        self.assertEqual(entry["window_statistics"], {})

    def test_audit_all_fields(self):
        """审计全字段"""
        self.svc.companion_adjust_personality("success")
        entry = self.svc.companion_personality_engine.audit()[
            "recent"][0]
        for key in ("record_id", "context", "before_state",
                    "adjustment", "after_state", "result",
                    "timestamp", "relationship_context",
                    "decay_reason", "window_statistics"):
            self.assertIn(key, entry)


class TestConfigV56(unittest.TestCase):
    """配置驱动"""

    def test_decay_enabled_config(self):
        """衰减启用配置"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_personality_decay_enabled": False,
        })
        self.assertFalse(svc.companion_decay.enabled)

    def test_decay_rate_config(self):
        """衰减率配置"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_decay_rate": 0.1,
        })
        self.assertEqual(svc.companion_decay.rate, 0.1)

    def test_relationship_disabled_config(self):
        """关系停用配置"""
        svc = EmbodiedService()
        svc.load_config({
            "embodied_enabled": True,
            "companion_relationship_enabled": False,
        })
        r = svc.companion_relationship_update(success=True)
        self.assertFalse(r["updated"])


class TestSafetyCompatV56(unittest.TestCase):
    """安全与兼容"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({
            "embodied_enabled": True,
            "companion_enabled": True,
        })

    def test_no_memory_write(self):
        """关系/稳定不写 Agent Memory"""
        before = self.svc.memory.stats().get("total", 0)
        self.svc.companion_relationship_update(success=True)
        self.svc.companion_personality_stability()
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        after = self.svc.memory.stats().get("total", 0)
        self.assertEqual(after, before)

    def test_base_immutable(self):
        """核心人格不变"""
        self.svc.companion_relationship_update(success=True)
        self.svc.companion_relationship_update(success=False)
        p = self.svc.companion_personality()
        self.assertEqual(p["base"], "铁哥们")

    def test_v55_personality_api_works(self):
        """V5.5 companion_personality 兼容"""
        p = self.svc.companion_personality()
        self.assertIn("dimensions", p)

    def test_v54_correct_works(self):
        """V5.4 companion_correct 兼容"""
        r = self.svc.companion_correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(r["success"])

    def test_v53_execute_works(self):
        """V5.3 companion_execute 兼容"""
        rec = self.svc.companion_execute({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(rec["success"])

    def test_version_5_6_0(self):
        """版本 = 9.5.0"""
        self.assertEqual(self.svc.report()["version"], "9.5.0")

    def test_window_stats_only_numbers(self):
        """窗口统计只存数字"""
        ws = self.svc.companion_window_stats(days=7)
        self.assertTrue(all(isinstance(v, (int, float))
                            for k, v in ws.items() if k != "mode"))

    def test_relationship_stage_default(self):
        """默认关系阶段 familiar"""
        rel = self.svc.companion_relationship()
        self.assertEqual(rel["relationship_stage"], "familiar")

    def test_relationship_style_default(self):
        """默认沟通风格 casual"""
        rel = self.svc.companion_relationship()
        self.assertEqual(rel["communication_style"], "casual")

    def test_relationship_update_multiple(self):
        """多次更新关系"""
        for _ in range(3):
            self.svc.companion_relationship_update(success=True)
        rel = self.svc.companion_relationship()
        self.assertEqual(rel["interaction_count"], 3)
        self.assertGreater(rel["trust_level"], 0.5)

    def test_stability_current_personality(self):
        """稳定状态含当前人格"""
        st = self.svc.companion_personality_stability()
        self.assertIn("dimensions", st["current"])

    def test_stability_relationship(self):
        """稳定状态含关系"""
        st = self.svc.companion_personality_stability()
        self.assertIn("trust_level", st["relationship"])

    def test_window_stats_empty_initial(self):
        """初始窗口空"""
        ws = self.svc.companion_window_stats(days=7)
        self.assertEqual(ws["recent_interaction_count"], 0)

    def test_handle_personality_present_after(self):
        """handle 后人格仍可查"""
        self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        p = self.svc.companion_personality()
        self.assertEqual(p["base"], "铁哥们")

    def test_audit_upgrade_full_flow(self):
        """审计升级端到端"""
        self.svc.companion_adjust_personality("success")
        self.svc.companion_relationship_update(success=True)
        entry = self.svc.companion_personality_engine.audit()[
            "recent"][0]
        self.assertIn("relationship_context", entry)
        self.assertIn("decay_reason", entry)
        self.assertIn("window_statistics", entry)

    def test_decay_applied_in_handle(self):
        """handle 触发衰减应用 (无异常)"""
        r = self.svc.companion_handle({"text": "扫描环境查看策略建议"})
        self.assertIn("personality", r)
        self.assertIn("window_stats", r)


if __name__ == "__main__":
    unittest.main()
