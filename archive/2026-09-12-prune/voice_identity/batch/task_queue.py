"""
YHLZ Voice Identity System V2.2-Phase3.1 - 批量克隆任务队列

职责:
    - 管理批量克隆任务的提交、执行、查询
    - 使用线程池并行执行任务项 (每个 TaskItem 一个线程)
    - 单项失败不影响其他项 (partial 状态)
    - 提供任务状态查询与历史列表

架构:
    submit(items) → CloneTask (pending)
      ↓ (worker 线程异步消费)
    _run_task(task_id)
      ↓ 遍历 items
    _run_item(item) → 调用 Service.clone_voice_with_adapter
      ↓
    更新 item.status / task.status

设计原则:
    - 单进程内存队列 (不引入 Celery/Redis)
    - 线程池大小可配 (默认 2, 避免并发克隆占用过多显存)
    - 任务保留可配置时长 (默认 1000 个, 超出 FIFO 淘汰)
    - 线程安全: 所有任务字典操作持锁
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.voice_identity.batch.task_models import (
    CloneTask,
    TaskItem,
    TaskStatus,
    TaskSummary,
)
from backend.voice_identity.batch.task_store import TaskStore, get_task_store

logger = logging.getLogger(__name__)


class BatchTaskError(Exception):
    """批量任务异常"""


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class TaskQueue:
    """批量克隆任务队列 (线程池 worker)

    构造参数:
        max_workers: 线程池大小 (默认 2)
        max_history: 保留历史任务数 (默认 1000, FIFO 淘汰)
        store:       TaskStore 持久化实例 (None 时用全局单例, 随 DB 隔离环境生效)
    """

    def __init__(
        self,
        max_workers: int = 2,
        max_history: int = 1000,
        store: Optional[TaskStore] = None,
    ):
        self._max_workers = max_workers
        self._max_history = max_history
        self._tasks: "OrderedDict[str, CloneTask]" = OrderedDict()
        self._lock = threading.RLock()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: Dict[str, Future] = {}
        self._closed = False
        # 持久化: None 时延迟到首次使用才取全局单例 (便于测试 DB 隔离)
        self._store: Optional[TaskStore] = store

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动 worker 线程池"""
        if self._executor is None and not self._closed:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="batch-clone",
            )
            logger.info(f"TaskQueue 已启动 (max_workers={self._max_workers})")

    def shutdown(self, wait: bool = True) -> None:
        """关闭线程池"""
        self._closed = True
        if self._executor is not None:
            self._executor.shutdown(wait=wait)
            self._executor = None
            logger.info("TaskQueue 已关闭")

    @property
    def is_running(self) -> bool:
        return self._executor is not None and not self._closed

    @property
    def store(self) -> Optional[TaskStore]:
        """持久化存储实例 (延迟取全局单例, 便于测试 DB 隔离)"""
        if self._store is None:
            try:
                self._store = get_task_store()
            except Exception as e:
                logger.warning(f"TaskStore 初始化失败, 持久化禁用: {e}")
                self._store = None
        return self._store

    def _persist(self, task: CloneTask) -> None:
        """持久化任务 (失败不阻塞主流程, 仅日志)"""
        s = self.store
        if s is None:
            return
        try:
            s.save_task(task)
        except Exception as e:
            logger.warning(f"任务持久化失败 (不阻塞): {e}")

    def recover_on_startup(self, rerun: bool = False) -> int:
        """服务重启恢复: 将 pending/running 任务标记为 failed (或重新入队)

        参数:
            rerun: True 时重新提交可恢复任务 (谨慎: 可能重复克隆);
                   False (默认) 仅标记为 failed 并保留记录

        返回:
            处理的任务数
        """
        s = self.store
        if s is None:
            return 0
        try:
            recoverable = s.get_recoverable_tasks()
        except Exception as e:
            logger.error(f"获取可恢复任务失败: {e}")
            return 0
        if not recoverable:
            return 0
        if not rerun:
            return s.mark_interrupted_as_failed()
        # rerun=True: 重新构造 items 提交 (仅 pending 状态的项)
        n = 0
        for rec in recoverable:
            progress = rec.get("progress") or {}
            items_raw = progress.get("items") or []
            re_items = [
                {
                    "audio_path": it.get("audio_path"),
                    "name": it.get("name"),
                    "engine": it.get("engine", "qwen3"),
                    "language": it.get("language", "zh"),
                    "metadata": it.get("metadata", {}) or {},
                }
                for it in items_raw
                if it.get("status") == "pending" and it.get("audio_path") and it.get("name")
            ]
            if re_items and self.is_running:
                try:
                    self.submit(re_items, owner=rec.get("owner", "system"))
                    n += 1
                except Exception as e:
                    logger.warning(f"重提交任务 {rec.get('task_id')} 失败: {e}")
            # 标记原任务为 failed (已由新任务替代)
            try:
                s.update_status(rec.get("task_id", ""), TaskStatus.FAILED)
            except Exception:
                pass
        logger.info(f"服务重启恢复: 重新提交 {n} 个任务")
        return n

    # ------------------------------------------------------------------
    # 提交任务
    # ------------------------------------------------------------------

    def submit(
        self,
        items: List[Dict[str, Any]],
        owner: str = "system",
    ) -> CloneTask:
        """提交批量克隆任务

        参数:
            items: 任务项列表, 每项 dict 含:
                   - audio_path (必需)
                   - name (必需)
                   - engine (可选, 默认 qwen3)
                   - language (可选, 默认 zh)
                   - metadata (可选, dict)
            owner: 任务发起者

        返回:
            CloneTask (status=pending)

        异常:
            BatchTaskError: 队列未启动 / items 为空 / 参数缺失
        """
        if not self.is_running:
            raise BatchTaskError("TaskQueue 未启动, 请先调用 start()")
        if not items:
            raise BatchTaskError("items 不能为空")

        # 构造任务项
        task_items: List[TaskItem] = []
        for idx, raw in enumerate(items):
            audio_path = raw.get("audio_path")
            name = raw.get("name")
            if not audio_path:
                raise BatchTaskError(f"第 {idx+1} 项缺少 audio_path")
            if not name:
                raise BatchTaskError(f"第 {idx+1} 项缺少 name")
            task_items.append(TaskItem(
                audio_path=audio_path,
                name=name,
                engine=raw.get("engine", "qwen3"),
                language=raw.get("language", "zh"),
                metadata=raw.get("metadata", {}) or {},
            ))

        task_id = f"batch_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        task = CloneTask(
            task_id=task_id,
            items=task_items,
            status=TaskStatus.PENDING,
            created_at=_now_iso(),
            owner=owner,
        )

        with self._lock:
            self._add_task(task)
            self._persist(task)

        # 提交到线程池异步执行
        future = self._executor.submit(self._run_task, task_id)
        self._futures[task_id] = future
        logger.info(f"批量任务已提交: {task_id} (items={len(task_items)} owner={owner})")
        return task

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> Optional[CloneTask]:
        """查询任务详情"""
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 50) -> List[TaskSummary]:
        """列出最近任务 (按创建时间倒序)"""
        with self._lock:
            tasks = list(self._tasks.values())
        tasks.sort(key=lambda t: t.created_at or "", reverse=True)
        out: List[TaskSummary] = []
        for t in tasks[:limit]:
            t.update_counts()
            out.append(TaskSummary(
                task_id=t.task_id,
                status=t.status.value,
                total=t.total,
                success_count=t.success_count,
                failed_count=t.failed_count,
                created_at=t.created_at,
                ended_at=t.ended_at,
            ))
        return out

    def cancel(self, task_id: str) -> bool:
        """取消任务 (仅 pending/running 可取消; 当前版本仅标记, 不中断已运行项)

        返回:
            True 表示成功标记取消
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.PARTIAL):
                return False
            # 标记未开始的项为 failed
            for it in task.items:
                if it.status == "pending":
                    it.status = "failed"
                    it.error = "任务已取消"
                    it.ended_at = _now_iso()
            task.status = task.compute_status()
            task.ended_at = _now_iso()
            self._persist(task)
            return True

    # ------------------------------------------------------------------
    # 内部: 任务执行
    # ------------------------------------------------------------------

    def _run_task(self, task_id: str) -> None:
        """worker 线程执行入口 (在线程池中运行)"""
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            logger.error(f"任务不存在: {task_id}")
            return

        task.status = TaskStatus.RUNNING
        task.started_at = _now_iso()
        self._persist(task)
        logger.info(f"批量任务开始执行: {task_id} (items={task.total})")

        for idx, item in enumerate(task.items):
            if item.status != "pending":
                # 已被取消
                continue
            item.status = "running"
            item.started_at = _now_iso()
            try:
                self._run_item(item)
            except Exception as e:
                item.status = "failed"
                item.error = f"worker 异常: {e}"
                logger.error(f"任务项执行异常 [{task_id}#{idx}]: {e}", exc_info=True)
            finally:
                item.ended_at = _now_iso()
                # 每项完成后持久化进度 (断点可查)
                self._persist(task)

        # 计算最终状态
        task.status = task.compute_status()
        task.ended_at = _now_iso()
        task.update_counts()
        self._persist(task)
        logger.info(
            f"批量任务完成: {task_id} status={task.status.value} "
            f"success={task.success_count} failed={task.failed_count}"
        )

    def _run_item(self, item: TaskItem) -> None:
        """执行单个克隆项 (调用 VoiceIdentityService)

        异常:
            引擎未就绪 / 克隆失败 → 抛异常, 由上层标记 failed
        """
        import os
        from backend.voice_identity.service import VoiceIdentityService
        from backend.voice_identity.adapter.config import build_adapter_from_config

        # 音频文件存在性预校验 (避免阻塞后端服务加载)
        if not item.audio_path or not os.path.exists(item.audio_path):
            item.status = "failed"
            item.error = f"[validate] 音频文件不存在: {item.audio_path}"
            logger.warning(f"克隆失败 [{item.name}]: {item.error}")
            return

        # 获取 Service 单例 (与 API 层一致)
        try:
            from backend.main import _get_voice_identity_service
            svc: VoiceIdentityService = _get_voice_identity_service()
        except Exception:
            # 测试环境或未初始化时直接构造
            svc = VoiceIdentityService()

        # 构造请求级 adapter (并发安全)
        adapter = None
        try:
            r = build_adapter_from_config(item.engine)
            if r.is_ok:
                adapter = r.unwrap()
        except Exception as e:
            logger.warning(f"构造 adapter 失败 [{item.engine}]: {e}")

        result = svc.clone_voice_with_adapter(
            audio_path=item.audio_path,
            name=item.name,
            engine=item.engine,
            metadata=item.metadata or None,
            language=item.language,
            auto_prepare=True,
            adapter=adapter,
        )
        if result.is_err():
            item.status = "failed"
            item.error = str(result.error)
            logger.warning(f"克隆失败 [{item.name}]: {result.error}")
            return
        clone_result = result.unwrap()
        item.voice_id = clone_result.profile.voice_id
        item.status = "success"
        logger.info(f"克隆成功 [{item.name}] → voice_id={item.voice_id}")

    # ------------------------------------------------------------------
    # 内部: 任务存储
    # ------------------------------------------------------------------

    def _add_task(self, task: CloneTask) -> None:
        """添加任务并淘汰过期历史 (FIFO)"""
        self._tasks[task.task_id] = task
        while len(self._tasks) > self._max_history:
            self._tasks.popitem(last=False)


# ── 模块级单例 ──
_task_queue: Optional[TaskQueue] = None
_queue_lock = threading.Lock()


def get_task_queue() -> TaskQueue:
    """获取全局 TaskQueue 单例 (首次调用自动启动)"""
    global _task_queue
    if _task_queue is None:
        with _queue_lock:
            if _task_queue is None:
                _task_queue = TaskQueue()
                _task_queue.start()
    return _task_queue


def reset_task_queue() -> None:
    """重置全局 TaskQueue 单例 (仅用于测试 teardown)"""
    global _task_queue
    with _queue_lock:
        if _task_queue is not None:
            try:
                _task_queue.shutdown(wait=False)
            except Exception:
                pass
            _task_queue = None
