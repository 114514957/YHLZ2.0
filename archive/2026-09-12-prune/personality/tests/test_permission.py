"""
YHLZ Personality Engine V3.4 - 权限单元测试

覆盖:
    - 默认拒绝 (personality_enabled=False)
    - load / update / reset
    - check_enabled / check_save 敏感信息拦截
    - sanitize_text 清洗
"""
import unittest

from backend.personality.permission import (
    PersonalityPermission,
    PermissionChecker,
    sanitize_text,
)
from backend.personality.schema import PersonalityProfile


class TestPersonalityPermission(unittest.TestCase):

    def test_default_denied(self):
        perm = PersonalityPermission()
        self.assertFalse(perm.personality_enabled)
        self.assertFalse(perm.allow_sensitive)
        self.assertEqual(perm.max_profiles, 50)

    def test_to_dict_from_dict(self):
        perm = PersonalityPermission(personality_enabled=True, allow_sensitive=True, max_profiles=10)
        d = perm.to_dict()
        self.assertTrue(d["personality_enabled"])
        perm2 = PersonalityPermission.from_dict(d)
        self.assertTrue(perm2.personality_enabled)
        self.assertTrue(perm2.allow_sensitive)
        self.assertEqual(perm2.max_profiles, 10)


class TestPermissionChecker(unittest.TestCase):

    def setUp(self):
        self.checker = PermissionChecker()

    def test_check_enabled_default_denied(self):
        allowed, reason = self.checker.check_enabled()
        self.assertFalse(allowed)
        self.assertIn("personality_enabled", reason)

    def test_check_enabled_after_load(self):
        self.checker.load(personality_enabled=True)
        allowed, reason = self.checker.check_enabled()
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_load_from_permission(self):
        self.checker.load_from_permission(PersonalityPermission(personality_enabled=True))
        allowed, _ = self.checker.check_enabled()
        self.assertTrue(allowed)

    def test_update(self):
        self.checker.update(personality_enabled=True, max_profiles=5)
        self.assertTrue(self.checker.permission.personality_enabled)
        self.assertEqual(self.checker.permission.max_profiles, 5)

    def test_update_ignores_unknown(self):
        self.checker.update(not_a_field=1)
        self.assertFalse(self.checker.permission.personality_enabled)

    def test_reset(self):
        self.checker.load(personality_enabled=True)
        self.checker.reset()
        allowed, _ = self.checker.check_enabled()
        self.assertFalse(allowed)

    def test_check_save_sensitive_blocked(self):
        self.checker.load(personality_enabled=True, allow_sensitive=False)
        profile = PersonalityProfile.create(
            name="测试",
            description="这是我的手机号 13800138000 和银行卡号 6222 0000",
        )
        allowed, reason = self.checker.check_save(profile)
        self.assertFalse(allowed)
        self.assertIn("敏感", reason)

    def test_check_save_clean_ok(self):
        self.checker.load(personality_enabled=True, allow_sensitive=False)
        profile = PersonalityProfile.create(name="测试", description="温暖友善")
        allowed, _ = self.checker.check_save(profile)
        self.assertTrue(allowed)

    def test_check_save_allow_sensitive(self):
        self.checker.load(personality_enabled=True, allow_sensitive=True)
        profile = PersonalityProfile.create(name="测试", description="密码 abc123")
        allowed, _ = self.checker.check_save(profile)
        self.assertTrue(allowed)

    def test_check_save_denied_when_disabled(self):
        profile = PersonalityProfile.create(name="测试")
        allowed, reason = self.checker.check_save(profile)
        self.assertFalse(allowed)
        self.assertIn("总开关", reason)

    def test_to_dict(self):
        self.checker.load(personality_enabled=True)
        d = self.checker.to_dict()
        self.assertTrue(d["personality_enabled"])


class TestSanitizeText(unittest.TestCase):

    def test_sanitize_chinese_sensitive(self):
        out = sanitize_text("我的手机号是 13800138000, 密码是 123456")
        self.assertIn("[已过滤]", out)
        self.assertNotIn("手机号", out)
        self.assertNotIn("密码", out)
        self.assertEqual(out.count("[已过滤]"), 2)

    def test_sanitize_english_sensitive(self):
        out = sanitize_text("token: abc123, api_key: xyz")
        self.assertIn("[已过滤]", out)
        self.assertNotIn("token", out)
        self.assertNotIn("api_key", out)
        self.assertEqual(out.count("[已过滤]"), 2)

    def test_sanitize_clean_text_unchanged(self):
        text = "温暖友善的回复"
        self.assertEqual(sanitize_text(text), text)

    def test_sanitize_empty(self):
        self.assertEqual(sanitize_text(""), "")
        self.assertIsNone(sanitize_text(None))


if __name__ == "__main__":
    unittest.main()
