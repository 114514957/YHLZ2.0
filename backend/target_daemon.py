"""Always-on daemon (ledger 0168/0169): multi-channel ConversationSessions.

Routes:
  GET  /health                     -> status (sessions, memory)
  POST /turn      {"text","channel"} -> per-channel turn (private default)
  POST /v1/chat/completions        -> OpenAI-compatible (AstrBot provider):
          messages last user text; "user" field = channel id (public).

Per-channel sessions: each group/user gets an independent conversation +
session file (cache/sessions/qq_<id>.json). Public channels add the
PUBLIC_CONVERGENCE_CLAUSE (privacy guard).  Dual-rail LLM (cloud -> local).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional

_PROJECT = __import__("pathlib").Path(__file__).resolve().parent.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

LOCAL_BASE = "http://127.0.0.1:11434/v1/chat/completions"
LOCAL_MODEL = "qwen2.5:3b"

from backend.console_server import ConsoleHandler  # noqa: E402 (workbench UI base)
from backend import notify_guard  # noqa: E402 (F5 dedupe/rate-limit)

NOTIFY_DIR = _PROJECT / "cache" / "qqwatch"
NOTIFY_FILE = NOTIFY_DIR / "notifications.json"
NOTIFY_LAST_POP = NOTIFY_DIR / "notifications.popup.json"
NOTIFY_RESULT_WORDS = ("完成", "已导出", "已入库", "入库", "导出", "总结", "已生成",
                       "汇报", "抽取", "处理完", "技能", "已启动", "已停止")
# write/action tools only — read tools (kb.query, file.read, ...) never notify
NOTIFY_TOOL_HINTS = ("qq.export", "qq.process", "qq.runbatch", "qq.bootstrap",
                     "qq.shutdown", "qq.digest", "qq.summarize",
                     "memory.save", "diary.write", "task.plan",
                     "skill.add", "kb.add")

# 自主可审计（0496）：每次自主 tick 落一条决策——时间 / 驱动值 / 选题 / 是否推送 / 拦截原因
AUTONOMY_LOG_FILE = NOTIFY_DIR / "autonomy_ticks.json"
AUTONOMY_LOG_KEEP = 40  # 3h 一次 → 约 5 天


def log_autonomy_tick(entry: dict) -> None:
    """Append one autonomy-tick decision (bounded; never raises)."""
    try:
        NOTIFY_DIR.mkdir(parents=True, exist_ok=True)
        rows = []
        if AUTONOMY_LOG_FILE.exists():
            try:
                rows = json.loads(AUTONOMY_LOG_FILE.read_text(encoding="utf-8"))
            except Exception:
                rows = []
        if not isinstance(rows, list):
            rows = []
        rows.append(entry)
        del rows[:-AUTONOMY_LOG_KEEP]
        AUTONOMY_LOG_FILE.write_text(json.dumps(rows, ensure_ascii=False),
                                     encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — 记账失败不能打断自主链路
        print(f"[autonomy] 决策日志写入失败 {type(exc).__name__}", flush=True)


def read_autonomy_ticks(limit: int = 20) -> list[dict]:
    """Recent autonomy-tick decisions, newest first (audit / workbench)."""
    try:
        rows = json.loads(AUTONOMY_LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    rows = [r for r in rows if isinstance(r, dict)]
    return list(reversed(rows[-max(1, int(limit)):]))


def _drive_snapshot(limit: int = 3) -> list[dict]:
    """Top intrinsic drives at tick time (the values that were supposed to drive it)."""
    try:
        from backend import intrinsic_drives

        return [{"name": d.get("name"), "category": d.get("category"),
                 "strength": d.get("strength"), "priority": d.get("priority")}
                for d in intrinsic_drives.active(limit)]
    except Exception:
        return []


def _drive_urge() -> dict:
    """内因触发信号（0501）；任何失败都退化为"没有内因推动"。"""
    try:
        from backend import intrinsic_drives

        return intrinsic_drives.urge()
    except Exception:
        return {"name": "", "category": "", "strength": 0.0, "note": ""}


def notify_push(text: str) -> None:
    """Append a Yuanheng activity notification (bounded queue)."""
    import pathlib

    NOTIFY_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    if NOTIFY_FILE.exists():
        try:
            entries = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
        except Exception:
            entries = []
    entries.append({"ts": time.time(), "text": str(text)[:600]})
    del entries[:-8]
    NOTIFY_FILE.write_text(json.dumps(entries, ensure_ascii=False),
                           encoding="utf-8")


def notify_should(text: str, tools: list[dict]) -> bool:
    """Heuristic: is this turn worth pushing to the owner's desktop?"""
    joined = " ".join(
        str(u.get("name", "")) for u in (tools or []))
    if any(h in joined for h in NOTIFY_TOOL_HINTS):
        return True
    return any(w in text for w in NOTIFY_RESULT_WORDS)


# 自主触发（0501）：过去只有 3h 定时器 —— 内在因只进 prompt、不影响**何时**发生。
# 现在多一条内因通路：某条非「期待」驱动被顶到阈值以上且过了冷却 → 提前起身。
AUTONOMY_URGE_THRESHOLD = 0.75   # 单条驱动强度 ≥ 此值 = 该动一动
AUTONOMY_URGE_COOLDOWN = 3600.0  # 内因触发的两次之间至少隔 1h（防抖）
AUTONOMY_POLL_SECONDS = 300.0    # 轮询步长：判定只是读一个小 json，很便宜


def autonomy_due(*, last_tick: float, now: float, timer_seconds: float,
                 urge_strength: float, last_urge: float = 0.0,
                 urge_threshold: float = AUTONOMY_URGE_THRESHOLD,
                 urge_cooldown: float = AUTONOMY_URGE_COOLDOWN) -> tuple[bool, str]:
    """该不该跑一次自主（纯函数，可单测）。返回 (是否, 触发原因)。

    原因 ∈ timer（到点）/ urge（内因顶高）/ wait。
    """
    if float(now) - float(last_tick) >= float(timer_seconds):
        return True, "timer"
    if (float(urge_strength) >= float(urge_threshold)
            and float(now) - float(last_urge) >= float(urge_cooldown)):
        return True, "urge"
    return False, "wait"


def _gpu_chat_active() -> int:
    """Cheap GPU-interlock read used by /health (never touches SQLite/locks)."""
    try:
        from backend import gpu_lock

        return int(gpu_lock.chat_active())
    except Exception:
        return 0


def _daemon_target_voice_enabled() -> bool:
    """Opt-in (default off): route audio turns through the shared Target graph."""
    import os

    return os.getenv("YHLZ_DAEMON_TARGET_VOICE", "0").strip() == "1"


def _daemon_target_device_binding():
    """Build an explicit endpoint binding from env (fail-closed)."""
    import os

    from backend.target_device_binding import TargetDeviceBinding

    return TargetDeviceBinding(
        input_name=os.getenv("YHLZ_TARGET_INPUT_NAME", ""),
        output_name=os.getenv("YHLZ_TARGET_OUTPUT_NAME", ""),
        route=os.getenv("YHLZ_TARGET_ROUTE", "speaker_mic"),
        input_hostapi_name=os.getenv("YHLZ_TARGET_INPUT_HOSTAPI") or None,
        output_hostapi_name=os.getenv("YHLZ_TARGET_OUTPUT_HOSTAPI") or None,
    )


class DaemonRuntime:
    def __init__(self, session_factory: Optional[Callable[[], Any]] = None,
                 llm_turn: Any = None,
                 autonomy_seconds: Optional[float] = None) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._factory = session_factory or self._default_session
        self._llm_turn_override = llm_turn
        self._sessions: dict[str, Any] = {}
        self._lock = threading.Lock()
        # 节点A (default off): route audio turns through the shared Target graph.
        self._target_voice = None
        self._target_voice_error = ""
        self._target_voice_lock = threading.Lock()
        self._started_at = time.time()
        self._target_voice_cleanup_pending = False
        from backend.voice_task_supervisor import VoiceTaskSupervisor
        self._voice_supervisor = VoiceTaskSupervisor()
        from backend.voice_jobs import VoiceJobs
        self._voice_jobs = VoiceJobs()
        import os as _os

        if autonomy_seconds is None:
            try:
                autonomy_seconds = float(
                    _os.getenv("YHLZ_AUTONOMY_SECONDS", "0")) or 3 * 3600
            except Exception:
                autonomy_seconds = 3 * 3600
        self.autonomy_seconds = float(autonomy_seconds)
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._worker.start()
        self._ready.wait(timeout=10)
        # selfcheck superseded by schedule plan_night (ledger 0196/0209)
        # batch-2 #2 (ledger 0196) -> superseded by schedule-driven autonomy
        # (ledger 0209): Yuanheng designs its own recurring plans; the daemon
        # reads the schedule table and nudges when an entry is due.
        self._sched_checked = ""
        # B4 (ledger 0437): serializes due-plan processing; non-blocking so a
        # plan nudge (itself a turn) cannot deadlock the nested check.
        self._sched_lock = threading.Lock()
        threading.Thread(target=self._schedule_loop, daemon=True).start()
        self._upkeep_last = ""
        threading.Thread(target=self._memory_upkeep_loop, daemon=True).start()
        # 0501: 起点=现在（与旧的"先睡 3h 再首次 tick"一致）；内因通道也以启动时刻
        # 起算冷却——否则重启时若某条驱动恰好高位，会立刻触发一次自主（不是我们想要的）
        self._autonomy_last = time.time()
        self._autonomy_urge_last = time.time()
        threading.Thread(target=self._autonomy_loop, daemon=True).start()

    def _autonomy_loop(self) -> None:
        """Unified autonomy cadence (ledger 0226 / 0501): one self-initiated moment
        either on the timer (default 3h) **or** earlier when an intrinsic drive
        is pushed above the urge threshold. Polls cheaply; the decision itself
        is the pure function `autonomy_due`."""
        while True:
            time.sleep(min(AUTONOMY_POLL_SECONDS, max(30.0, self.autonomy_seconds / 10)))
            try:
                u = _drive_urge()
                now = time.time()
                due, trigger = autonomy_due(
                    last_tick=self._autonomy_last, now=now,
                    timer_seconds=self.autonomy_seconds,
                    urge_strength=u.get("strength", 0.0),
                    last_urge=self._autonomy_urge_last)
                if not due:
                    continue
                s = self._session("console")

                async def _run():
                    # 0501: 内因触发的 tick 要说明"为什么是现在"，否则元亨会
                    # 以为是例行公事（这是内因驱动的意义所在）。
                    if trigger == "urge" and u.get("name"):
                        why = (f"（这次不是到点，是你内在的「{u.get('name')}」"
                               f"被顶起来了——强度 {u.get('strength')}）")
                    else:
                        why = "（到点的例行自主）"
                    return await s.proactive_tick(
                        f"这是你的自主时刻{why}：读你的内在因，"
                        "据此行动——去探索未知、推进你的渴望、或对齐老爹的期待。"
                        "简短、真实；没有就说没有，别硬凑。若确实想通了值得长期"
                        "坚持的原则，可用 memory.save(importance 8-9) 记下。",
                        extra="")

                fut = asyncio.run_coroutine_threadsafe(_run(), self._loop)
                info = fut.result(timeout=300)
                try:
                    s.save_session("console")
                except Exception:
                    pass
                try:
                    # turn the autonomous thinking into cognition proposals
                    # (PENDING -> owner approval, ledger 0226)
                    self._maybe_consolidate("console")
                except Exception:
                    pass
                try:
                    # 2026-10-01: 自主时刻不再转发 QQ，改写进元亨自己的日记。
                    from backend.target_scheduler_tools import diary_write

                    ans = str(info.get("answer", "")).strip()
                    if len(ans) < 30:
                        pushed, reason = False, "too_short"
                    elif ans.startswith("没有"):
                        pushed, reason = False, "model_says_none"
                    else:
                        ok, reason = notify_guard.allow_ex(
                            "autonomy_diary", ans, cooldown=3 * 3600,
                            max_per_day=8)
                        pushed = bool(ok)
                        if pushed:
                            diary_write("【自主时刻】" + ans)
                except Exception as exc:  # noqa: BLE001
                    pushed, reason, ans = False, "error", str(
                        info.get("answer", "")).strip()
                    print(f"[autonomy] diary 失败 {type(exc).__name__}", flush=True)
                log_autonomy_tick({
                    "ts": time.time(),
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "trigger": trigger,
                    "urge": u,
                    "drives": _drive_snapshot(),
                    "tool_uses": info.get("tool_uses", []),
                    "answer_head": ans[:120],
                    "diary": pushed,
                    "reason": reason,
                })
                self._autonomy_last = time.time()
                if trigger == "urge":
                    self._autonomy_urge_last = time.time()
                print("[autonomy] tick(" + trigger + "): "
                      + str(info.get("answer", ""))[:90]
                      + f" | diary={pushed}/{reason}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[autonomy] skip {type(exc).__name__}", flush=True)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    @staticmethod
    def _default_session(channel: str = "private"):
        from backend.env_loader import ensure_env_loaded

        ensure_env_loaded()
        from backend.target_entry import ConversationSession, is_owner_channel
        from backend.target_orchestrator import build_openai_compatible_llm_turn

        llm = build_openai_compatible_llm_turn(
            fallback_base_url=LOCAL_BASE, fallback_model=LOCAL_MODEL)
        if str(channel) == "console":
            # workbench: default (non-injected) llm so run_turn can rebuild a
            # streaming turn on on_delta (0222); shared L2 db via TargetMemory
            s = ConversationSession(channel=channel)
            try:
                s.load_session("console")
            except Exception:
                pass
            return s
        # ConversationSession owns channel isolation and summary-hook wiring
        # for both owner and group sessions. Injecting a bare group service here
        # previously bypassed those hooks and lost its rolling summary.
        s = ConversationSession(llm_turn=llm, channel=channel)
        if channel != "private":
            try:
                s.load_session(f"qq_{channel}")
            except Exception:
                pass
        else:
            try:
                s.load_session("default")
            except Exception:
                pass
        return s

    def _session(self, channel: str) -> Any:
        key = channel or "private"
        with self._lock:
            s = self._sessions.get(key)
            if s is None:
                s = self._factory(key)
                if self._llm_turn_override is not None:
                    s.llm_turn = self._llm_turn_override
                s._voice_supervisor = self._voice_supervisor
                self._sessions[key] = s
            return s

    def health(self) -> dict:
        # F3 (ledger 0436): /health must never touch SQLite/session locks —
        # the watchdog polls it with a 2s timeout and a busy DB used to make a
        # live daemon look "down", triggering the respawn storm. Heavy stats
        # stay on the session /status path.
        try:
            counts = {k: len(getattr(self._sessions[k], "history", [])) // 2
                      for k in self._sessions}
        except Exception as exc:
            return {"status": "degraded", "detail": type(exc).__name__}
        return {"status": "ok", "provider": "dual-rail",
                "sessions": len(self._sessions), "turns": counts,
                "llm": "deepseek->ollama",
                "uptime_s": round(
                    time.time() - getattr(self, "_started_at", time.time()), 1),
                "active_turns": _gpu_chat_active(),
                "voice_background": self._voice_supervisor.snapshot(),
                "target_voice": self._target_voice.health() if self._target_voice is not None else {
                    "ready": False, "error_code": self._target_voice_error,
                    "cleanup_pending": self._target_voice_cleanup_pending}}

    @staticmethod
    def _norm_ui_channel(channel: str) -> str:
        """Unified conversation (ledger 0226): all owner text entry points share
        one session ('console' = console UI / pet chat window / plain /turn)."""
        c = str(channel or "").strip()
        # "public" is the external OpenAI-compatible channel — it must stay
        # isolated (own memory db, read-only tools), NOT alias to owner.
        if c in ("", "private", "default", "chat", "console"):
            return "console"
        return c

    def turn(self, text: str, channel: str = "private",
             images: list | None = None, audio: list | None = None) -> dict:
        """GPU interlock (ledger 0459): refuse new turns during the SVC window.

        节点A (opt-in, default off): audio turns are routed through the shared
        Target graph; only a clean pre-dispatch failure may use the legacy path.
        """
        from backend import gpu_lock

        if not gpu_lock.chat_enter():
            return {"answer": gpu_lock.busy_message(), "tool_uses": [],
                    "iterations": 0, "busy": True}
        try:
            if audio and not images and self._norm_ui_channel(channel) == "console":
                routed = self._target_voice_turn(text, channel, audio)
                if routed is not None:
                    return routed
            return self._turn_impl(text, channel, images=images, audio=audio)
        finally:
            gpu_lock.chat_exit()

    def _ensure_target_voice(self):
        """节点A: lazily start the shared Target graph on this daemon loop.

        Strictly opt-in; fail-closed (returns None on any error so the caller
        falls back to the legacy path).  Never opens devices unless enabled.
        """
        if not _daemon_target_voice_enabled():
            return None
        with self._target_voice_lock:
            if self._target_voice is not None:
                return self._target_voice
            if self._target_voice_error:
                return None
            service = None
            future = None
            try:
                import os

                from backend.target_daemon_service import TargetDaemonService

                service = TargetDaemonService(
                    _daemon_target_device_binding(),
                    model_dir=(os.getenv("YHLZ_TARGET_MODEL_DIR") or None),
                    voice_profile=(os.getenv("YHLZ_TARGET_VOICE_PROFILE") or None),
                    session_factory=lambda: self._session("console"),
                    voice_supervisor=self._voice_supervisor,
                )
                future = asyncio.run_coroutine_threadsafe(service.start(), self._loop)
                future.result(timeout=240)
                self._target_voice = service
                print("[target-voice] started", flush=True)
                return service
            except Exception as exc:  # noqa: BLE001
                self._target_voice_error = type(exc).__name__
                if future is not None and not future.done():
                    future.cancel()
                if service is not None:
                    self._target_voice_cleanup_pending = True
                    try:
                        cleanup = asyncio.run_coroutine_threadsafe(service.shutdown(), self._loop)
                        cleanup.result(timeout=15)
                        self._target_voice_cleanup_pending = False
                    except Exception:
                        # Never start the old path while output ownership is unknown.
                        pass
                print(f"[target-voice] start failed: {self._target_voice_error}",
                      flush=True)
                return None

    def _target_voice_turn(self, text, channel, audio):
        """Route one audio turn through the shared Target graph.

        Returns a turn dict, or None so the caller uses the legacy entry.
        """
        if self._norm_ui_channel(channel) != "console":
            return None  # QQ/public audio must not activate the local speaker.
        service = self._ensure_target_voice()
        if service is None:
            if getattr(self, "_target_voice_cleanup_pending", False):
                return {"answer": "", "status": "failed", "target_voice": True,
                        "error_code": "TARGET-CLEANUP-UNCONFIRMED", "tool_uses": [], "iterations": 0}
            return None
        future = None
        try:
            future = asyncio.run_coroutine_threadsafe(
                service.submit_audio(audio, text=str(text or ""),
                                     source="daemon_audio"),
                self._loop)
            result = future.result(timeout=240)
            return {
                "answer": str(getattr(result, "text", "") or ""),
                "tool_uses": [],
                "iterations": 1,
                "status": str(getattr(result, "status", "") or ""),
                "target_voice": True,
                "turn_id": getattr(result, "turn_id", None),
                "error_code": getattr(result, "error_code", None),
            }
        except Exception as exc:  # noqa: BLE001
            if future is not None:
                future.cancel()  # service cancels only this turn's lease, not a newer one
            print(f"[target-voice] turn failed: {type(exc).__name__}", flush=True)
            return {"answer": "", "tool_uses": [], "iterations": 1,
                    "status": "failed", "target_voice": True,
                    "error_code": "TARGET-VOICE-" + type(exc).__name__.upper(),
                    "stop_confirmed": False}

    def shutdown_voice(self, timeout_s=20.0):
        async def close():
            try:
                jobs = getattr(self, "_voice_jobs", None)
                if jobs is not None:
                    await jobs.shutdown()
                if self._target_voice is not None:
                    await self._target_voice.shutdown()
            finally:
                await self._voice_supervisor.shutdown()
        return asyncio.run_coroutine_threadsafe(close(), self._loop).result(timeout=timeout_s)

    def _turn_impl(self, text: str, channel: str = "private",
                   images: list | None = None, audio: list | None = None) -> dict:
        key = self._norm_ui_channel(channel)
        # owner dev console (#dev/#a/#ds/#y/#n/#push) — not a conversation turn
        # (ledger 0407): mirrors the QQ bridge without hijacking chat.
        try:
            from backend.target_entry import is_owner_channel

            if is_owner_channel(key):
                from backend.target_dev_bridge import handle_dev_command

                cmd_reply = handle_dev_command(str(text or ""))
                if cmd_reply is not None:
                    return {"answer": cmd_reply, "tool_uses": [],
                            "iterations": 0, "dev_command": True}
        except Exception:
            pass
        s = self._session(key)
        future = asyncio.run_coroutine_threadsafe(
            s.run_turn(str(text), images=images, audio=audio), self._loop)
        info = future.result(timeout=240)
        # Text markers cannot authorize a dev process. Apply defense in depth
        # for custom/legacy session factories too; explicit #dev was handled
        # above from trusted owner input. Frozen audio dispatch stays unchanged.
        if not audio:
            from backend.target_entry import is_owner_channel
            from backend.target_dev_bridge import guard_text_dev_handoff

            guarded, status = guard_text_dev_handoff(
                str(info.get("answer", "")), is_owner=is_owner_channel(key),
                had_tool_attempts=bool(info.get("tool_uses")))
            if status:
                info["answer"] = guarded
                info["dev_handoff_status"] = status
        else:
            # [[dev: ...]] hand-off to 利贞 (ledger 0406): owner-only, strip the
            # marker from the answer before it is stored/spoken, dispatch async.
            try:
                from backend.target_entry import is_owner_channel

                if is_owner_channel(key):
                    from backend.target_dev_bridge import (
                        extract_dev_task, start_dev_task,
                    )

                    clean, task = extract_dev_task(str(info.get("answer", "")))
                    if task:
                        info["answer"] = clean
                        info["dev_task"] = task
                        note = start_dev_task(task)
                        if note:
                            info["answer"] = (clean + "\n" + note).strip()
            except Exception:
                pass
        try:
            s.save_session("console" if key == "console" else
                           "qq_" + key if key != "private" else "default")
        except Exception as exc:  # noqa: BLE001
            # 2026-10-13（ledger 0816）：这里原来静默 pass——会话写盘失败后
            # 表现是"上下文丢了/每轮像重新认识"，但日志里一个字都没有。
            print(f"[session] 保存失败 key={key} {type(exc).__name__}: {exc}",
                  flush=True)
        self._maybe_consolidate(key)
        try:
            answer = str(info.get("answer", ""))
            if key == "console" and answer:
                try:
                    from backend.target_signals import capture as _sig_capture

                    _sig_capture(str(text), channel=key)
                except Exception:
                    pass
                try:
                    from backend.target_scheduler_tools import skill_hint

                    hint = skill_hint(str(text), [u.get("name", "") for u in (info.get("tool_uses") or [])])
                    if hint:
                        info["answer"] = answer + hint
                except Exception:
                    pass
                try:
                    from backend.target_persona_loop import (
                        PENDING_FILE, maybe_open_refute_proposal)

                    s = self._session(key)
                    from backend.target_persona_loop import COGNITION_FILE

                    msg = ""
                    try:
                        msg = maybe_open_refute_proposal(
                            COGNITION_FILE.read_text(encoding="utf-8"),
                            str(text), pending_file=PENDING_FILE)
                    except Exception:
                        msg = ""
                    if msg:
                        info["answer"] = info.get("answer", "") + "\n\n（证伪联动）" + msg
                except Exception:
                    pass
            if key == "console" and notify_should(answer, info.get("tool_uses") or []):
                tools = [u.get("name", "") for u in (info.get("tool_uses") or [])]
                head = answer[:150].replace("\n", " ")
                msg = (f"任务完成汇报：{head}"
                       + (f"（工具：{'、'.join(tools)}）" if tools else ""))
                if notify_guard.allow("task", msg, cooldown=1800.0,
                                      max_per_day=8):
                    notify_push(msg)
        except Exception:
            pass
        # B4 (ledger 0437): idle right after a finished turn -> deliver due plans now
        self._run_due_plans()
        return info

    # auto-consolidation: every N turns on the private channel run the persona
    # loop once (idempotent by design — stamped items are never re-proposed).
    AUTO_CONSOLIDATE_EVERY = 15

    def _maybe_consolidate(self, key: str) -> None:
        try:
            if key not in ("private", "console"):
                return
            s = self._session(key)
            st = s.status()
            if int(st.get("history_turns", 0)) < 1:
                return
            counter = getattr(self, "_consolidate_counter", 0) + 1
            self._consolidate_counter = counter
            if counter % self.AUTO_CONSOLIDATE_EVERY != 0:
                return
            from backend.target_persona_loop import PersonaConsolidationLoop

            pc = PersonaConsolidationLoop(s.llm_turn, s.memory)
            future = asyncio.run_coroutine_threadsafe(pc.consolidate_once(),
                                                      self._loop)
            info = future.result(timeout=180)
            print(f"[auto-consolidate] {info.get('status')}", flush=True)
            if info.get("status") == "pending-approval":
                msg = ("有认知提炼待你确认：在 CLI 输入 /review-cognition "
                       "逐条 y/n 批准（写进元亨认知根基）")
                if notify_guard.allow("consolidate", msg,
                                      cooldown=12 * 3600, max_per_day=2):
                    notify_push(msg)
        except Exception as exc:
            print(f"[auto-consolidate] skip: {type(exc).__name__}", flush=True)

    def _schedule_loop(self) -> None:
        """Schedule-driven autonomy (ledger 0209): 30s fallback tick.

        B4 (ledger 0437): completed turns also call _run_due_plans() directly,
        so a due plan is delivered at the first idle moment instead of waiting
        for the next tick."""
        while True:
            time.sleep(30)
            try:
                self._run_due_plans()
            except Exception as exc:
                print(f"[schedule] loop err {type(exc).__name__}", flush=True)

    def _run_due_plans(self) -> None:
        """Process due plans once (B1 jitter + B3 priority + F4 backoff).

        Non-reentrant: a plan nudge is itself a turn(), whose trailing B4 call
        re-enters here — the nested call must return immediately."""
        if not self._sched_lock.acquire(blocking=False):
            return
        try:
            now = time.localtime()
            from backend import target_schedule as sched_mod

            due = []
            try:
                for plan in sched_mod._load():
                    if not plan.get("enabled", True):
                        continue
                    if not sched_mod.is_due(plan, now, plan.get("last_run", "")):
                        continue
                    if not sched_mod.jitter_ready(plan, now):
                        continue
                    due.append(plan)
            except Exception as exc:
                print(f"[schedule] load err {type(exc).__name__}", flush=True)
                return
            for plan in sched_mod.sort_due(due):
                try:
                    # F4 (ledger 0436): a repeatedly failing plan backs off
                    # (was: full LLM retry every 30s forever == "重复思考").
                    if sched_mod.in_backoff(plan, time.time()):
                        continue
                    steps = plan.get("steps") or []
                    body = (f"（计划表到点）你的例行计划：{plan.get('name')}。"
                            f"{'步骤：' + '；'.join(steps[:3]) if steps else ''}"
                            " 想做才做——需要我配合跑工具（如 summarize/consolidate/清理任务表）就说一声。")
                    self.turn(body, "private")
                    sched_mod.mark_run(plan.get("id", ""), now)
                    print(f"[schedule] ran {plan.get('name')}", flush=True)
                except Exception as exc:
                    err = type(exc).__name__
                    fc = sched_mod.mark_fail(plan.get("id", ""), err)
                    print(f"[schedule] run err {err} (fail #{fc})",
                          flush=True)
                    if fc == 3:
                        msg = (f"计划「{plan.get('name')}」连续失败 3 次，"
                               f"已自动暂停 24 小时：{err}")
                        if notify_guard.allow("schedule", msg,
                                              cooldown=12 * 3600,
                                              max_per_day=2):
                            notify_push(msg)
        finally:
            self._sched_lock.release()

    def _memory_upkeep_loop(self) -> None:
        """Weekly memory upkeep (ledger 0189/0301): belief time-decay + downgrades
        (cold) so L2 behaves like a real memory (unused items fade, nothing is
        ever deleted). Runs weekly with catch-up so a daemon that was down at the
        scheduled moment still runs it on the next start."""
        import pathlib

        stamp_file = pathlib.Path(_PROJECT) / "cache" / "memory_upkeep_last.json"
        while True:
            time.sleep(60)
            try:
                now = time.localtime()
                today = time.strftime("%Y-%m-%d")
                if self._upkeep_last == today:
                    continue
                last = ""
                try:
                    if stamp_file.exists():
                        last = str(json.loads(
                            stamp_file.read_text(encoding="utf-8")).get("date", ""))
                except Exception:
                    pass
                # weekly cadence WITH catch-up (ledger 0301): run when >=7 days
                # since the last run (or never run), regardless of day/hour —
                # the old "only Sunday 12:00" gate silently never fired when the
                # daemon was down at that moment.
                import datetime as _dt

                try:
                    due = (not last) or (
                        (_dt.date.fromisoformat(today)
                         - _dt.date.fromisoformat(last)).days >= 7)
                except Exception:
                    due = True
                if not due:
                    continue
                self._upkeep_last = today
                from backend.target_memory import TargetMemoryService

                svc = TargetMemoryService()
                reinforced = svc.review_reinforce()
                decayed = svc.apply_belief_decay()
                downgraded = svc.apply_belief_downgrades()
                stamp_file.write_text(
                    json.dumps({"date": today, "reinforced": reinforced,
                                "decayed": decayed, "downgraded": downgraded}),
                    encoding="utf-8")
                print(f"[memory-upkeep] {today} reinforced={reinforced} "
                      f"decayed={decayed} downgraded={downgraded}", flush=True)
                try:
                    from backend import snapshots

                    snapshots.create("daily")
                except Exception:
                    pass
                try:
                    from backend import intrinsic_drives

                    intrinsic_drives.decay()
                except Exception:
                    pass
                try:
                    from backend import communities

                    communities.build(force=True)
                except Exception:
                    pass
                try:
                    import asyncio as _asyncio

                    from backend import reflection

                    _asyncio.run(reflection.reflect())  # P5c 主动反思
                except Exception:
                    pass
            except Exception as exc:
                print(f"[memory-upkeep] skip: {type(exc).__name__}", flush=True)

    def console_turn_stream(self, text: str, on_delta,
                            pre_recall: list | None = None) -> dict:
        """Console (workbench) turn with token streaming via on_delta."""
        s = self._session("console")
        async def _run():
            return await s.run_turn(str(text), on_delta=on_delta,
                                    pre_recall=pre_recall)
        fut = asyncio.run_coroutine_threadsafe(_run(), self._loop)
        info = fut.result(timeout=300)
        try:
            s.save_session("console")
        except Exception:
            pass
        self._maybe_consolidate("console")
        # B4 (ledger 0437): deliver due plans at the first idle moment
        self._run_due_plans()
        return info

    def stream_chat(self, payload: dict, sink) -> str:
        """Dual-rail streaming chat (ledger 0204 + 0212): local Gemma first
        (llama.cpp 8081), Ollama Qwen fallback. Emits OpenAI-style SSE frames
        via `sink(text_chunk, reasoning_chunk=None)`; returns model used."""
        from backend.env_loader import ensure_env_loaded

        messages = payload.get("messages") or []
        ensure_env_loaded()
        import os

        key = os.getenv("DEEPSEEK_API_KEY", "")

        async def _stream_to(base_url, api_key, model):
            from backend.llm_stream import stream_openai_compatible

            async def _on(ev):
                if ev["kind"] == "delta":
                    if ev["stage"] == "content":
                        sink(ev["delta"], None)
                    else:
                        sink(None, ev["delta"])
                # done frame ignored here (client closes on [DONE])

            await stream_openai_compatible(
                base_url=base_url, api_key=api_key, model=model,
                messages=messages, on_event=_on,
                temperature=float(payload.get("temperature", 0.7)),
                max_tokens=int(payload.get("max_tokens", 1200) or 1200),
                reasoning_effort="none",
            )

        async def _try_cloud():
            await _stream_to("http://127.0.0.1:8081/v1/chat/completions",
                              key, "gemma-4-e4b")

        try:
            fut = asyncio.run_coroutine_threadsafe(_try_cloud(), self._loop)
            fut.result(timeout=300)
            return "gemma-4-e4b"
        except Exception:
            async def _try_local():
                await _stream_to(LOCAL_BASE, "", LOCAL_MODEL)

            fut = asyncio.run_coroutine_threadsafe(_try_local(), self._loop)
            fut.result(timeout=300)
            return LOCAL_MODEL

    def openai_chat(self, payload: dict) -> dict:
        messages = payload.get("messages") or []
        user_msgs = [m for m in messages if m.get("role") == "user"]
        text = str((user_msgs[-1] or {}).get("content", "")).strip()
        if not text:
            return {"error": "empty user message"}
        channel = str(payload.get("user") or "public")
        info = self.turn(text, channel=channel)
        return {
            "id": f"chatcmpl-yhlz-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": str(payload.get("model", "yhlz-yuanheng")),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant",
                            "content": info.get("answer", "")},
                "finish_reason": "stop",
            }],
        }


class _Handler(ConsoleHandler):
    runtime: DaemonRuntime = None  # type: ignore[assignment]

    def _ui_route(self, method: str) -> bool:
        """Workbench UI/API endpoints served on the daemon port (single entry)."""
        from backend.console_server import GET_UI, POST_UI

        p = self.path.split("?", 1)[0]
        if method == "GET":
            if p in GET_UI or p.startswith(("/live2d/", "/live2d-models/")):
                self.console_do_GET()
                return True
        if method == "POST" and p in POST_UI:
            self.console_do_POST()
            return True
        return False

    def _handle_stream_chat(self, payload: dict) -> None:
        """SSE streaming chat (ledger 0204): OpenAI-style frames."""
        import os

        from backend.env_loader import ensure_env_loaded

        ensure_env_loaded()
        messages = payload.get("messages") or []
        if not any(m.get("role") == "user" for m in messages):
            self._send(400, {"error": "empty user message"})
            return
        model = str(payload.get("model", "yhlz-yuanheng"))
        cid = f"chatcmpl-yhlz-{int(time.time() * 1000)}"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def _frame(obj: dict) -> bytes:
            return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")

        def _sink(text_chunk, reason_chunk):
            delta = {}
            if text_chunk:
                delta["content"] = text_chunk
            if reason_chunk:
                delta["reasoning_content"] = reason_chunk
            if delta:
                try:
                    self.wfile.write(_frame({
                        "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                        "model": model,
                        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                    }))
                    self.wfile.flush()
                except Exception:
                    pass

        try:
            used_model = self.runtime.stream_chat(payload, _sink)
        except Exception:
            used_model = model
        self.wfile.write(_frame({
            "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
            "model": used_model or model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, fmt, *args):
        return

    def _send(self, code: int, obj: Any) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/voice/jobs/"):
            from backend.target_voice_api import handle_get
            handle_get(self)
            return
        if self._ui_route("GET"):
            return
        if self.path.startswith(("/sing", "/songs")):
            self.console_do_GET()
            return
        if self.path.startswith("/health"):
            self._send(200, self.runtime.health())
        elif self.path.startswith("/autonomy"):
            # 自主可审计（0496）: 最近几次自主 tick 的决策（驱动值/选题/推送/原因）
            self._send(200, {"items": read_autonomy_ticks(20),
                             "decisions": notify_guard.recent(20)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self._ui_route("POST"):
            return
        if self.path.startswith(("/sing", "/songs")):
            # upload/sing/song routes read the raw body themselves
            self.console_do_POST()
            return
        if self.path.startswith("/voice/"):
            from backend.target_voice_api import MAX_BODY_BYTES, local_request
            if not local_request(self):
                self._send(403, {"error": "VOICE-LOCAL-ONLY"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self._send(400, {"error": "VOICE-INVALID-LENGTH"})
                return
            if not 0 <= length <= MAX_BODY_BYTES:
                self._send(413, {"error": "VOICE-BODY-TOO-LARGE"})
                return
        else:
            length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(400, {"error": "bad json"})
            return
        if self.path.startswith("/voice/"):
            from backend.target_voice_api import handle_post
            handle_post(self, payload)
            return
        if self.path == "/turn":
            text = str(payload.get("text", "")).strip()
            imgs = payload.get("images")
            imgs = [str(x) for x in imgs if x][:4] if isinstance(imgs, list) else None
            auds = payload.get("audio")
            auds = [str(x) for x in auds if x][:2] if isinstance(auds, list) else None
            if not text and not imgs and not auds:
                self._send(400, {"error": "empty text"})
                return
            # Channel identity auth (Step 1, 2026-09-29): source must match channel.
            from backend.channel_auth import ChannelAuthError, validate_channel
            try:
                channel = validate_channel(
                    str(payload.get("source", "")),
                    str(payload.get("channel", "console")),
                )
            except ChannelAuthError as exc:
                self._send(403, {"error": f"{exc.code}: {exc.detail}"})
                return
            try:
                info = self.runtime.turn(text, channel,
                                         images=imgs, audio=auds)
                self._send(200, info)
            except Exception as exc:
                self._send(500, {"error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            return
        if self.path == "/tool/schedule":
            from backend.target_scheduler_tools import schedule_handle
            try:
                pl = payload if isinstance(payload, dict) else {}
                method = str(pl.get("method") or pl.get("action") or "list")
                kw = dict(
                    name=pl.get("name", ""),
                    time_=pl.get("time") or pl.get("time_", ""),
                    cadence=pl.get("cadence", "daily"),
                    steps=pl.get("steps", ""),
                    plan_id=pl.get("plan_id", ""),
                    weekday=pl.get("weekday", ""),
                    day=pl.get("day", ""),
                    enabled=pl.get("enabled", ""),
                    fields_json=pl.get("fields_json", ""),
                )
                out = schedule_handle(method, **kw)
                self._send(200, {"ok": True, "output": out})
            except Exception as exc:
                self._send(500, {"error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            return
        if self.path in ("/v1/chat/completions", "/chat/completions"):
            if payload.get("stream"):
                self._handle_stream_chat(payload)
                return
            try:
                out = self.runtime.openai_chat(payload)
            except Exception as exc:
                self._send(500, {"error": f"{type(exc).__name__}: {str(exc)[:160]}"})
                return
            if "error" in out:
                self._send(400, out)
                return
            self._send(200, out)
            return
        if self.path == "/tts":
            # A4b (ledger 0454): synthesize one line -> WAV bytes for qq_bot
            from backend import gpu_lock
            from backend.console_server import (
                _settings_load, _synth, _wav_bytes,
            )

            if gpu_lock.chat_blocked():
                self._send(409, {"ok": False, "busy": True,
                                 "error": "元亨正在唱歌（GPU 互锁）"})
                return
            text = str(payload.get("text", "")).strip()[:200]
            if not text:
                self._send(400, {"error": "empty text"})
                return
            st = _settings_load()
            model = str(payload.get("model") or st.get("tts_model", "clone"))
            speaker = str(payload.get("speaker") or st.get("tts_speaker",
                                                          "Vivian"))
            try:
                audio, sr = _synth(model, text, speaker)
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"error": type(exc).__name__})
                return
            data = _wav_bytes(audio, sr)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/notifications":
            # owner-side poll: return queued Yuanheng activity then clear
            import pathlib

            try:
                entries = []
                if NOTIFY_FILE.exists():
                    entries = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
                NOTIFY_FILE.write_text("[]", encoding="utf-8")
                self._send(200, {"notifications": entries})
            except Exception as exc:
                self._send(500, {"error": type(exc).__name__})
            return
        self._send(404, {"error": "not found"})


def make_server(port: int, host: str, runtime: DaemonRuntime) -> ThreadingHTTPServer:
    _Handler.runtime = runtime
    return ThreadingHTTPServer((host, port), _Handler)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="元亨常驻 daemon（双轨+多渠道）")
    parser.add_argument("--port", type=int, default=8321)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-console", action="store_true",
                        help="(legacy) force console thread off")
    parser.add_argument("--console-port", type=int, default=0,
                        help="legacy separate console port (0=off; "
                             "workbench UI served on the main port)")
    parser.add_argument("--autonomy-hours", type=float, default=3.0,
                        help="self-initiated autonomy cadence (hours)")
    args = parser.parse_args()
    # 环境消毒（ledger 0815）：NO_PROXY 里带方括号的 IPv6（`[::1]`，DSH/Node 工具链
    # 会注入）会让 daemon 的 httpx 对**每个**请求抛 InvalidURL → 元亨在 QQ 上全哑
    # （2026-10-13 22:0x 事故）。启动即清掉并记录，避免"看起来像模型挂了"。
    try:
        from backend.env_loader import ensure_env_loaded, sanitize_proxy_env

        ensure_env_loaded()
        for _change in sanitize_proxy_env():
            print(f"[env] {_change}", flush=True)
    except Exception:
        pass
    runtime = DaemonRuntime(autonomy_seconds=max(60.0,
                                                 args.autonomy_hours * 3600))
    try:
        from backend.vector_memory import warm_reranker

        warm_reranker()  # background: reranker ready shortly after boot
    except Exception:
        pass
    try:
        from backend import intrinsic_drives

        intrinsic_drives.seed_defaults()  # P2: 老爹的期待 + 基础好奇
    except Exception:
        pass
    server = make_server(args.port, args.host, runtime)
    print(f"元亨 daemon: http://{args.host}:{args.port} "
          f"(OpenAI 兼容 {args.host}:{args.port}/v1/chat/completions)", flush=True)
    if not args.no_console and args.console_port and args.console_port > 0:
        try:
            from backend.console_server import serve_in_thread

            serve_in_thread(args.console_port, args.host, runtime)
        except Exception as exc:
            print(f"[console] 启动失败(跳过): {type(exc).__name__}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutdown", flush=True)
    finally:
        server.server_close()
        runtime.shutdown_voice()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
