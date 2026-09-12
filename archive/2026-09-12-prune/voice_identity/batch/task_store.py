"""
YHLZ Voice Identity System V2.3-Phase2 - 生产级任务持久化

职责:
    - 将批量克隆任务持久化到 SQLite (voice_clone_tasks 表)
    - 服务重启后任务状态可恢复
    - 支持任务状态更新与查询

数据表 voice_clone_tasks 字段:
    id          自增主键
    task_id     任务唯一 ID (业务主键)
    status      任务状态 (pending/running/completed/partial/failed)
    owner       任务发起者
    created_at  创建时间
    updated_at  更新时间
    progress    进度 JSON (success_count/failed_count/total/items 详情)
    result      结果 JSON (成功时含 voice_id 列表)
    error       错误信息 (失败时)

设计原则:
    - 复用 voice_identity.db 连接 (不新建 db 文件)
    - 表 IF NOT EXISTS 幂等创建
    - 持久化失败不阻塞主流程 (仅日志告警)
    - 与 TaskQueue 解耦: TaskQueue 内存执行, TaskStore 持久化
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.voice_identity.database import VoiceIdentityDB, get_db
from backend.voice_identity.batch.task_models import (
    CloneTask,
    TaskItem,
    TaskStatus,
    TaskSummary,
)

logger = logging.getLogger(__name__)


# ==================================================================
# 持久化表 DDL (幂等)
# ==================================================================

DDL_VOICE_CLONE_TASKS = """
CREATE TABLE IF NOT EXISTS voice_clone_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT    NOT NULL UNIQUE,
    status      TEXT    NOT NULL DEFAULT 'pending',
    owner       TEXT    NOT NULL DEFAULT 'system',
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    progress    TEXT    NOT NULL DEFAULT '{}',
    result      TEXT    NOT NULL DEFAULT '{}',
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_clone_tasks_task_id ON voice_clone_tasks(task_id);
CREATE INDEX IF NOT EXISTS idx_clone_tasks_status ON voice_clone_tasks(status);
CREATE INDEX IF NOT EXISTS idx_clone_tasks_owner ON voice_clone_tasks(owner);
CREATE INDEX IF NOT EXISTS idx_clone_tasks_created_at ON voice_clone_tasks(created_at);
"""

# 触发器: updated_at 自动更新
TRG_CLONE_TASKS_UPDATED_AT = """
CREATE TRIGGER IF NOT EXISTS trg_clone_tasks_updated_at
AFTER UPDATE ON voice_clone_tasks
FOR EACH ROW
BEGIN
    UPDATE voice_clone_tasks
    SET updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
    WHERE id = OLD.id;
END;
"""


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _task_to_progress(task: CloneTask) -> str:
    """将任务进度序列化为 JSON"""
    task.update_counts()
    return json.dumps({
        "total": task.total,
        "success_count": task.success_count,
        "failed_count": task.failed_count,
        "items": [it.to_dict() for it in task.items],
    }, ensure_ascii=False)


def _task_to_result(task: CloneTask) -> str:
    """将任务结果序列化为 JSON"""
    success_items = [
        {"voice_id": it.voice_id, "name": it.name}
        for it in task.items if it.status == "success" and it.voice_id
    ]
    return json.dumps({
        "success_items": success_items,
        "success_count": len(success_items),
    }, ensure_ascii=False)


class TaskStore:
    """任务持久化存储

    构造参数:
        db: VoiceIdentityDB (复用现有连接; None 时用全局单例)
    """

    _init_lock = threading.Lock()

    def __init__(self, db: Optional[VoiceIdentityDB] = None):
        if db is None:
            from backend.voice_identity.database import get_db
            db = get_db()
        self._db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        """幂等创建任务表"""
        with self._init_lock:
            try:
                with self._db._lock:  # type: ignore[attr-defined]
                    assert self._db._conn is not None  # type: ignore[attr-defined]
                    self._db._conn.executescript(DDL_VOICE_CLONE_TASKS)  # type: ignore[attr-defined]
                    self._db._conn.executescript(TRG_CLONE_TASKS_UPDATED_AT)  # type: ignore[attr-defined]
                logger.debug("voice_clone_tasks 表已就绪")
            except Exception as e:
                logger.error(f"创建 voice_clone_tasks 表失败: {e}")
                raise

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def save_task(self, task: CloneTask) -> bool:
        """保存或更新任务 (UPSERT)

        参数:
            task: CloneTask 实例

        返回:
            True=成功, False=失败 (不抛异常, 仅日志)
        """
        try:
            progress = _task_to_progress(task)
            result = _task_to_result(task)
            error = None
            if task.status == TaskStatus.FAILED:
                errors = [it.error for it in task.items if it.error]
                error = "; ".join(errors) if errors else "任务失败"

            with self._db._lock:  # type: ignore[attr-defined]
                assert self._db._conn is not None  # type: ignore[attr-defined]
                self._db._conn.execute(  # type: ignore[attr-defined]
                    "INSERT INTO voice_clone_tasks "
                    "(task_id, status, owner, created_at, progress, result, error) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(task_id) DO UPDATE SET "
                    "status = excluded.status, "
                    "progress = excluded.progress, "
                    "result = excluded.result, "
                    "error = excluded.error;",
                    (
                        task.task_id,
                        task.status.value,
                        task.owner,
                        task.created_at or _now_iso(),
                        progress,
                        result,
                        error,
                    ),
                )
            return True
        except Exception as e:
            logger.error(f"持久化任务失败 (不阻塞主流程): {e}")
            return False

    def update_status(self, task_id: str, status: TaskStatus) -> bool:
        """仅更新任务状态 (轻量更新)"""
        try:
            with self._db._lock:  # type: ignore[attr-defined]
                assert self._db._conn is not None  # type: ignore[attr-defined]
                self._db._conn.execute(  # type: ignore[attr-defined]
                    "UPDATE voice_clone_tasks SET status = ? WHERE task_id = ?;",
                    (status.value, task_id),
                )
            return True
        except Exception as e:
            logger.error(f"更新任务状态失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_task_record(self, task_id: str) -> Optional[Dict[str, Any]]:
        """查询任务记录 (原始 DB 行)"""
        try:
            with self._db._lock:  # type: ignore[attr-defined]
                assert self._db._conn is not None  # type: ignore[attr-defined]
                row = self._db._conn.execute(  # type: ignore[attr-defined]
                    "SELECT * FROM voice_clone_tasks WHERE task_id = ?;",
                    (task_id,),
                ).fetchone()
            if row is None:
                return None
            return {
                "id": row["id"],
                "task_id": row["task_id"],
                "status": row["status"],
                "owner": row["owner"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "progress": json.loads(row["progress"] or "{}"),
                "result": json.loads(row["result"] or "{}"),
                "error": row["error"],
            }
        except Exception as e:
            logger.error(f"查询任务记录失败: {e}")
            return None

    def list_tasks(
        self,
        owner: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """列出任务记录 (按创建时间倒序)"""
        clauses: List[str] = []
        params: List[Any] = []
        if owner is not None:
            clauses.append("owner = ?")
            params.append(owner)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT * FROM voice_clone_tasks{where} "
            f"ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?;"
        )
        params.extend([limit, offset])
        try:
            with self._db._lock:  # type: ignore[attr-defined]
                assert self._db._conn is not None  # type: ignore[attr-defined]
                rows = self._db._conn.execute(sql, tuple(params)).fetchall()  # type: ignore[attr-defined]
            return [
                {
                    "id": r["id"],
                    "task_id": r["task_id"],
                    "status": r["status"],
                    "owner": r["owner"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "progress": json.loads(r["progress"] or "{}"),
                    "result": json.loads(r["result"] or "{}"),
                    "error": r["error"],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"列出任务记录失败: {e}")
            return []

    def count(
        self,
        owner: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """统计任务数量"""
        clauses: List[str] = []
        params: List[Any] = []
        if owner is not None:
            clauses.append("owner = ?")
            params.append(owner)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        try:
            with self._db._lock:  # type: ignore[attr-defined]
                assert self._db._conn is not None  # type: ignore[attr-defined]
                row = self._db._conn.execute(  # type: ignore[attr-defined]
                    f"SELECT COUNT(*) AS c FROM voice_clone_tasks{where};",
                    tuple(params),
                ).fetchone()
            return int(row["c"]) if row else 0
        except Exception as e:
            logger.error(f"统计任务数量失败: {e}")
            return 0

    def list_pending_tasks(self) -> List[Dict[str, Any]]:
        """列出所有未完成任务 (pending/running) - 用于服务重启恢复"""
        try:
            with self._db._lock:  # type: ignore[attr-defined]
                assert self._db._conn is not None  # type: ignore[attr-defined]
                rows = self._db._conn.execute(  # type: ignore[attr-defined]
                    "SELECT * FROM voice_clone_tasks "
                    "WHERE status IN ('pending', 'running') "
                    "ORDER BY created_at ASC;",
                ).fetchall()
            return [
                {
                    "id": r["id"],
                    "task_id": r["task_id"],
                    "status": r["status"],
                    "owner": r["owner"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "progress": json.loads(r["progress"] or "{}"),
                    "result": json.loads(r["result"] or "{}"),
                    "error": r["error"],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"列出未完成任务失败: {e}")
            return []

    def get_recoverable_tasks(self) -> List[Dict[str, Any]]:
        """获取可恢复的任务 (状态为 pending 或 running)

        服务重启后, 这些任务需要重新执行或标记为 failed。
        """
        try:
            with self._db._lock:  # type: ignore[attr-defined]
                assert self._db._conn is not None  # type: ignore[attr-defined]
                rows = self._db._conn.execute(  # type: ignore[attr-defined]
                    "SELECT * FROM voice_clone_tasks "
                    "WHERE status IN ('pending', 'running') "
                    "ORDER BY created_at ASC;",
                ).fetchall()
            return [
                {
                    "id": r["id"],
                    "task_id": r["task_id"],
                    "status": r["status"],
                    "owner": r["owner"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "progress": json.loads(r["progress"] or "{}"),
                    "result": json.loads(r["result"] or "{}"),
                    "error": r["error"],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"获取可恢复任务失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 恢复
    # ------------------------------------------------------------------

    def mark_interrupted_as_failed(self) -> int:
        """服务重启时, 将所有 pending/running 任务标记为 failed

        返回:
            被标记的任务数
        """
        try:
            with self._db._lock:  # type: ignore[attr-defined]
                assert self._db._conn is not None  # type: ignore[attr-defined]
                cur = self._db._conn.execute(  # type: ignore[attr-defined]
                    "UPDATE voice_clone_tasks "
                    "SET status = 'failed', error = '服务重启中断' "
                    "WHERE status IN ('pending', 'running');",
                )
                n = cur.rowcount
            if n > 0:
                logger.info(f"已将 {n} 个中断任务标记为 failed")
            return n
        except Exception as e:
            logger.error(f"标记中断任务失败: {e}")
            return 0

    # ------------------------------------------------------------------
    # 删除 (清理旧历史)
    # ------------------------------------------------------------------

    def delete_old_tasks(self, before_date: str) -> int:
        """删除指定日期之前的任务记录 (清理历史)"""
        try:
            with self._db._lock:  # type: ignore[attr-defined]
                assert self._db._conn is not None  # type: ignore[attr-defined]
                cur = self._db._conn.execute(  # type: ignore[attr-defined]
                    "DELETE FROM voice_clone_tasks WHERE created_at < ?;",
                    (before_date,),
                )
                return cur.rowcount
        except Exception as e:
            logger.error(f"删除旧任务失败: {e}")
            return 0


# ==================================================================
# 模块级单例
# ==================================================================

_task_store: Optional[TaskStore] = None
_store_lock = threading.Lock()


def get_task_store() -> TaskStore:
    """获取全局 TaskStore 单例"""
    global _task_store
    if _task_store is None:
        with _store_lock:
            if _task_store is None:
                _task_store = TaskStore()
    return _task_store


def reset_task_store() -> None:
    """重置全局 TaskStore 单例 (仅用于测试)"""
    global _task_store
    with _store_lock:
        _task_store = None
