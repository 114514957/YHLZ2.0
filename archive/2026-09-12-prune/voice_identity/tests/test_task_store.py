"""
YHLZ Voice Identity System V2.3-Phase2 - 任务持久化测试

覆盖:
    - TaskStore CRUD: save_task / get_task_record / list_tasks / count
    - 任务状态更新: update_status
    - 服务重启恢复: get_recoverable_tasks / mark_interrupted_as_failed
    - TaskQueue + TaskStore 集成: 提交后持久化, 取消后持久化
    - 历史清理: delete_old_tasks
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


class _IsolatedDb:
    """测试 DB 隔离上下文管理器 (与 test_phase3.py 一致)"""

    def __enter__(self):
        self._tmp_dir = tempfile.mkdtemp(prefix="yhlz_v23_store_")
        self._db_path = os.path.join(self._tmp_dir, "test.db")
        self._old_env = os.environ.get("YHLZ_VOICE_IDENTITY_DB")
        os.environ["YHLZ_VOICE_IDENTITY_DB"] = self._db_path
        import importlib
        import backend.voice_identity.database as db_mod
        importlib.reload(db_mod)
        db_mod.reset_db_instance()
        # 重置 store/queue 单例, 确保使用新 DB
        try:
            from backend.voice_identity.batch import reset_task_store, reset_task_queue
            reset_task_store()
            reset_task_queue()
        except Exception:
            pass
        return self

    def __exit__(self, *args):
        import importlib
        import backend.voice_identity.database as db_mod
        try:
            from backend.voice_identity.batch import reset_task_store, reset_task_queue
            reset_task_store()
            reset_task_queue()
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


def _make_task(task_id="t1", status="pending", owner="system"):
    """构造一个测试任务"""
    from backend.voice_identity.batch.task_models import (
        CloneTask, TaskItem, TaskStatus,
    )
    status_enum = {
        "pending": TaskStatus.PENDING,
        "running": TaskStatus.RUNNING,
        "completed": TaskStatus.COMPLETED,
        "partial": TaskStatus.PARTIAL,
        "failed": TaskStatus.FAILED,
    }[status]
    items = [
        TaskItem(audio_path="/tmp/a.wav", name="A", engine="qwen3"),
        TaskItem(audio_path="/tmp/b.wav", name="B", engine="qwen3"),
    ]
    return CloneTask(
        task_id=task_id, items=items, status=status_enum,
        created_at="2026-08-05T10:00:00", owner=owner,
    )


# ==================================================================
# TaskStore 基础 CRUD
# ==================================================================

class TestTaskStoreCRUD(unittest.TestCase):
    """TaskStore 增删改查"""

    def test_save_and_get(self):
        """保存并查询任务"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            store = TaskStore()
            task = _make_task("t_save", "pending")
            ok = store.save_task(task)
            self.assertTrue(ok)
            rec = store.get_task_record("t_save")
            self.assertIsNotNone(rec)
            self.assertEqual(rec["task_id"], "t_save")
            self.assertEqual(rec["status"], "pending")
            self.assertEqual(rec["owner"], "system")

    def test_save_upsert(self):
        """UPSERT: 同 task_id 重复保存更新而非插入"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            from backend.voice_identity.batch.task_models import TaskStatus
            store = TaskStore()
            task = _make_task("t_upsert", "pending")
            store.save_task(task)
            # 更新状态
            task.status = TaskStatus.RUNNING
            store.save_task(task)
            rec = store.get_task_record("t_upsert")
            self.assertEqual(rec["status"], "running")
            # 仍只有一条记录
            self.assertEqual(store.count(), 1)

    def test_get_nonexistent_returns_none(self):
        """查询不存在任务返回 None"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            store = TaskStore()
            self.assertIsNone(store.get_task_record("nonexistent"))

    def test_list_tasks(self):
        """列出任务"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            store = TaskStore()
            store.save_task(_make_task("t1", "pending"))
            store.save_task(_make_task("t2", "completed"))
            store.save_task(_make_task("t3", "failed"))
            lst = store.list_tasks(limit=10)
            self.assertEqual(len(lst), 3)
            # 按 owner 过滤
            lst_owner = store.list_tasks(owner="system")
            self.assertEqual(len(lst_owner), 3)
            lst_other = store.list_tasks(owner="other")
            self.assertEqual(len(lst_other), 0)

    def test_list_tasks_by_status(self):
        """按状态过滤"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            store = TaskStore()
            store.save_task(_make_task("t1", "pending"))
            store.save_task(_make_task("t2", "completed"))
            lst = store.list_tasks(status="completed")
            self.assertEqual(len(lst), 1)
            self.assertEqual(lst[0]["status"], "completed")

    def test_count(self):
        """计数"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            store = TaskStore()
            self.assertEqual(store.count(), 0)
            store.save_task(_make_task("t1", "pending"))
            store.save_task(_make_task("t2", "completed"))
            self.assertEqual(store.count(), 2)
            self.assertEqual(store.count(status="pending"), 1)
            self.assertEqual(store.count(status="completed"), 1)

    def test_update_status(self):
        """仅更新状态"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            from backend.voice_identity.batch.task_models import TaskStatus
            store = TaskStore()
            store.save_task(_make_task("t_upd", "pending"))
            ok = store.update_status("t_upd", TaskStatus.RUNNING)
            self.assertTrue(ok)
            rec = store.get_task_record("t_upd")
            self.assertEqual(rec["status"], "running")


# ==================================================================
# 服务重启恢复
# ==================================================================

class TestTaskStoreRecover(unittest.TestCase):
    """服务重启恢复测试"""

    def test_get_recoverable_tasks(self):
        """获取可恢复任务 (pending/running)"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            store = TaskStore()
            store.save_task(_make_task("t1", "pending"))
            store.save_task(_make_task("t2", "running"))
            store.save_task(_make_task("t3", "completed"))
            store.save_task(_make_task("t4", "failed"))
            recoverable = store.get_recoverable_tasks()
            ids = {r["task_id"] for r in recoverable}
            self.assertIn("t1", ids)
            self.assertIn("t2", ids)
            self.assertNotIn("t3", ids)
            self.assertNotIn("t4", ids)

    def test_list_pending_tasks(self):
        """list_pending_tasks 仅返回 pending/running"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            store = TaskStore()
            store.save_task(_make_task("t1", "pending"))
            store.save_task(_make_task("t2", "completed"))
            pending = store.list_pending_tasks()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["task_id"], "t1")

    def test_mark_interrupted_as_failed(self):
        """标记中断任务为 failed"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            store = TaskStore()
            store.save_task(_make_task("t1", "pending"))
            store.save_task(_make_task("t2", "running"))
            store.save_task(_make_task("t3", "completed"))
            n = store.mark_interrupted_as_failed()
            self.assertEqual(n, 2)  # t1 + t2
            # 验证 t1/t2 已变 failed
            self.assertEqual(store.get_task_record("t1")["status"], "failed")
            self.assertEqual(store.get_task_record("t2")["status"], "failed")
            # t3 不受影响
            self.assertEqual(store.get_task_record("t3")["status"], "completed")

    def test_no_recoverable_returns_empty(self):
        """无可恢复任务时返回空列表"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            store = TaskStore()
            store.save_task(_make_task("t1", "completed"))
            self.assertEqual(store.get_recoverable_tasks(), [])
            self.assertEqual(store.mark_interrupted_as_failed(), 0)


# ==================================================================
# 历史清理
# ==================================================================

class TestTaskStoreCleanup(unittest.TestCase):
    """历史清理"""

    def test_delete_old_tasks(self):
        """删除旧任务"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            store = TaskStore()
            store.save_task(_make_task("t_old", "completed"))
            # 删除 2026-01-01 之前的 (即所有任务, 因 created_at=2026-08-05)
            # 实际上我们的测试任务 created_at=2026-08-05, 用 2026-09-01 作分界
            n = store.delete_old_tasks("2026-09-01T00:00:00")
            self.assertEqual(n, 1)
            self.assertIsNone(store.get_task_record("t_old"))

    def test_delete_keeps_newer(self):
        """新任务保留"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            store = TaskStore()
            store.save_task(_make_task("t_new", "completed"))
            # 删除 2020-01-01 之前的 (无任务)
            n = store.delete_old_tasks("2020-01-01T00:00:00")
            self.assertEqual(n, 0)
            self.assertIsNotNone(store.get_task_record("t_new"))


# ==================================================================
# TaskQueue + TaskStore 集成
# ==================================================================

class TestQueueStoreIntegration(unittest.TestCase):
    """TaskQueue 与 TaskStore 集成"""

    def test_submit_persists_to_store(self):
        """提交任务后, TaskStore 中应有记录"""
        with _IsolatedDb():
            from backend.voice_identity.batch import TaskQueue, get_task_store
            q = TaskQueue(max_workers=1)
            q.start()
            try:
                task = q.submit([
                    {"audio_path": "/nonexistent/a.wav", "name": "A"},
                ])
                # 立即检查持久化 (submit 内同步调用 _persist)
                store = get_task_store()
                rec = store.get_task_record(task.task_id)
                self.assertIsNotNone(rec)
                self.assertEqual(rec["task_id"], task.task_id)
            finally:
                q.shutdown(wait=False)

    def test_cancel_persists(self):
        """取消任务后, 持久化状态更新"""
        with _IsolatedDb():
            from backend.voice_identity.batch import TaskQueue, get_task_store
            q = TaskQueue(max_workers=1)
            q.start()
            try:
                task = q.submit([
                    {"audio_path": "/nonexistent/a.wav", "name": "A"},
                    {"audio_path": "/nonexistent/b.wav", "name": "B"},
                ])
                ok = q.cancel(task.task_id)
                self.assertTrue(ok)
                store = get_task_store()
                rec = store.get_task_record(task.task_id)
                self.assertIsNotNone(rec)
                # 取消后应为 failed/partial (因 pending 项被标记 failed)
                self.assertIn(rec["status"], ("failed", "partial"))
            finally:
                q.shutdown(wait=False)

    def test_recover_on_startup_marks_failed(self):
        """recover_on_startup(rerun=False) 将 pending/running 标记为 failed"""
        with _IsolatedDb():
            from backend.voice_identity.batch import TaskQueue, get_task_store
            from backend.voice_identity.batch.task_models import TaskStatus
            # 1) 先写入一个 pending 任务到 store (模拟上次服务中断)
            store = get_task_store()
            store.save_task(_make_task("t_interrupted", "pending"))
            self.assertEqual(store.count(status="pending"), 1)
            # 2) 新队列启动恢复
            q = TaskQueue(max_workers=1)
            q.start()
            try:
                n = q.recover_on_startup(rerun=False)
                self.assertEqual(n, 1)
                # 验证已标记 failed
                rec = store.get_task_record("t_interrupted")
                self.assertEqual(rec["status"], "failed")
            finally:
                q.shutdown(wait=False)

    def test_recover_on_startup_no_tasks(self):
        """无可恢复任务时 recover 返回 0"""
        with _IsolatedDb():
            from backend.voice_identity.batch import TaskQueue, get_task_store
            store = get_task_store()
            store.save_task(_make_task("t_done", "completed"))
            q = TaskQueue(max_workers=1)
            q.start()
            try:
                n = q.recover_on_startup(rerun=False)
                self.assertEqual(n, 0)
            finally:
                q.shutdown(wait=False)

    def test_singleton_get_reset(self):
        """get_task_store / reset_task_store 单例"""
        with _IsolatedDb():
            from backend.voice_identity.batch import (
                get_task_store, reset_task_store,
            )
            s1 = get_task_store()
            s2 = get_task_store()
            self.assertIs(s1, s2)
            reset_task_store()
            s3 = get_task_store()
            self.assertIsNot(s1, s3)


# ==================================================================
# 任务进度持久化 (序列化字段)
# ==================================================================

class TestTaskStoreProgressSerialization(unittest.TestCase):
    """progress / result JSON 序列化"""

    def test_progress_contains_items(self):
        """progress 字段包含 items 详情"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_store import TaskStore
            store = TaskStore()
            store.save_task(_make_task("t_prog", "running"))
            rec = store.get_task_record("t_prog")
            progress = rec["progress"]
            self.assertIn("total", progress)
            self.assertIn("items", progress)
            self.assertEqual(progress["total"], 2)
            self.assertEqual(len(progress["items"]), 2)

    def test_result_contains_success_items(self):
        """completed 任务的 result 包含 success_items"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_models import (
                CloneTask, TaskItem, TaskStatus,
            )
            from backend.voice_identity.batch.task_store import TaskStore
            task = CloneTask(
                task_id="t_res", owner="system",
                created_at="2026-08-05T10:00:00",
                status=TaskStatus.COMPLETED,
                items=[
                    TaskItem(audio_path="/tmp/a.wav", name="A",
                             status="success", voice_id="vid_a"),
                    TaskItem(audio_path="/tmp/b.wav", name="B",
                             status="success", voice_id="vid_b"),
                ],
            )
            store = TaskStore()
            store.save_task(task)
            rec = store.get_task_record("t_res")
            result = rec["result"]
            self.assertIn("success_items", result)
            self.assertEqual(result["success_count"], 2)

    def test_failed_task_records_error(self):
        """failed 任务记录 error 字段"""
        with _IsolatedDb():
            from backend.voice_identity.batch.task_models import (
                CloneTask, TaskItem, TaskStatus,
            )
            from backend.voice_identity.batch.task_store import TaskStore
            task = CloneTask(
                task_id="t_err", owner="system",
                created_at="2026-08-05T10:00:00",
                status=TaskStatus.FAILED,
                items=[
                    TaskItem(audio_path="/tmp/a.wav", name="A",
                             status="failed", error="引擎未就绪"),
                ],
            )
            store = TaskStore()
            store.save_task(task)
            rec = store.get_task_record("t_err")
            self.assertIsNotNone(rec["error"])
            self.assertIn("引擎未就绪", rec["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
