"""
单元测试: permission.py - 权限校验
覆盖: PerceptionPermission 数据结构 / PermissionChecker 校验流程 / 默认拒绝 / 字段级更新
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.vision.perception.permission import (
    PermissionChecker,
    PerceptionPermission,
)
from backend.vision.perception.schema import (
    PerceptionRequest,
    PerceptionSource,
)


class TestPerceptionPermission(unittest.TestCase):

    def test_default_all_denied(self):
        perm = PerceptionPermission()
        self.assertFalse(perm.perception_enabled)
        self.assertFalse(perm.ocr_enabled)
        self.assertFalse(perm.detection_enabled)
        self.assertFalse(perm.allow_image_save)
        self.assertEqual(perm.save_policy, "memory")

    def test_to_dict(self):
        perm = PerceptionPermission(perception_enabled=True, ocr_enabled=True)
        d = perm.to_dict()
        self.assertTrue(d["perception_enabled"])
        self.assertTrue(d["ocr_enabled"])
        self.assertFalse(d["detection_enabled"])

    def test_from_dict(self):
        perm = PerceptionPermission.from_dict({
            "perception_enabled": True,
            "ocr_enabled": True,
            "min_confidence": 0.5,
        })
        self.assertTrue(perm.perception_enabled)
        self.assertTrue(perm.ocr_enabled)
        self.assertEqual(perm.min_confidence, 0.5)

    def test_roundtrip(self):
        p1 = PerceptionPermission(perception_enabled=True, ocr_enabled=True, min_confidence=0.3)
        d = p1.to_dict()
        p2 = PerceptionPermission.from_dict(d)
        self.assertEqual(p1, p2)


class TestPermissionChecker(unittest.TestCase):

    def setUp(self):
        self.checker = PermissionChecker()

    def test_default_all_denied(self):
        """默认拒绝: 总开关 / OCR / Detection 都为 False"""
        req = PerceptionRequest(source="ocr", image="fake")
        allowed, reason = self.checker.check(req)
        self.assertFalse(allowed)
        self.assertIn("总开关", reason)

    def test_mock_always_allowed(self):
        """Mock 来源始终允许 (即使总开关关)"""
        req = PerceptionRequest(source=PerceptionSource.MOCK.value, image="fake")
        allowed, _ = self.checker.check(req)
        # mock 需要 perception_enabled=True
        self.assertFalse(allowed)

    def test_mock_allowed_when_perception_on(self):
        """开启总开关后 Mock 允许"""
        self.checker.update(perception_enabled=True)
        req = PerceptionRequest(source=PerceptionSource.MOCK.value, image="fake")
        allowed, _ = self.checker.check(req)
        self.assertTrue(allowed)

    def test_ocr_requires_both_switches(self):
        """OCR 需要 perception_enabled + ocr_enabled"""
        self.checker.update(perception_enabled=True)
        req = PerceptionRequest(source="ocr", image="fake")
        allowed, reason = self.checker.check(req)
        self.assertFalse(allowed)
        self.assertIn("OCR", reason)

        self.checker.update(ocr_enabled=True)
        allowed, _ = self.checker.check(req)
        self.assertTrue(allowed)

    def test_detection_requires_both_switches(self):
        self.checker.update(perception_enabled=True, detection_enabled=True)
        req = PerceptionRequest(source="detection", image="fake")
        allowed, _ = self.checker.check(req)
        self.assertTrue(allowed)

    def test_combined_requires_one(self):
        """联合感知需要 OCR 或 Detection 至少一个"""
        self.checker.update(perception_enabled=True)
        req = PerceptionRequest(source="combined", image="fake")
        allowed, reason = self.checker.check(req)
        self.assertFalse(allowed)

        self.checker.update(ocr_enabled=True)
        allowed, _ = self.checker.check(req)
        self.assertTrue(allowed)

    def test_empty_image_rejected(self):
        """输入图像为空时拒绝"""
        self.checker.update(perception_enabled=True, ocr_enabled=True)
        req = PerceptionRequest(source="ocr", image=None)
        allowed, reason = self.checker.check(req)
        self.assertFalse(allowed)
        self.assertIn("图像", reason)

    def test_region_validation(self):
        """区域参数校验"""
        self.checker.update(perception_enabled=True, ocr_enabled=True)
        # 缺少参数
        req = PerceptionRequest(
            source="ocr", image="fake",
            region={"x": 0, "y": 0, "w": 100},  # 缺 h
        )
        allowed, reason = self.checker.check(req)
        self.assertFalse(allowed)
        self.assertIn("不完整", reason)
        # 尺寸非法
        req = PerceptionRequest(
            source="ocr", image="fake",
            region={"x": 0, "y": 0, "w": 0, "h": 100},
        )
        allowed, reason = self.checker.check(req)
        self.assertFalse(allowed)
        self.assertIn("非法", reason)

    def test_region_size_limit(self):
        """区域尺寸超限"""
        self.checker.update(perception_enabled=True, ocr_enabled=True, max_image_size=500)
        req = PerceptionRequest(
            source="ocr", image="fake",
            region={"x": 0, "y": 0, "w": 1000, "h": 100},  # w 超限
        )
        allowed, reason = self.checker.check(req)
        self.assertFalse(allowed)
        self.assertIn("超出限制", reason)

    def test_unknown_source_rejected(self):
        self.checker.update(perception_enabled=True)
        req = PerceptionRequest(source="unknown_source", image="fake")
        allowed, reason = self.checker.check(req)
        self.assertFalse(allowed)
        self.assertIn("未知", reason)

    def test_update_returns_new_permission(self):
        """update 返回新 Permission 对象"""
        perm = self.checker.update(perception_enabled=True)
        self.assertTrue(perm.perception_enabled)
        self.assertIsInstance(perm, PerceptionPermission)

    def test_reset(self):
        self.checker.update(perception_enabled=True, ocr_enabled=True)
        self.checker.reset()
        perm = self.checker.permission
        self.assertFalse(perm.perception_enabled)
        self.assertFalse(perm.ocr_enabled)

    def test_check_source(self):
        self.checker.update(perception_enabled=True, ocr_enabled=True)
        ok, _ = self.checker.check_source("ocr")
        self.assertTrue(ok)
        ok, _ = self.checker.check_source("detection")
        self.assertFalse(ok)
        ok, _ = self.checker.check_source("mock")
        self.assertTrue(ok)

    def test_load_from_dict(self):
        self.checker.load_from_dict({
            "perception_enabled": True,
            "ocr_enabled": True,
            "detection_enabled": False,
        })
        perm = self.checker.permission
        self.assertTrue(perm.perception_enabled)
        self.assertTrue(perm.ocr_enabled)
        self.assertFalse(perm.detection_enabled)

    def test_load_from_permission(self):
        p = PerceptionPermission(perception_enabled=True, detection_enabled=True)
        self.checker.load_from_permission(p)
        self.assertTrue(self.checker.permission.perception_enabled)
        self.assertTrue(self.checker.permission.detection_enabled)

    def test_to_dict(self):
        d = self.checker.to_dict()
        self.assertIn("perception_enabled", d)
        self.assertIn("ocr_enabled", d)


if __name__ == "__main__":
    unittest.main()
