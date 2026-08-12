"""
YHLZ Voice Identity System V2.3-Phase3 - 权限系统测试

覆盖:
    - get_actor_id: 请求头提取
    - PermissionChecker.check_create: clone/batch 创建类权限 (拒绝 anonymous/guest/空)
    - PermissionChecker.check_voice_action: 既有声音 read/write/delete/synthesize
    - 403/404 异常语义
    - 单例 get/reset

设计:
    - 单元测试为主 (不启动 FastAPI 服务, 避免 Qwen3 模型加载)
    - 使用 Mock Service 替代 VoiceIdentityService
    - API 层 403 路径在 Phase 6 MockModelLoader 就绪后补充端到端测试
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


class _MockRequest:
    """模拟 FastAPI Request (仅含 headers)"""

    def __init__(self, headers: dict | None = None):
        self.headers = headers or {}


class _MockService:
    """模拟 VoiceIdentityService (仅 get_voice)"""

    def __init__(self, profile=None):
        self._profile = profile
        self.get_voice = MagicMock(return_value=profile)


def _make_profile(owner_id="user_123", voice_id="v1"):
    """构造测试 Profile"""
    from backend.voice_identity.models import VoiceProfile
    return VoiceProfile(voice_id=voice_id, owner_id=owner_id, name="test")


# ==================================================================
# get_actor_id
# ==================================================================

class TestGetActorId(unittest.TestCase):
    """actor_id 提取"""

    def test_no_header_returns_system(self):
        """无请求头 → system"""
        from backend.voice_identity.permission import get_actor_id
        self.assertEqual(get_actor_id(_MockRequest()), "system")

    def test_header_present(self):
        """有 X-Actor-ID 头 → 使用该值"""
        from backend.voice_identity.permission import get_actor_id
        req = _MockRequest({"X-Actor-ID": "user_abc"})
        self.assertEqual(get_actor_id(req), "user_abc")

    def test_header_empty_falls_back(self):
        """空头 → system"""
        from backend.voice_identity.permission import get_actor_id
        req = _MockRequest({"X-Actor-ID": ""})
        self.assertEqual(get_actor_id(req), "system")

    def test_header_whitespace_stripped(self):
        """头值去空白"""
        from backend.voice_identity.permission import get_actor_id
        req = _MockRequest({"X-Actor-ID": "  user_xyz  "})
        self.assertEqual(get_actor_id(req), "user_xyz")

    def test_no_request_returns_system(self):
        """request=None → system"""
        from backend.voice_identity.permission import get_actor_id
        self.assertEqual(get_actor_id(None), "system")

    def test_custom_header_name(self):
        """自定义头名称"""
        from backend.voice_identity.permission import get_actor_id
        req = _MockRequest({"X-User": "alice"})
        self.assertEqual(get_actor_id(req, header_name="X-User"), "alice")


# ==================================================================
# PermissionChecker.check_create (clone / batch)
# ==================================================================

class TestCheckCreate(unittest.TestCase):
    """创建类权限 (clone / batch / quality)"""

    def setUp(self):
        from backend.voice_identity.permission import PermissionChecker
        self.checker = PermissionChecker()

    def test_system_allowed(self):
        """system 允许创建"""
        self.assertEqual(self.checker.check_create("system"), "system")

    def test_normal_user_allowed(self):
        """普通用户允许创建"""
        self.assertEqual(self.checker.check_create("user_123"), "user_123")

    def test_anonymous_denied_403(self):
        """anonymous 拒绝 → 403"""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self.checker.check_create("anonymous")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_guest_denied_403(self):
        """guest 拒绝 → 403"""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self.checker.check_create("guest")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_empty_denied_403(self):
        """空字符串拒绝 → 403"""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.checker.check_create("")

    def test_403_detail_contains_permission_denied(self):
        """403 detail 含 'permission denied'"""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self.checker.check_create("anonymous")
        self.assertIn("permission denied", ctx.exception.detail)


# ==================================================================
# PermissionChecker.check_voice_action (既有声音)
# ==================================================================

class TestCheckVoiceAction(unittest.TestCase):
    """既有声音权限校验"""

    def setUp(self):
        from backend.voice_identity.permission import PermissionChecker
        self.checker = PermissionChecker()
        self.profile = _make_profile(owner_id="user_123", voice_id="v1")

    def test_voice_not_found_404(self):
        """声音不存在 → 404"""
        from fastapi import HTTPException
        svc = _MockService(profile=None)
        with self.assertRaises(HTTPException) as ctx:
            self.checker.check_delete(svc, "nonexistent", "system")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_owner_can_delete(self):
        """owner 可删除"""
        svc = _MockService(profile=self.profile)
        self.assertTrue(self.checker.check_delete(svc, "v1", "user_123"))

    def test_system_can_delete(self):
        """system 可删除"""
        svc = _MockService(profile=self.profile)
        self.assertTrue(self.checker.check_delete(svc, "v1", "system"))

    def test_non_owner_cannot_delete_403(self):
        """非 owner 不可删除 → 403"""
        from fastapi import HTTPException
        svc = _MockService(profile=self.profile)
        with self.assertRaises(HTTPException) as ctx:
            self.checker.check_delete(svc, "v1", "user_other")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_non_owner_can_read(self):
        """非 owner 可读"""
        svc = _MockService(profile=self.profile)
        self.assertTrue(self.checker.check_read(svc, "v1", "user_other"))

    def test_non_owner_can_synthesize(self):
        """非 owner 可合成"""
        svc = _MockService(profile=self.profile)
        self.assertTrue(self.checker.check_synthesize(svc, "v1", "user_other"))

    def test_non_owner_cannot_write_403(self):
        """非 owner 不可写 → 403"""
        from fastapi import HTTPException
        svc = _MockService(profile=self.profile)
        with self.assertRaises(HTTPException) as ctx:
            self.checker.check_write(svc, "v1", "user_other")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_403_detail_contains_voice_id(self):
        """403 detail 含 voice_id"""
        from fastapi import HTTPException
        svc = _MockService(profile=self.profile)
        with self.assertRaises(HTTPException) as ctx:
            self.checker.check_delete(svc, "v1", "user_other")
        self.assertIn("v1", ctx.exception.detail)


# ==================================================================
# 单例
# ==================================================================

class TestPermissionSingleton(unittest.TestCase):

    def test_get_reset(self):
        from backend.voice_identity.permission import (
            get_permission_checker, reset_permission_checker,
        )
        c1 = get_permission_checker()
        c2 = get_permission_checker()
        self.assertIs(c1, c2)
        reset_permission_checker()
        c3 = get_permission_checker()
        self.assertIsNot(c1, c3)


# ==================================================================
# 集成: 4 个 API 端点权限语义 (通过 PermissionChecker 模拟)
# ==================================================================

class TestApiPermissionSemantics(unittest.TestCase):
    """模拟 4 个 API 端点的权限语义 (不启动服务)

    覆盖:
        POST /voice/clone            → check_create (拒绝 anonymous)
        DELETE /voice/{id}           → check_delete (须 owner/system)
        POST /voice/clone/batch      → check_create (拒绝 anonymous)
        POST /voice/quality/evaluate → check_create (拒绝 anonymous)
    """

    def setUp(self):
        from backend.voice_identity.permission import PermissionChecker
        self.checker = PermissionChecker()
        self.profile = _make_profile(owner_id="user_123", voice_id="v1")

    def test_clone_anonymous_denied(self):
        """clone: anonymous → 403"""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self.checker.check_create("anonymous")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_clone_normal_user_allowed(self):
        """clone: 普通用户 → 允许"""
        self.checker.check_create("user_456")

    def test_delete_non_owner_denied(self):
        """delete: 非 owner → 403"""
        from fastapi import HTTPException
        svc = _MockService(profile=self.profile)
        with self.assertRaises(HTTPException) as ctx:
            self.checker.check_delete(svc, "v1", "user_other")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_delete_owner_allowed(self):
        """delete: owner → 允许"""
        svc = _MockService(profile=self.profile)
        self.checker.check_delete(svc, "v1", "user_123")

    def test_batch_anonymous_denied(self):
        """batch: anonymous → 403"""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self.checker.check_create("anonymous")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_batch_normal_user_allowed(self):
        """batch: 普通用户 → 允许"""
        self.checker.check_create("user_789")

    def test_quality_anonymous_denied(self):
        """quality: anonymous → 403"""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self.checker.check_create("anonymous")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_quality_normal_user_allowed(self):
        """quality: 普通用户 → 允许"""
        self.checker.check_create("user_qaq")


if __name__ == "__main__":
    unittest.main(verbosity=2)
