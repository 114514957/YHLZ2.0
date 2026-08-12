"""
单元测试: permission.py - 理解权限控制
覆盖: 默认拒绝 / 显式开启 / 字段级更新 / 重置 / 空图校验
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.understanding.permission import (
    PermissionChecker,
    UnderstandingPermission,
)
from backend.vision.understanding.schema import UnderstandingRequest


class TestUnderstandingPermission(unittest.TestCase):

    def test_defaults_all_denied(self):
        """默认全部拒绝"""
        perm = UnderstandingPermission()
        self.assertFalse(perm.understanding_enabled)
        self.assertFalse(perm.allow_image_save)

    def test_to_dict(self):
        perm = UnderstandingPermission(understanding_enabled=True, max_image_size=1280)
        d = perm.to_dict()
        self.assertTrue(d["understanding_enabled"])
        self.assertEqual(d["max_image_size"], 1280)

    def test_from_dict(self):
        d = {"understanding_enabled": True, "allow_image_save": True, "max_image_size": 640, "save_policy": "memory"}
        perm = UnderstandingPermission.from_dict(d)
        self.assertTrue(perm.understanding_enabled)
        self.assertTrue(perm.allow_image_save)
        self.assertEqual(perm.max_image_size, 640)

    def test_from_dict_defaults(self):
        perm = UnderstandingPermission.from_dict({})
        self.assertFalse(perm.understanding_enabled)


class TestPermissionChecker(unittest.TestCase):

    def setUp(self):
        self.image = np.zeros((100, 100, 3), dtype=np.uint8)

    def test_check_denied_by_default(self):
        """默认拒绝: 总开关关闭"""
        checker = PermissionChecker()
        allowed, reason = checker.check(UnderstandingRequest(image=self.image))
        self.assertFalse(allowed)
        self.assertIn("understanding_enabled", reason)

    def test_check_allowed_when_enabled(self):
        checker = PermissionChecker()
        checker.load(understanding_enabled=True)
        allowed, reason = checker.check(UnderstandingRequest(image=self.image))
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_check_empty_image(self):
        """空图像拒绝"""
        checker = PermissionChecker()
        checker.load(understanding_enabled=True)
        allowed, reason = checker.check(UnderstandingRequest(image=None))
        self.assertFalse(allowed)
        self.assertIn("图像为空", reason)

    def test_check_does_not_raise(self):
        """权限校验不抛异常"""
        checker = PermissionChecker()
        allowed, _ = checker.check(UnderstandingRequest(image=None))
        self.assertFalse(allowed)

    def test_update_permission(self):
        checker = PermissionChecker()
        perm = checker.update(understanding_enabled=True, allow_image_save=True)
        self.assertTrue(perm.understanding_enabled)
        self.assertTrue(perm.allow_image_save)
        allowed, _ = checker.check(UnderstandingRequest(image=self.image))
        self.assertTrue(allowed)

    def test_update_ignores_none_and_unknown(self):
        checker = PermissionChecker()
        perm = checker.update(understanding_enabled=True, unknown_field=123, none_field=None)
        self.assertTrue(perm.understanding_enabled)
        self.assertFalse(hasattr(perm, "unknown_field"))

    def test_reset_to_default(self):
        checker = PermissionChecker()
        checker.load(understanding_enabled=True)
        checker.reset()
        allowed, _ = checker.check(UnderstandingRequest(image=self.image))
        self.assertFalse(allowed)

    def test_load_from_permission(self):
        checker = PermissionChecker()
        perm = UnderstandingPermission(understanding_enabled=True)
        checker.load_from_permission(perm)
        allowed, _ = checker.check(UnderstandingRequest(image=self.image))
        self.assertTrue(allowed)

    def test_to_dict(self):
        checker = PermissionChecker()
        checker.load(understanding_enabled=True)
        d = checker.to_dict()
        self.assertTrue(d["understanding_enabled"])

    def test_load_with_kwargs(self):
        checker = PermissionChecker()
        checker.load(understanding_enabled=True, max_image_size=800)
        self.assertEqual(checker.permission.max_image_size, 800)


if __name__ == "__main__":
    unittest.main()
