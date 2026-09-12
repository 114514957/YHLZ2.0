"""
YHLZ Personality Engine V3.4 - Service 单元测试

覆盖:
    - 权限默认拒绝 → 开启 → 重置
    - save (敏感拦截 / 数量上限) / load_default / switch / CRUD
    - personality_style 风格生成
    - assess_consistency 一致性评估
    - build_persona_context 上下文
    - status / 日志查询
"""
import unittest

from backend.personality.logger import PersonalityLogger
from backend.personality.manager import PersonalityManager
from backend.personality.permission import PermissionChecker
from backend.personality.schema import PersonalityProfile, PersonalityQuery
from backend.personality.service import PersonalityService
from backend.personality.stores.memory_store import InMemoryPersonalityStore


class TestPersonalityService(unittest.TestCase):

    def setUp(self):
        self.store = InMemoryPersonalityStore()
        self.mgr = PersonalityManager()
        # 注意: 测试模式下 register_defaults 会以 "memory" 为 key 覆盖注册
        # 因此使用自定义 key "test", 避免默认注册覆盖注入的 store
        self.mgr.register_store("test", self.store)
        self.svc = PersonalityService(
            manager=self.mgr,
            permission=PermissionChecker(),
            plog=PersonalityLogger(enable_logging=False),
        )
        self.svc.load_config({"personality_enabled": True, "max_profiles": 5})

    def test_load_config_enables(self):
        self.assertTrue(self.svc.get_permission()["personality_enabled"])
        self.assertTrue(self.svc._initialized)

    # ── 权限 ──────────────────────────────────────────────────────
    def test_default_denied(self):
        svc = PersonalityService(
            manager=PersonalityManager(),
            permission=PermissionChecker(),
            plog=PersonalityLogger(enable_logging=False),
        )
        svc.load_config({})
        res = svc.personality_style()
        self.assertFalse(res.success)
        self.assertEqual(res.status, "denied")

    def test_update_and_reset_permission(self):
        self.svc.update_permission(personality_enabled=False)
        self.assertFalse(self.svc.get_permission()["personality_enabled"])
        self.svc.reset_permission()
        self.assertFalse(self.svc.get_permission()["personality_enabled"])

    # ── save ──────────────────────────────────────────────────────
    def test_save(self):
        res = self.svc.save(PersonalityProfile.create(name="新人格"))
        self.assertTrue(res.success)
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.count, 1)
        self.assertEqual(self.svc.count(), 1)

    def test_save_sensitive_blocked(self):
        res = self.svc.save(PersonalityProfile.create(
            name="测试", description="手机号 13800138000"))
        self.assertFalse(res.success)
        self.assertEqual(res.status, "invalid")
        self.assertEqual(self.svc.count(), 0)

    def test_save_max_profiles(self):
        for i in range(5):
            res = self.svc.save(PersonalityProfile.create(name=f"人格{i}"))
            self.assertTrue(res.success)
        res = self.svc.save(PersonalityProfile.create(name="超限人格"))
        self.assertFalse(res.success)
        self.assertIn("上限", res.error)

    def test_save_denied(self):
        self.svc.update_permission(personality_enabled=False)
        res = self.svc.save(PersonalityProfile.create(name="x"))
        self.assertFalse(res.success)
        self.assertEqual(res.status, "denied")

    # ── 默认人格 / 当前人格 ────────────────────────────────────────
    def test_load_default_creates_profile(self):
        res = self.svc.load_default()
        self.assertTrue(res.success)
        self.assertEqual(res.profile.name, "YHLZ 默认人格")
        self.assertEqual(self.svc.count(), 1)
        current = self.svc.get_current_profile()
        self.assertTrue(current.success)
        self.assertEqual(current.profile.profile_id, res.profile_id)

    def test_load_default_uses_existing_active(self):
        p = PersonalityProfile.create(name="自定义人格", active=True)
        self.svc.save(p)
        res = self.svc.load_default()
        self.assertTrue(res.success)
        self.assertEqual(res.profile_id, p.profile_id)

    def test_load_default_denied(self):
        self.svc.update_permission(personality_enabled=False)
        res = self.svc.load_default()
        self.assertFalse(res.success)
        self.assertEqual(res.status, "denied")

    def test_switch_profile(self):
        a = self.svc.save(PersonalityProfile.create(name="人格A", active=True))
        b = self.svc.save(PersonalityProfile.create(name="人格B"))
        res = self.svc.switch_profile(b.profile_id)
        self.assertTrue(res.success)
        current = self.svc.get_current_profile()
        self.assertEqual(current.profile.profile_id, b.profile_id)
        self.assertFalse(self.store.retrieve(a.profile_id).active)

    def test_switch_missing(self):
        res = self.svc.switch_profile("not-exist")
        self.assertFalse(res.success)
        self.assertEqual(res.status, "not_found")

    def test_switch_empty(self):
        res = self.svc.switch_profile("")
        self.assertFalse(res.success)
        self.assertEqual(res.status, "empty_input")

    # ── CRUD ──────────────────────────────────────────────────────
    def test_retrieve(self):
        pid = self.svc.save(PersonalityProfile.create(name="检索人格")).profile_id
        res = self.svc.retrieve(pid)
        self.assertTrue(res.success)
        self.assertEqual(res.profile.name, "检索人格")

    def test_retrieve_missing(self):
        res = self.svc.retrieve("not-exist")
        self.assertFalse(res.success)
        self.assertEqual(res.status, "not_found")

    def test_query(self):
        self.svc.save(PersonalityProfile.create(name="温暖人格", traits={"warmth": 4.5}))
        self.svc.save(PersonalityProfile.create(name="严谨人格", traits={"rigor": 4.5}))
        res = self.svc.query(PersonalityQuery(trait_filter={"warmth": 4.0}))
        self.assertTrue(res.success)
        self.assertEqual(res.count, 1)
        self.assertEqual(res.profiles[0].name, "温暖人格")

    def test_update(self):
        pid = self.svc.save(PersonalityProfile.create(name="原人格")).profile_id
        res = self.svc.update(pid, name="新人格")
        self.assertTrue(res.success)
        self.assertEqual(self.store.retrieve(pid).name, "新人格")

    def test_update_missing(self):
        res = self.svc.update("not-exist", name="x")
        self.assertFalse(res.success)
        self.assertEqual(res.status, "not_found")

    def test_delete(self):
        pid = self.svc.save(PersonalityProfile.create(name="删除人格")).profile_id
        res = self.svc.delete(pid)
        self.assertTrue(res.success)
        self.assertEqual(self.svc.count(), 0)

    def test_clear(self):
        self.svc.save(PersonalityProfile.create(name="a"))
        self.svc.save(PersonalityProfile.create(name="b"))
        res = self.svc.clear()
        self.assertTrue(res.success)
        self.assertEqual(res.count, 2)
        self.assertEqual(self.svc.count(), 0)

    # ── 风格生成 ──────────────────────────────────────────────────
    def test_personality_style_default(self):
        self.svc.load_default()
        res = self.svc.personality_style()
        self.assertTrue(res.success)
        self.assertIn("你是 YHLZ 默认人格", res.style)
        self.assertIn("温暖", res.style)
        self.assertIn("友好", res.style)
        self.assertIn("简洁", res.style)
        self.assertIn("行为准则", res.style)

    def test_personality_style_low_traits_natural(self):
        self.svc.save(PersonalityProfile.create(
            name="中性人格", active=True,
            traits={"warmth": 2.0, "friendliness": 2.0, "humor": 2.0,
                    "rigor": 2.0, "conciseness": 2.0},
        ))
        res = self.svc.personality_style()
        self.assertTrue(res.success)
        self.assertIn("自然", res.style)

    def test_personality_style_emoji_pref(self):
        self.svc.save(PersonalityProfile.create(
            name="表情人格", active=True,
            preferences={"use_emojis": True},
        ))
        res = self.svc.personality_style()
        self.assertIn("允许使用表情符号", res.style)

    def test_personality_style_no_emoji(self):
        self.svc.load_default()
        res = self.svc.personality_style()
        self.assertIn("不使用表情符号", res.style)

    # ── 一致性评估 ────────────────────────────────────────────────
    def test_assess_consistency_empty(self):
        res = self.svc.assess_consistency("")
        self.assertFalse(res.success)
        self.assertEqual(res.status, "empty_input")

    def test_assess_consistency_default_warm(self):
        self.svc.load_default()
        res = self.svc.assess_consistency("谢谢你, 别担心, 请慢慢来")
        self.assertTrue(res.success)
        self.assertGreaterEqual(res.consistency, 0.0)
        self.assertLessEqual(res.consistency, 1.0)

    def test_assess_consistency_cold_profile_low_warmth(self):
        self.svc.save(PersonalityProfile.create(
            name="冷峻人格", active=True,
            traits={"warmth": 1.0, "friendliness": 1.0, "conciseness": 5.0},
            preferences={"use_emojis": False},
        ))
        res = self.svc.assess_consistency("结果如下: 123")
        self.assertTrue(res.success)
        self.assertIsNotNone(res.consistency)

    # ── 上下文 ────────────────────────────────────────────────────
    def test_build_persona_context_enabled(self):
        self.svc.load_default()
        ctx = self.svc.build_persona_context()
        self.assertIn("YHLZ 默认人格", ctx)
        self.assertIn("交流方式", ctx)

    def test_build_persona_context_denied_empty(self):
        self.svc.update_permission(personality_enabled=False)
        self.assertEqual(self.svc.build_persona_context(), "")

    # ── 状态 / 日志 ───────────────────────────────────────────────
    def test_status(self):
        self.svc.load_default()
        st = self.svc.status()
        self.assertEqual(st["version"], "3.4.0")
        self.assertTrue(st["initialized"])
        self.assertEqual(st["profile_count"], 1)

    def test_logs_query_and_clear(self):
        self.svc.load_default()
        self.assertGreaterEqual(len(self.svc.get_logs(limit=10)), 1)
        self.assertGreaterEqual(self.svc.get_log_stats()["total"], 1)
        n = self.svc.clear_logs()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(self.svc.get_log_stats()["total"], 0)

    def test_list_stores(self):
        stores = self.svc.list_stores()
        names = [s["name"] for s in stores]
        self.assertIn("test", names)


if __name__ == "__main__":
    unittest.main()
