"""
YHLZ Voice Identity System - Phase 3 平台化能力测试

覆盖:
    Phase 3.1 批量克隆: TaskQueue submit/get/list/cancel, 任务状态流转
    Phase 3.2 声音去重: compute_audio_hash, compute_feature_similarity, check_duplicate
    Phase 3.3 安全审计: AuditLogger log/query/count, VoicePermission can/check
"""
from __future__ import annotations

import io
import math
import os
import struct
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


def _make_wav_bytes(duration_s: float = 5.0, sr: int = 16000) -> bytes:
    buf = io.BytesIO()
    n = int(duration_s * sr)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sr))
            frames.extend(struct.pack("<h", v))
        w.writeframes(bytes(frames))
    return buf.getvalue()


def _make_wav_file(path: str, duration_s: float = 5.0, sr: int = 16000) -> str:
    with open(path, "wb") as f:
        f.write(_make_wav_bytes(duration_s, sr))
    return path


class _IsolatedDb:
    """测试 DB 隔离上下文管理器"""

    def __enter__(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="yhlz_phase3_")
        self._db_path = os.path.join(self._tmp_dir, "test.db")
        self._old_env = os.environ.get("YHLZ_VOICE_IDENTITY_DB")
        os.environ["YHLZ_VOICE_IDENTITY_DB"] = self._db_path
        # 重载 database 模块以应用环境变量
        import importlib
        import backend.voice_identity.database as db_mod
        importlib.reload(db_mod)
        db_mod.reset_db_instance()
        return self

    def __exit__(self, *args):
        import importlib
        import backend.voice_identity.database as db_mod
        db_mod.reset_db_instance()
        if self._old_env is None:
            os.environ.pop("YHLZ_VOICE_IDENTITY_DB", None)
        else:
            os.environ["YHLZ_VOICE_IDENTITY_DB"] = self._old_env
        importlib.reload(db_mod)
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)


# ==================================================================
# Phase 3.1 批量克隆任务系统
# ==================================================================

class TestBatchTaskModels(unittest.TestCase):
    """任务数据模型测试"""

    def test_task_status_enum(self):
        from backend.voice_identity.batch.task_models import TaskStatus
        self.assertEqual(TaskStatus.PENDING.value, "pending")
        self.assertEqual(TaskStatus.COMPLETED.value, "completed")
        self.assertEqual(TaskStatus.PARTIAL.value, "partial")
        self.assertEqual(TaskStatus.FAILED.value, "failed")

    def test_clone_task_compute_status_completed(self):
        """全部成功 → completed"""
        from backend.voice_identity.batch.task_models import CloneTask, TaskItem, TaskStatus
        task = CloneTask(
            task_id="test1",
            items=[
                TaskItem(audio_path="a.wav", name="A", status="success"),
                TaskItem(audio_path="b.wav", name="B", status="success"),
            ],
        )
        self.assertEqual(task.compute_status(), TaskStatus.COMPLETED)
        self.assertEqual(task.success_count, 2)
        self.assertEqual(task.failed_count, 0)

    def test_clone_task_compute_status_partial(self):
        """部分成功 → partial"""
        from backend.voice_identity.batch.task_models import CloneTask, TaskItem, TaskStatus
        task = CloneTask(
            task_id="test2",
            items=[
                TaskItem(audio_path="a.wav", name="A", status="success"),
                TaskItem(audio_path="b.wav", name="B", status="failed", error="不存在"),
            ],
        )
        self.assertEqual(task.compute_status(), TaskStatus.PARTIAL)
        self.assertEqual(task.success_count, 1)
        self.assertEqual(task.failed_count, 1)

    def test_clone_task_compute_status_failed(self):
        """全部失败 → failed"""
        from backend.voice_identity.batch.task_models import CloneTask, TaskItem, TaskStatus
        task = CloneTask(
            task_id="test3",
            items=[
                TaskItem(audio_path="a.wav", name="A", status="failed", error="x"),
                TaskItem(audio_path="b.wav", name="B", status="failed", error="y"),
            ],
        )
        self.assertEqual(task.compute_status(), TaskStatus.FAILED)
        self.assertEqual(task.failed_count, 2)

    def test_task_to_dict(self):
        from backend.voice_identity.batch.task_models import CloneTask, TaskItem
        task = CloneTask(task_id="t4", items=[TaskItem(audio_path="a", name="A")])
        d = task.to_dict()
        self.assertEqual(d["task_id"], "t4")
        self.assertEqual(d["total"], 1)
        self.assertIn("items", d)
        self.assertEqual(len(d["items"]), 1)


class TestTaskQueue(unittest.TestCase):
    """TaskQueue 测试"""

    def test_submit_empty_items_raises(self):
        """提交空 items 应抛异常"""
        from backend.voice_identity.batch import TaskQueue, BatchTaskError
        q = TaskQueue(max_workers=1)
        q.start()
        try:
            with self.assertRaises(BatchTaskError):
                q.submit([])
        finally:
            q.shutdown(wait=False)

    def test_submit_missing_audio_path_raises(self):
        """缺少 audio_path 应抛异常"""
        from backend.voice_identity.batch import TaskQueue, BatchTaskError
        q = TaskQueue(max_workers=1)
        q.start()
        try:
            with self.assertRaises(BatchTaskError):
                q.submit([{"name": "A"}])  # 缺 audio_path
        finally:
            q.shutdown(wait=False)

    def test_submit_missing_name_raises(self):
        """缺少 name 应抛异常"""
        from backend.voice_identity.batch import TaskQueue, BatchTaskError
        q = TaskQueue(max_workers=1)
        q.start()
        try:
            with self.assertRaises(BatchTaskError):
                q.submit([{"audio_path": "a.wav"}])  # 缺 name
        finally:
            q.shutdown(wait=False)

    def test_submit_not_started_raises(self):
        """未启动的队列提交应抛异常"""
        from backend.voice_identity.batch import TaskQueue, BatchTaskError
        q = TaskQueue(max_workers=1)
        # 未调用 start()
        with self.assertRaises(BatchTaskError):
            q.submit([{"audio_path": "a.wav", "name": "A"}])

    def test_submit_and_get_task(self):
        """提交后可查询到任务"""
        from backend.voice_identity.batch import TaskQueue
        q = TaskQueue(max_workers=1)
        q.start()
        try:
            task = q.submit([
                {"audio_path": "/nonexistent/a.wav", "name": "A"},
            ])
            self.assertIsNotNone(task.task_id)
            self.assertEqual(task.total, 1)
            # 查询
            got = q.get_task(task.task_id)
            self.assertIsNotNone(got)
            self.assertEqual(got.task_id, task.task_id)
        finally:
            q.shutdown(wait=False)

    def test_list_tasks(self):
        """列出任务"""
        from backend.voice_identity.batch import TaskQueue
        q = TaskQueue(max_workers=1)
        q.start()
        try:
            q.submit([{"audio_path": "/nonexistent/a.wav", "name": "A"}])
            q.submit([{"audio_path": "/nonexistent/b.wav", "name": "B"}])
            time.sleep(0.1)  # 等提交完成
            lst = q.list_tasks()
            self.assertGreaterEqual(len(lst), 2)
        finally:
            q.shutdown(wait=False)

    def test_cancel_nonexistent(self):
        """取消不存在的任务返回 False"""
        from backend.voice_identity.batch import TaskQueue
        q = TaskQueue(max_workers=1)
        q.start()
        try:
            self.assertFalse(q.cancel("nonexistent_task_id"))
        finally:
            q.shutdown(wait=False)

    def test_get_nonexistent_task(self):
        """查询不存在的任务返回 None"""
        from backend.voice_identity.batch import TaskQueue
        q = TaskQueue(max_workers=1)
        q.start()
        try:
            self.assertIsNone(q.get_task("nonexistent"))
        finally:
            q.shutdown(wait=False)

    def test_task_execution_with_nonexistent_audio(self):
        """任务项执行: 音频不存在应标记 failed (集成测试, 需加载后端)"""
        from backend.voice_identity.batch import TaskQueue
        q = TaskQueue(max_workers=1)
        q.start()
        try:
            task = q.submit([
                {"audio_path": "/nonexistent/audio.wav", "name": "Test"},
            ])
            # 等待 worker 执行 (后端加载可能较慢, 最多等 120s)
            for _ in range(120):
                time.sleep(1.0)
                got = q.get_task(task.task_id)
                if got and got.ended_at is not None:
                    break
            got = q.get_task(task.task_id)
            self.assertIsNotNone(got)
            self.assertIn(got.status.value, ("failed", "partial"))
            self.assertEqual(got.failed_count, 1)
        finally:
            q.shutdown(wait=False)

    def test_reset_task_queue(self):
        """reset_task_queue 重置单例"""
        from backend.voice_identity.batch import reset_task_queue, get_task_queue
        q1 = get_task_queue()
        reset_task_queue()
        q2 = get_task_queue()
        self.assertIsNot(q1, q2)
        reset_task_queue()


# ==================================================================
# Phase 3.2 声音去重系统
# ==================================================================

class TestAudioHash(unittest.TestCase):
    """音频哈希测试"""

    def test_same_content_same_hash(self):
        """相同内容 → 相同哈希"""
        from backend.voice_identity.dedup import compute_audio_hash
        tmp_dir = tempfile.mkdtemp()
        try:
            p1 = os.path.join(tmp_dir, "a.wav")
            p2 = os.path.join(tmp_dir, "b.wav")
            _make_wav_file(p1, 3.0)
            _make_wav_file(p2, 3.0)  # 同参数生成相同内容
            h1 = compute_audio_hash(p1)
            h2 = compute_audio_hash(p2)
            self.assertIsNotNone(h1)
            self.assertIsNotNone(h2)
            self.assertEqual(h1, h2)
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_different_content_different_hash(self):
        """不同内容 → 不同哈希"""
        from backend.voice_identity.dedup import compute_audio_hash
        tmp_dir = tempfile.mkdtemp()
        try:
            p1 = os.path.join(tmp_dir, "a.wav")
            p2 = os.path.join(tmp_dir, "b.wav")
            # 写入不同内容
            with open(p1, "wb") as f:
                f.write(b"content_a" * 100)
            with open(p2, "wb") as f:
                f.write(b"content_b" * 100)
            h1 = compute_audio_hash(p1)
            h2 = compute_audio_hash(p2)
            self.assertNotEqual(h1, h2)
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_nonexistent_file_returns_none(self):
        """不存在的文件 → None"""
        from backend.voice_identity.dedup import compute_audio_hash
        self.assertIsNone(compute_audio_hash("/nonexistent/file.wav"))


class TestFeatureSimilarity(unittest.TestCase):
    """特征相似度测试"""

    def _make_feature(self, f0=200.0, energy=0.3, rate=4.0, snr=20.0):
        from backend.voice_identity.clone.audio_validator import AudioInfo
        from backend.voice_identity.clone.voice_analyzer import VoiceFeature
        return VoiceFeature(
            audio_info=AudioInfo(path="x", sample_rate=16000, duration_s=5.0, channels=1, frames=80000, format="wav"),
            mean_f0=f0, f0_range=(100, 300), mean_energy=energy,
            speech_rate=rate, snr_db=snr,
        )

    def test_identical_features_similarity_1(self):
        """完全相同特征 → 相似度 1.0"""
        from backend.voice_identity.dedup import compute_feature_similarity
        f = self._make_feature()
        sim = compute_feature_similarity(f, f)
        self.assertGreaterEqual(sim, 0.99)

    def test_different_features_low_similarity(self):
        """差异大的特征 → 低相似度"""
        from backend.voice_identity.dedup import compute_feature_similarity
        f1 = self._make_feature(f0=100, energy=0.1, rate=2.0, snr=5.0)
        f2 = self._make_feature(f0=400, energy=0.9, rate=8.0, snr=40.0)
        sim = compute_feature_similarity(f1, f2)
        self.assertLess(sim, 0.5)

    def test_no_comparable_fields_returns_zero(self):
        """无可比字段 → 0.0"""
        from backend.voice_identity.clone.audio_validator import AudioInfo
        from backend.voice_identity.clone.voice_analyzer import VoiceFeature
        from backend.voice_identity.dedup import compute_feature_similarity
        ai = AudioInfo(path="x", sample_rate=16000, duration_s=5.0, channels=1, frames=80000, format="wav")
        f1 = VoiceFeature(audio_info=ai)
        f2 = VoiceFeature(audio_info=ai)
        sim = compute_feature_similarity(f1, f2)
        self.assertEqual(sim, 0.0)

    def test_partial_fields_still_computes(self):
        """部分字段缺失仍能计算"""
        from backend.voice_identity.dedup import compute_feature_similarity
        f1 = self._make_feature(f0=200, energy=None, rate=None, snr=None)
        f2 = self._make_feature(f0=200, energy=None, rate=None, snr=None)
        sim = compute_feature_similarity(f1, f2)
        self.assertGreaterEqual(sim, 0.99)


class TestVoiceDeduplicator(unittest.TestCase):
    """VoiceDeduplicator 测试"""

    def test_check_duplicate_no_existing(self):
        """无已有声音 → 不重复"""
        with _IsolatedDb():
            from backend.voice_identity.dedup import VoiceDeduplicator
            from backend.voice_identity.service import VoiceIdentityService
            svc = VoiceIdentityService()
            dedup = VoiceDeduplicator(svc)
            tmp_dir = tempfile.mkdtemp()
            try:
                p = _make_wav_file(os.path.join(tmp_dir, "a.wav"), 3.0)
                result = dedup.check_duplicate(p)
                self.assertFalse(result.is_duplicate)
                self.assertEqual(result.match_type, "none")
                self.assertIsNotNone(result.audio_hash)
            finally:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_check_duplicate_hash_match(self):
        """同音频哈希 → 重复"""
        with _IsolatedDb():
            from backend.voice_identity.dedup import VoiceDeduplicator
            from backend.voice_identity.service import VoiceIdentityService
            svc = VoiceIdentityService()
            dedup = VoiceDeduplicator(svc)
            tmp_dir = tempfile.mkdtemp()
            try:
                p1 = _make_wav_file(os.path.join(tmp_dir, "a.wav"), 3.0)
                p2 = _make_wav_file(os.path.join(tmp_dir, "b.wav"), 3.0)  # 同内容
                # 先创建一个声音
                svc.create_voice(name="A", reference_audio=p1, engine="qwen3")
                # 检测 p2 (同内容)
                result = dedup.check_duplicate(p2)
                self.assertTrue(result.is_duplicate)
                self.assertEqual(result.match_type, "hash")
                self.assertEqual(result.confidence, 1.0)
            finally:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_check_duplicate_different_audio(self):
        """不同音频 → 不重复"""
        with _IsolatedDb():
            from backend.voice_identity.dedup import VoiceDeduplicator
            from backend.voice_identity.service import VoiceIdentityService
            svc = VoiceIdentityService()
            dedup = VoiceDeduplicator(svc)
            tmp_dir = tempfile.mkdtemp()
            try:
                p1 = _make_wav_file(os.path.join(tmp_dir, "a.wav"), 3.0, sr=16000)
                p2 = os.path.join(tmp_dir, "b.wav")
                with open(p2, "wb") as f:
                    f.write(b"different_content" * 1000)
                svc.create_voice(name="A", reference_audio=p1, engine="qwen3")
                result = dedup.check_duplicate(p2)
                self.assertFalse(result.is_duplicate)
            finally:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_check_duplicate_skip_self(self):
        """skip_voice_ids 跳过自身"""
        with _IsolatedDb():
            from backend.voice_identity.dedup import VoiceDeduplicator
            from backend.voice_identity.service import VoiceIdentityService
            svc = VoiceIdentityService()
            dedup = VoiceDeduplicator(svc)
            tmp_dir = tempfile.mkdtemp()
            try:
                p = _make_wav_file(os.path.join(tmp_dir, "a.wav"), 3.0)
                profile = svc.create_voice(name="A", reference_audio=p, engine="qwen3")
                # 跳过自身
                result = dedup.check_duplicate(p, skip_voice_ids=[profile.voice_id])
                self.assertFalse(result.is_duplicate)
            finally:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)


# ==================================================================
# Phase 3.3 安全与审计系统
# ==================================================================

class TestAuditLogger(unittest.TestCase):
    """AuditLogger 测试"""

    def test_log_and_query(self):
        """记录并查询审计日志"""
        with _IsolatedDb():
            from backend.voice_identity.audit import AuditLogger, EVENT_CREATED
            logger = AuditLogger()
            entry = logger.log(
                event_type=EVENT_CREATED,
                voice_id="test_vid",
                actor_id="test_actor",
                owner_id="test_owner",
                detail={"name": "测试声音"},
            )
            self.assertIsNotNone(entry)
            self.assertEqual(entry.event_type, EVENT_CREATED)
            self.assertEqual(entry.voice_id, "test_vid")
            # 查询
            entries = logger.query(voice_id="test_vid")
            self.assertGreaterEqual(len(entries), 1)
            self.assertEqual(entries[0].voice_id, "test_vid")

    def test_log_invalid_event_returns_none(self):
        """非法事件类型返回 None"""
        with _IsolatedDb():
            from backend.voice_identity.audit import AuditLogger
            logger = AuditLogger()
            entry = logger.log(event_type="invalid_event", voice_id="x")
            self.assertIsNone(entry)

    def test_query_by_event_type(self):
        """按事件类型查询"""
        with _IsolatedDb():
            from backend.voice_identity.audit import AuditLogger, EVENT_CREATED, EVENT_DELETED
            logger = AuditLogger()
            logger.log(event_type=EVENT_CREATED, voice_id="v1", actor_id="a1")
            logger.log(event_type=EVENT_DELETED, voice_id="v1", actor_id="a2")
            created = logger.query(event_type=EVENT_CREATED)
            deleted = logger.query(event_type=EVENT_DELETED)
            self.assertGreaterEqual(len(created), 1)
            self.assertGreaterEqual(len(deleted), 1)
            self.assertTrue(all(e.event_type == EVENT_CREATED for e in created))
            self.assertTrue(all(e.event_type == EVENT_DELETED for e in deleted))

    def test_query_by_actor(self):
        """按操作者查询"""
        with _IsolatedDb():
            from backend.voice_identity.audit import AuditLogger, EVENT_CREATED
            logger = AuditLogger()
            logger.log(event_type=EVENT_CREATED, voice_id="v1", actor_id="user_a")
            logger.log(event_type=EVENT_CREATED, voice_id="v2", actor_id="user_b")
            results = logger.query(actor_id="user_a")
            self.assertGreaterEqual(len(results), 1)
            self.assertTrue(all(e.actor_id == "user_a" for e in results))

    def test_count(self):
        """计数"""
        with _IsolatedDb():
            from backend.voice_identity.audit import AuditLogger, EVENT_CREATED, EVENT_DELETED
            logger = AuditLogger()
            logger.log(event_type=EVENT_CREATED, voice_id="v1")
            logger.log(event_type=EVENT_CREATED, voice_id="v2")
            logger.log(event_type=EVENT_DELETED, voice_id="v1")
            total = logger.count()
            self.assertGreaterEqual(total, 3)
            created_count = logger.count(event_type=EVENT_CREATED)
            self.assertGreaterEqual(created_count, 2)

    def test_query_with_limit_offset(self):
        """分页查询"""
        with _IsolatedDb():
            from backend.voice_identity.audit import AuditLogger, EVENT_CREATED
            logger = AuditLogger()
            for i in range(5):
                logger.log(event_type=EVENT_CREATED, voice_id=f"v{i}")
            page1 = logger.query(limit=2, offset=0)
            page2 = logger.query(limit=2, offset=2)
            self.assertEqual(len(page1), 2)
            self.assertEqual(len(page2), 2)

    def test_audit_entry_to_dict(self):
        """AuditEntry 序列化"""
        with _IsolatedDb():
            from backend.voice_identity.audit import AuditLogger, EVENT_CREATED
            logger = AuditLogger()
            logger.log(event_type=EVENT_CREATED, voice_id="v1", detail={"k": "v"})
            entries = logger.query(voice_id="v1")
            d = entries[0].to_dict()
            self.assertIn("event_type", d)
            self.assertIn("voice_id", d)
            self.assertIn("detail", d)
            self.assertEqual(d["detail"], {"k": "v"})


class TestVoicePermission(unittest.TestCase):
    """VoicePermission 测试"""

    def _make_profile(self, owner_id="user_123"):
        from backend.voice_identity.models import VoiceProfile
        return VoiceProfile(voice_id="v1", owner_id=owner_id, name="test")

    def test_system_can_all(self):
        """system 角色拥有全部权限"""
        from backend.voice_identity.audit import VoicePermission
        perm = VoicePermission()
        p = self._make_profile("user_123")
        self.assertTrue(perm.can(p, "system", "read"))
        self.assertTrue(perm.can(p, "system", "write"))
        self.assertTrue(perm.can(p, "system", "delete"))
        self.assertTrue(perm.can(p, "system", "synthesize"))

    def test_owner_can_all(self):
        """owner 拥有全部权限"""
        from backend.voice_identity.audit import VoicePermission
        perm = VoicePermission()
        p = self._make_profile("user_123")
        self.assertTrue(perm.can(p, "user_123", "read"))
        self.assertTrue(perm.can(p, "user_123", "write"))
        self.assertTrue(perm.can(p, "user_123", "delete"))

    def test_non_owner_can_read(self):
        """非 owner 可读"""
        from backend.voice_identity.audit import VoicePermission
        perm = VoicePermission()
        p = self._make_profile("user_123")
        self.assertTrue(perm.can(p, "user_other", "read"))
        self.assertTrue(perm.can(p, "user_other", "synthesize"))

    def test_non_owner_cannot_write(self):
        """非 owner 不可写/删"""
        from backend.voice_identity.audit import VoicePermission
        perm = VoicePermission()
        p = self._make_profile("user_123")
        self.assertFalse(perm.can(p, "user_other", "write"))
        self.assertFalse(perm.can(p, "user_other", "delete"))

    def test_check_raises_on_denied(self):
        """check 在拒绝时抛 PermissionError"""
        from backend.voice_identity.audit import VoicePermission, PermissionError as AuditPermError
        perm = VoicePermission()
        p = self._make_profile("user_123")
        with self.assertRaises(AuditPermError):
            perm.check(p, "user_other", "delete")

    def test_check_returns_true_on_allowed(self):
        """check 在允许时返回 True"""
        from backend.voice_identity.audit import VoicePermission
        perm = VoicePermission()
        p = self._make_profile("user_123")
        self.assertTrue(perm.check(p, "user_123", "delete"))

    def test_invalid_action_returns_false(self):
        """非法 action 返回 False"""
        from backend.voice_identity.audit import VoicePermission
        perm = VoicePermission()
        p = self._make_profile()
        self.assertFalse(perm.can(p, "system", "invalid_action"))

    def test_require_owner_or_system_pass(self):
        """owner 或 system 通过"""
        from backend.voice_identity.audit import VoicePermission
        perm = VoicePermission()
        p = self._make_profile("user_123")
        self.assertTrue(perm.require_owner_or_system(p, "user_123"))
        self.assertTrue(perm.require_owner_or_system(p, "system"))

    def test_require_owner_or_system_raises(self):
        """非 owner 非 system 抛异常"""
        from backend.voice_identity.audit import VoicePermission, PermissionError as AuditPermError
        perm = VoicePermission()
        p = self._make_profile("user_123")
        with self.assertRaises(AuditPermError):
            perm.require_owner_or_system(p, "user_other")


class TestAuditSingleton(unittest.TestCase):
    """审计单例测试"""

    def test_get_and_reset_audit_logger(self):
        with _IsolatedDb():
            from backend.voice_identity.audit import get_audit_logger, reset_audit_logger
            l1 = get_audit_logger()
            l2 = get_audit_logger()
            self.assertIs(l1, l2)
            reset_audit_logger()
            l3 = get_audit_logger()
            self.assertIsNot(l1, l3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
