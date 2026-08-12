"""
YHLZ Vision Memory V1.0 - 权限单元测试

覆盖:
    - MemoryPermission 默认拒绝 / 序列化
    - PermissionChecker: check_enabled / check_save / update / load / reset
    - 禁止保存原始图像
"""
import unittest

from backend.vision.memory.permission import MemoryPermission, PermissionChecker


class TestMemoryPermission(unittest.TestCase):

    def test_default_denied(self):
        perm = MemoryPermission()
        self.assertFalse(perm.vision_memory_enabled)
        self.assertFalse(perm.allow_raw_image_save)
        self.assertEqual(perm.default_importance, "medium")
        self.assertEqual(perm.max_query_limit, 100)

    def test_to_dict(self):
        perm = MemoryPermission(
            vision_memory_enabled=True,
            allow_raw_image_save=True,
            default_importance="high",
            max_query_limit=50,
        )
        d = perm.to_dict()
        self.assertTrue(d["vision_memory_enabled"])
        self.assertTrue(d["allow_raw_image_save"])
        self.assertEqual(d["default_importance"], "high")
        self.assertEqual(d["max_query_limit"], 50)

    def test_from_dict(self):
        d = {
            "vision_memory_enabled": True,
            "allow_raw_image_save": False,
            "default_importance": "low",
            "max_query_limit": 10,
        }
        perm = MemoryPermission.from_dict(d)
        self.assertTrue(perm.vision_memory_enabled)
        self.assertEqual(perm.default_importance, "low")
        self.assertEqual(perm.max_query_limit, 10)

    def test_from_dict_defaults(self):
        perm = MemoryPermission.from_dict({})
        self.assertFalse(perm.vision_memory_enabled)


class TestPermissionChecker(unittest.TestCase):

    def setUp(self):
        self.checker = PermissionChecker()

    def test_default_check_enabled_denied(self):
        allowed, reason = self.checker.check_enabled()
        self.assertFalse(allowed)
        self.assertIn("vision_memory_enabled", reason)

    def test_check_enabled_after_load(self):
        self.checker.load(vision_memory_enabled=True)
        allowed, _ = self.checker.check_enabled()
        self.assertTrue(allowed)

    def test_check_save_denied_by_default(self):
        allowed, reason = self.checker.check_save()
        self.assertFalse(allowed)
        self.assertIn("vision_memory_enabled", reason)

    def test_check_save_ok(self):
        self.checker.load(vision_memory_enabled=True)
        allowed, _ = self.checker.check_save()
        self.assertTrue(allowed)

    def test_check_save_reject_raw_image(self):
        self.checker.load(vision_memory_enabled=True)
        class FakeRecord:
            metadata = {"image": b"raw"}
        allowed, reason = self.checker.check_save(FakeRecord())
        self.assertFalse(allowed)
        self.assertIn("原始图像", reason)

    def test_check_save_reject_raw_image_key2(self):
        self.checker.load(vision_memory_enabled=True)
        class FakeRecord:
            metadata = {"raw_image": b"raw"}
        allowed, _ = self.checker.check_save(FakeRecord())
        self.assertFalse(allowed)

    def test_check_save_allow_metadata(self):
        self.checker.load(vision_memory_enabled=True)
        class FakeRecord:
            metadata = {"result_id": "abc", "summary": "摘要"}
        allowed, _ = self.checker.check_save(FakeRecord())
        self.assertTrue(allowed)

    def test_load_from_permission(self):
        perm = MemoryPermission(vision_memory_enabled=True)
        self.checker.load_from_permission(perm)
        allowed, _ = self.checker.check_enabled()
        self.assertTrue(allowed)

    def test_update(self):
        perm = self.checker.update(vision_memory_enabled=True, max_query_limit=50)
        self.assertTrue(perm.vision_memory_enabled)
        self.assertEqual(perm.max_query_limit, 50)

    def test_update_ignores_invalid(self):
        self.checker.update(unknown_field=123, none_field=None)
        d = self.checker.to_dict()
        self.assertNotIn("unknown_field", d)

    def test_reset(self):
        self.checker.load(vision_memory_enabled=True)
        self.checker.reset()
        allowed, _ = self.checker.check_enabled()
        self.assertFalse(allowed)

    def test_permission_property(self):
        self.checker.load(vision_memory_enabled=True)
        self.assertTrue(self.checker.permission.vision_memory_enabled)

    def test_to_dict(self):
        self.checker.load(vision_memory_enabled=True)
        d = self.checker.to_dict()
        self.assertTrue(d["vision_memory_enabled"])


if __name__ == "__main__":
    unittest.main()
