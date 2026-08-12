"""
YHLZ Conversation Turn Controller V10.1.7

职责:
    - Conversation Control 层: 接收 / Turn / 打断 / 排队 / 状态
    - Conversation State Machine: IDLE → RECEIVING → READY →
      PROCESSING → STREAMING → COMPLETED → IDLE
      异常: PROCESSING/STREAMING → INTERRUPTED → QUEUED/READY
    - 事件协议: START / TOKEN / FLUSH / COMPLETE / INTERRUPTED / ERROR
      (含 conversation_id / turn_id / timestamp / sequence / event_type / payload)
    - 延迟追踪: input_start→turn_close 全阶段 (TTFT/总响应/队列等待/中断延迟)
    - turn 日志: 每个 turn 通过 turn_id 找到完整链路

设计原则:
    - Turn Controller 不替代 Streaming (Streaming 是输出传输层)
    - 每个状态有明确进入/退出条件, 可记录/可恢复/可诊断
    - 禁止隐式状态
    - 线程安全 (RLock)
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 对话状态机 (可解释)
CONVERSATION_STATES: List[str] = [
    "IDLE",        # 空闲
    "RECEIVING",   # 接收输入
    "READY",       # 待处理
    "PROCESSING",  # 处理中
    "STREAMING",   # 流式输出
    "TTS_PLAYING", # TTS 播放中 (V10.1.8)
    "COMPLETED",   # 完成
    "INTERRUPTED", # 被中断
    "QUEUED",      # 排队中
    "RECOVERY",    # 恢复中 (V10.1.8)
    "ERROR",       # 错误
]

# 事件类型 (可解释)
EVENT_TYPES: List[str] = [
    "START",       # turn 开始
    "TOKEN",       # 文本增量
    "FLUSH",       # 分段刷新
    "COMPLETE",    # 完成
    "INTERRUPTED", # 中断
    "ERROR",       # 错误
    "HEARTBEAT",   # 心跳
]

# 状态机合法迁移 (可解释)
STATE_TRANSITIONS: Dict[str, List[str]] = {
    "IDLE": ["RECEIVING"],
    "RECEIVING": ["READY", "IDLE"],
    "READY": ["PROCESSING", "QUEUED", "IDLE"],
    "PROCESSING": ["STREAMING", "INTERRUPTED", "ERROR", "IDLE"],
    "STREAMING": ["TTS_PLAYING", "COMPLETED", "INTERRUPTED",
                  "ERROR", "IDLE"],
    "TTS_PLAYING": ["COMPLETED", "INTERRUPTED", "ERROR", "IDLE"],
    "COMPLETED": ["IDLE", "READY"],
    "INTERRUPTED": ["QUEUED", "READY", "IDLE", "RECOVERY"],
    "QUEUED": ["READY", "IDLE"],
    "RECOVERY": ["READY", "IDLE", "PROCESSING"],
    "ERROR": ["IDLE", "READY", "RECOVERY"],
}

# 打断分层 (V10.1.8): LLM 取消 vs TTS 停止
INTERRUPT_LAYERS: List[str] = [
    "llm",    # LLM 生成中: 取消生成
    "tts",    # TTS 播放中: 停止播放 (最高优先级)
    "queue",  # 播放队列: 清理低优先级任务
]


class ConversationControllerError(Exception):
    """对话控制器异常"""


class ConversationTurn:
    """对话回合 (turn)"""

    def __init__(
        self,
        conversation_id: str,
        turn_id: str,
        input_text: str,
        source: str = "user",
    ):
        self.conversation_id = conversation_id
        self.turn_id = turn_id
        self.input_text = str(input_text)
        self.source = str(source)
        self.content_hash = uuid.uuid5(
            uuid.NAMESPACE_URL, str(input_text),
        ).hex[:12]
        self.state: str = "RECEIVING"
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.sequence = 0
        self.response_text: str = ""
        self.error: str = ""
        self.latency: Dict[str, float] = {}
        self.interrupted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "turn_id": self.turn_id,
            "input_text": self.input_text[:200],
            "content_hash": self.content_hash,
            "source": self.source,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "sequence": self.sequence,
            "response_text": self.response_text[:500],
            "error": self.error,
            "latency": dict(self.latency),
            "interrupted": self.interrupted,
        }


class ConversationTurnController:
    """对话回合控制器 (V10.1.7)

    用法:
        ctc = ConversationTurnController()
        turn = ctc.begin_turn("你好")
        events = ctc.stream_event(turn, "TOKEN", {"content": "哎"})
        ctc.complete_turn(turn)
    """

    def __init__(
        self,
        max_queue: int = 20,
        enabled: bool = True,
    ):
        if max_queue <= 0:
            raise ConversationControllerError(
                f"max_queue 必须 > 0, 当前: {max_queue}"
            )
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._max_queue = int(max_queue)
        self._conversation_id = "conv_" + uuid.uuid4().hex[:10]
        self._queue: deque = deque()
        self._turns: Dict[str, ConversationTurn] = {}
        self._active_turn: Optional[str] = None
        self._event_seq: Dict[str, int] = {}

    # ── Turn 生命周期 ───────────────────────────────────────────
    def begin_turn(
        self,
        input_text: str,
        source: str = "user",
    ) -> ConversationTurn:
        """接收新输入 → RECEIVING → READY (或 QUEUED)"""
        with self._lock:
            if not self._enabled:
                raise ConversationControllerError(
                    "对话控制器停用"
                )
            turn_id = "turn_" + uuid.uuid4().hex[:10]
            turn = ConversationTurn(
                self._conversation_id, turn_id, input_text, source,
            )
            self._turns[turn_id] = turn
            self._event_seq[turn_id] = 0
            turn.state = "RECEIVING"
            turn.latency["input_start"] = time.time()
            self._log_turn(turn, "begin")
            # 有活跃 turn → 入队 (不丢失)
            if self._active_turn is not None:
                turn.state = "QUEUED"
                if len(self._queue) >= self._max_queue:
                    raise ConversationControllerError(
                        f"输入队列已满 ({self._max_queue}), "
                        f"丢弃输入: {input_text[:50]}"
                    )
                self._queue.append(turn_id)
                self._log_turn(turn, "queued")
                return turn
            # 无活跃 turn → 直接 READY
            turn.state = "READY"
            turn.latency["input_end"] = time.time()
            self._active_turn = turn_id
            self._log_turn(turn, "ready")
            return turn

    def claim_ready_turn(self) -> Optional[ConversationTurn]:
        """取出待处理 turn (READY → PROCESSING)"""
        with self._lock:
            if self._active_turn is None:
                return None
            turn = self._turns.get(self._active_turn)
            if turn is None or turn.state != "READY":
                return None
            turn.state = "PROCESSING"
            turn.latency["turn_start"] = time.time()
            turn.latency["runtime_start"] = time.time()
            self._log_turn(turn, "processing")
            return turn

    def mark_streaming(self, turn_id: str) -> ConversationTurn:
        """PROCESSING → STREAMING"""
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                raise ConversationControllerError(
                    f"turn 不存在: {turn_id}"
                )
            self._transition(turn, "STREAMING")
            turn.latency["llm_start"] = time.time()
            self._log_turn(turn, "streaming")
            return turn

    def mark_tts_playing(self, turn_id: str) -> ConversationTurn:
        """STREAMING → TTS_PLAYING (V10.1.8: TTS 播放中)"""
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                raise ConversationControllerError(
                    f"turn 不存在: {turn_id}"
                )
            self._transition(turn, "TTS_PLAYING")
            turn.latency["tts_start"] = time.time()
            self._log_turn(turn, "tts_playing")
            return turn

    def recover_turn(self, turn_id: str) -> ConversationTurn:
        """ERROR → RECOVERY → READY (V10.1.8: 恢复机制)"""
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                raise ConversationControllerError(
                    f"turn 不存在: {turn_id}"
                )
            self._transition(turn, "RECOVERY")
            turn.latency["recovery_time"] = time.time()
            self._log_turn(turn, "recovery")
            # 恢复后重新进入 READY (可重试)
            self._transition(turn, "READY")
            self._active_turn = turn_id
            return turn

    def complete_turn(self, turn_id: str) -> ConversationTurn:
        """STREAMING → COMPLETED → IDLE (释放, 处理队列)"""
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                raise ConversationControllerError(
                    f"turn 不存在: {turn_id}"
                )
            self._transition(turn, "COMPLETED")
            turn.latency["response_complete"] = time.time()
            turn.latency["turn_close"] = time.time()
            self._log_turn(turn, "completed")
            self._release_active()
            return turn

    def interrupt_turn(
        self, turn_id: str, layers: Optional[List[str]] = None,
    ) -> ConversationTurn:
        """PROCESSING/STREAMING/TTS_PLAYING → INTERRUPTED → READY/IDLE

        V10.1.8 分层打断:
          llm   → 取消生成
          tts   → 停止播放 (最高优先级)
          queue → 清理低优先级任务
        """
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                raise ConversationControllerError(
                    f"turn 不存在: {turn_id}"
                )
            if turn.state not in ("PROCESSING", "STREAMING",
                                  "TTS_PLAYING", "READY"):
                return turn
            stopped = [l for l in (layers or INTERRUPT_LAYERS)
                       if l in INTERRUPT_LAYERS]
            self._transition(turn, "INTERRUPTED")
            turn.interrupted = True
            turn.latency["interrupt_time"] = time.time()
            turn.latency["stopped_layer"] = ",".join(stopped)
            self._log_turn(turn,
                           f"interrupted ({','.join(stopped)})")
            # 队列中下一个 → READY
            self._release_active()
            return turn

    def error_turn(self, turn_id: str, error: str) -> ConversationTurn:
        """→ ERROR → IDLE"""
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                raise ConversationControllerError(
                    f"turn 不存在: {turn_id}"
                )
            self._transition(turn, "ERROR")
            turn.error = str(error)
            turn.latency["turn_close"] = time.time()
            self._log_turn(turn, f"error: {error[:80]}")
            self._release_active()
            return turn

    def _release_active(self) -> None:
        """释放活跃 turn, 从队列取下一个 → READY"""
        self._active_turn = None
        if self._queue:
            next_id = self._queue.popleft()
            nxt = self._turns.get(next_id)
            if nxt is not None:
                nxt.state = "READY"
                nxt.latency["input_end"] = time.time()
                self._active_turn = next_id
                self._log_turn(nxt, "ready (from queue)")

    # ── 事件协议 ────────────────────────────────────────────────
    def stream_event(
        self,
        turn_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """生成输出事件 (sequence 单调递增)"""
        with self._lock:
            if event_type not in EVENT_TYPES:
                raise ConversationControllerError(
                    f"非法事件类型: {event_type} "
                    f"(可选: {EVENT_TYPES})"
                )
            turn = self._turns.get(turn_id)
            if turn is None:
                raise ConversationControllerError(
                    f"turn 不存在: {turn_id}"
                )
            turn.sequence += 1
            event = {
                "conversation_id": self._conversation_id,
                "turn_id": turn_id,
                "timestamp": time.time(),
                "sequence": turn.sequence,
                "event_type": event_type,
                "payload": dict(payload or {}),
            }
            if event_type == "TOKEN":
                content = str(payload.get("content", ""))
                turn.response_text += content
            elif event_type == "COMPLETE":
                turn.latency["stream_end"] = time.time()
            elif event_type == "ERROR":
                turn.error = str(payload.get("error", ""))
            return event

    # ── 查询 ────────────────────────────────────────────────────
    def state(self) -> Dict[str, Any]:
        """对话控制器状态"""
        with self._lock:
            active = self._turns.get(self._active_turn)
            return {
                "mode": "rule_based",
                "enabled": self._enabled,
                "conversation_id": self._conversation_id,
                "active_turn_id": self._active_turn,
                "active_state": active.state if active else "IDLE",
                "queue_length": len(self._queue),
                "queue_ids": list(self._queue),
                "turn_count": len(self._turns),
            }

    def turn(self, turn_id: str) -> Optional[Dict[str, Any]]:
        """查询 turn"""
        with self._lock:
            t = self._turns.get(turn_id)
            return t.to_dict() if t else None

    def recent_turns(self, limit: int = 20) -> List[Dict[str, Any]]:
        """最近 turns"""
        with self._lock:
            turns = list(self._turns.values())
        out = []
        for t in reversed(turns):
            out.append(t.to_dict())
            if 0 < limit <= len(out):
                break
        return out

    def latency_summary(self) -> Dict[str, Any]:
        """延迟汇总 (所有完成 turn)"""
        with self._lock:
            turns = list(self._turns.values())
        ttfts = []
        totals = []
        for t in turns:
            if "llm_start" in t.latency and \
                    "turn_start" in t.latency:
                ttfts.append(
                    (t.latency.get("first_token", t.latency["llm_start"])
                     - t.latency["turn_start"]) * 1000,
                )
            if "turn_close" in t.latency and \
                    "input_start" in t.latency:
                totals.append(
                    (t.latency["turn_close"]
                     - t.latency["input_start"]) * 1000,
                )
        return {
            "mode": "rule_based",
            "total_turns": len(turns),
            "completed": sum(
                1 for t in turns if t.state == "COMPLETED"
            ),
            "interrupted": sum(
                1 for t in turns if t.interrupted
            ),
            "errors": sum(
                1 for t in turns if t.state == "ERROR"
            ),
            "avg_ttft_ms": round(
                sum(ttfts) / len(ttfts), 1,
            ) if ttfts else 0.0,
            "avg_total_ms": round(
                sum(totals) / len(totals), 1,
            ) if totals else 0.0,
        }

    # ── 内部 ────────────────────────────────────────────────────
    def _transition(
        self, turn: ConversationTurn, to_state: str,
    ) -> None:
        """状态迁移校验"""
        allowed = STATE_TRANSITIONS.get(turn.state, [])
        if to_state not in allowed:
            logger.warning(
                f"[Turn] 非法迁移 {turn.state} → {to_state} "
                f"(turn={turn.turn_id})"
            )
        turn.state = to_state
        turn.updated_at = time.time()

    def _log_turn(
        self, turn: ConversationTurn, detail: str,
    ) -> None:
        """turn 日志 (turn_id 可追踪)"""
        logger.info(
            f"[Turn] id={turn.turn_id} conv={turn.conversation_id} "
            f"state={turn.state} detail={detail} "
            f"hash={turn.content_hash}"
        )

    def clear(self) -> int:
        """清空 (测试隔离)"""
        with self._lock:
            n = len(self._turns)
            self._turns.clear()
            self._queue.clear()
            self._active_turn = None
            self._event_seq.clear()
            return n


__all__ = [
    "CONVERSATION_STATES",
    "ConversationControllerError",
    "ConversationTurn",
    "ConversationTurnController",
    "EVENT_TYPES",
    "STATE_TRANSITIONS",
]
