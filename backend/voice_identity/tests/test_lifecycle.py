"""
YHLZ Voice Identity System V2.3-Phase4 - 声音生命周期测试

覆盖:
    - archive_voice / restore_voice / deactivate_voice 状态流转
    - cleanup_unused_voice 时间规则 (90d → inactive, 180d → archived)
    - 幂等性 (已归档/已就绪重复操作)
    - 终态保护 (deleted 不可归档/恢复)
    - 单例 get/reset
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


class _IsolatedDb:
    """测试 DB 隔离上下文"""

    def __enter__(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="yhlz_v23_lc_")
        self._db_path = os.path.join(self._tmp_dir, "test.db")
        self._old_env = os.environ.get("YHLZ_VOICE_IDENTITY_DB")
        os.environ["YHLZ_VOICE_IDENTITY_DB"] = self._db_path
        import importlib
        import backend.voice_identity.database as db_mod
        importlib.reload(db_mod)
        db_mod.reset_db_instance()
        try:
            from backend.voice_identity.voice_lifecycle import reset_lifecycle
            reset_lifecycle()
        except Exception:
            pass
        return self

    def __exit__(self, *args):
        import importlib
        import backend.voice_identity.database as db_mod
        try:
            from backend.voice_identity.voice_lifecycle import reset_lifecycle
            reset_lifecycle()
        except Exception:
            pass
        db_mod.reset_db_instance()
        if self._old_env is None:
            os.environ.pop("YHLZ_VOICE_IDENTITY_DB", None)
        else:
            os.environ["YHLZ_VOICE_IDENTITY_DB"] = self._old_env
        importlib.reload(db_mod)
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)


def _create_voice(svc, voice_id, name="test", status="ready", owner="system",
                  created_at=None):
    """直接在 DB 创建 profile (绕过 Service.create_voice 的状态流转)"""
    svc.db.insert_profile(__import__(
        "backend.voice_identity.models", fromlist=["VoiceProfile"]
    ).VoiceProfile(
        voice_id=voice_id, owner_id=owner, name=name,
        status=status, engine="qwen3", created_at=created_at,
    ))
    return svc.db.get_profile_by_id(voice_id)


def _set_last_used(svc, voice_id, days_ago):
    """设置 voice_usage.last_used 为 N 天前"""
    last = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S")
    with svc.db._lock:
        assert svc.db._conn is not None
        svc.db._conn.execute(
            "INSERT INTO voice_usage (voice_id, usage_count, last_used, duration) "
            "VALUES (?, 1, ?, 0.0) "
            "ON CONFLICT(voice_id) DO UPDATE SET last_used = excluded.last_used;",
            (voice_id, last),
        )


# ==================================================================
# archive / restore
# ==================================================================

class TestArchiveRestore(unittest.TestCase):

    def test_archive_ready_voice(self):
        """归档 ready 声音 → archived"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="ready")
            lc = VoiceLifecycle(svc=svc)
            r = lc.archive_voice("v1")
            self.assertTrue(r.success)
            self.assertEqual(r.old_status, "ready")
            self.assertEqual(r.new_status, "archived")
            self.assertEqual(svc.db.get_profile_by_id("v1").status, "archived")

    def test_archive_active_voice(self):
        """归档 active 声音 → archived"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="active")
            lc = VoiceLifecycle(svc=svc)
            r = lc.archive_voice("v1")
            self.assertTrue(r.success)
            self.assertEqual(svc.db.get_profile_by_id("v1").status, "archived")

    def test_archive_already_archived_idempotent(self):
        """已 archived 重复归档 → 幂等成功"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="archived")
            lc = VoiceLifecycle(svc=svc)
            r = lc.archive_voice("v1")
            self.assertTrue(r.success)
            self.assertEqual(r.new_status, "archived")

    def test_archive_deleted_fails(self):
        """deleted 声音不可归档"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="deleted")
            lc = VoiceLifecycle(svc=svc)
            r = lc.archive_voice("v1")
            self.assertFalse(r.success)
            self.assertIsNotNone(r.error)

    def test_archive_nonexistent_fails(self):
        """不存在声音归档失败"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            lc = VoiceLifecycle(svc=svc)
            r = lc.archive_voice("nonexistent")
            self.assertFalse(r.success)

    def test_restore_archived_voice(self):
        """恢复 archived → ready"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="archived")
            lc = VoiceLifecycle(svc=svc)
            r = lc.restore_voice("v1")
            self.assertTrue(r.success)
            self.assertEqual(r.old_status, "archived")
            self.assertEqual(r.new_status, "ready")
            self.assertEqual(svc.db.get_profile_by_id("v1").status, "ready")

    def test_restore_inactive_voice(self):
        """恢复 inactive → ready"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="inactive")
            lc = VoiceLifecycle(svc=svc)
            r = lc.restore_voice("v1")
            self.assertTrue(r.success)
            self.assertEqual(r.new_status, "ready")

    def test_restore_ready_idempotent(self):
        """ready 声音恢复 → 幂等"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="ready")
            lc = VoiceLifecycle(svc=svc)
            r = lc.restore_voice("v1")
            self.assertTrue(r.success)
            self.assertEqual(r.new_status, "ready")

    def test_restore_deleted_fails(self):
        """deleted 不可恢复"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="deleted")
            lc = VoiceLifecycle(svc=svc)
            r = lc.restore_voice("v1")
            self.assertFalse(r.success)


# ==================================================================
# deactivate
# ==================================================================

class TestDeactivate(unittest.TestCase):

    def test_deactivate_active(self):
        """active → inactive"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="active")
            lc = VoiceLifecycle(svc=svc)
            r = lc.deactivate_voice("v1")
            self.assertTrue(r.success)
            self.assertEqual(r.new_status, "inactive")

    def test_deactivate_already_inactive_idempotent(self):
        """inactive 重复停用 → 幂等"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="inactive")
            lc = VoiceLifecycle(svc=svc)
            r = lc.deactivate_voice("v1")
            self.assertTrue(r.success)
            self.assertEqual(r.new_status, "inactive")


# ==================================================================
# cleanup_unused_voice (时间规则)
# ==================================================================

class TestCleanupUnused(unittest.TestCase):

    def test_cleanup_90d_to_inactive(self):
        """90 天未使用 → inactive"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="ready")
            _set_last_used(svc, "v1", days_ago=100)  # 100 天前 (> 90)
            lc = VoiceLifecycle(svc=svc)
            report = lc.cleanup_unused_voice(inactive_days=90, archive_days=180)
            self.assertEqual(report.inactive_count, 1)
            self.assertEqual(report.archived_count, 0)
            self.assertEqual(svc.db.get_profile_by_id("v1").status, "inactive")

    def test_cleanup_180d_to_archived(self):
        """180 天未使用 → archived"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="ready")
            _set_last_used(svc, "v1", days_ago=200)  # 200 天前 (> 180)
            lc = VoiceLifecycle(svc=svc)
            report = lc.cleanup_unused_voice(inactive_days=90, archive_days=180)
            self.assertEqual(report.archived_count, 1)
            self.assertEqual(report.inactive_count, 0)
            self.assertEqual(svc.db.get_profile_by_id("v1").status, "archived")

    def test_cleanup_recent_voice_skipped(self):
        """近期使用声音 → 跳过"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="ready")
            _set_last_used(svc, "v1", days_ago=10)  # 10 天前 (< 90)
            lc = VoiceLifecycle(svc=svc)
            report = lc.cleanup_unused_voice(inactive_days=90, archive_days=180)
            self.assertEqual(report.skipped_count, 1)
            self.assertEqual(report.inactive_count, 0)
            self.assertEqual(report.archived_count, 0)
            self.assertEqual(svc.db.get_profile_by_id("v1").status, "ready")

    def test_cleanup_skips_archived(self):
        """已 archived 跳过"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="archived")
            _set_last_used(svc, "v1", days_ago=300)
            lc = VoiceLifecycle(svc=svc)
            report = lc.cleanup_unused_voice()
            self.assertEqual(report.skipped_count, 1)
            self.assertEqual(report.archived_count, 0)

    def test_cleanup_skips_deleted(self):
        """已 deleted 跳过"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="deleted")
            _set_last_used(svc, "v1", days_ago=300)
            lc = VoiceLifecycle(svc=svc)
            report = lc.cleanup_unused_voice()
            self.assertEqual(report.skipped_count, 1)

    def test_cleanup_mixed_batch(self):
        """混合批处理: 多个声音不同状态"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            # v1: 100 天前 → inactive
            _create_voice(svc, "v1", status="ready")
            _set_last_used(svc, "v1", days_ago=100)
            # v2: 200 天前 → archived
            _create_voice(svc, "v2", status="ready")
            _set_last_used(svc, "v2", days_ago=200)
            # v3: 10 天前 → skip
            _create_voice(svc, "v3", status="active")
            _set_last_used(svc, "v3", days_ago=10)
            lc = VoiceLifecycle(svc=svc)
            report = lc.cleanup_unused_voice(inactive_days=90, archive_days=180)
            self.assertEqual(report.inactive_count, 1)
            self.assertEqual(report.archived_count, 1)
            self.assertEqual(report.skipped_count, 1)
            self.assertEqual(report.total_processed, 3)

    def test_cleanup_uses_created_at_when_no_usage(self):
        """无使用记录时回退到 created_at"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            # created_at 由 DB 默认值设为 now, 这里直接改写为 100 天前
            _create_voice(svc, "v1", status="ready")
            old_created = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%dT%H:%M:%S")
            with svc.db._lock:
                assert svc.db._conn is not None
                svc.db._conn.execute(
                    "UPDATE voice_profiles SET created_at = ? WHERE voice_id = ?;",
                    (old_created, "v1"),
                )
            lc = VoiceLifecycle(svc=svc)
            report = lc.cleanup_unused_voice(inactive_days=90, archive_days=180)
            self.assertEqual(report.inactive_count, 1)


# ==================================================================
# 查询
# ==================================================================

class TestLifecycleQuery(unittest.TestCase):

    def test_list_archived(self):
        """列出归档声音"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="archived")
            _create_voice(svc, "v2", status="ready")
            lc = VoiceLifecycle(svc=svc)
            archived = lc.list_archived()
            self.assertEqual(len(archived), 1)
            self.assertEqual(archived[0].voice_id, "v1")

    def test_list_inactive(self):
        """列出停用声音"""
        with _IsolatedDb():
            from backend.voice_identity.service import VoiceIdentityService
            from backend.voice_identity.voice_lifecycle import VoiceLifecycle
            svc = VoiceIdentityService()
            _create_voice(svc, "v1", status="inactive")
            _create_voice(svc, "v2", status="ready")
            lc = VoiceLifecycle(svc=svc)
            inactive = lc.list_inactive()
            self.assertEqual(len(inactive), 1)
            self.assertEqual(inactive[0].voice_id, "v1")


# ==================================================================
# 单例
# ==================================================================

class TestLifecycleSingleton(unittest.TestCase):

    def test_get_reset(self):
        with _IsolatedDb():
            from backend.voice_identity.voice_lifecycle import (
                get_lifecycle, reset_lifecycle,
            )
            l1 = get_lifecycle()
            l2 = get_lifecycle()
            self.assertIs(l1, l2)
            reset_lifecycle()
            l3 = get_lifecycle()
            self.assertIsNot(l1, l3)


# ==================================================================
# 数据模型
# ==================================================================

class TestLifecycleModels(unittest.TestCase):

    def test_lifecycle_result_to_dict(self):
        from backend.voice_identity.voice_lifecycle import LifecycleResult
        r = LifecycleResult("v1", True, "ready", "archived")
        d = r.to_dict()
        self.assertEqual(d["voice_id"], "v1")
        self.assertTrue(d["success"])
        self.assertEqual(d["old_status"], "ready")
        self.assertEqual(d["new_status"], "archived")

    def test_cleanup_report_total_processed(self):
        from backend.voice_identity.voice_lifecycle import CleanupReport
        r = CleanupReport(inactive_count=2, archived_count=1, skipped_count=3)
        self.assertEqual(r.total_processed, 6)

    def test_cleanup_report_to_dict(self):
        from backend.voice_identity.voice_lifecycle import CleanupReport
        r = CleanupReport(inactive_count=1, archived_count=1)
        d = r.to_dict()
        self.assertEqual(d["inactive_count"], 1)
        self.assertEqual(d["archived_count"], 1)
        self.assertEqual(d["total_processed"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
