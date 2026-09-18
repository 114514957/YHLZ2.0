"""[[dev: ...]] hand-off to 利贞 (opencode dev runner) — ledger 0406.

Shared by the QQ bridge (``tools/qq_bot.py``) and the daemon console/voice
path.  Extraction is pure and unit-testable; dispatch is fire-and-forget in a
daemon thread so a spoken reply is never blocked by the dev run.
"""
from __future__ import annotations

import re
import sys
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_DEV_RE = re.compile(r"\[\[dev[:：]\s*(.+?)\]\]", re.S)


def extract_dev_task(answer: str) -> tuple[str, str]:
    """Return ``(clean_answer, task)``; ``task`` is "" when no marker exists."""
    text = str(answer or "")
    tasks = [m.strip() for m in _DEV_RE.findall(text)]
    clean = _DEV_RE.sub("", text).strip()
    task = tasks[0] if tasks else ""
    return clean, task[:500]


def _dev_runner():
    """Import tools/dev_runner lazily (path setup included)."""
    tools_dir = str(_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import dev_runner  # noqa: PLC0415

    return dev_runner


def _notify(text: str) -> None:
    try:
        from backend.target_daemon import notify_push  # noqa: PLC0415

        notify_push(text)
    except Exception:
        pass


def _run_async(action: str, fn, note: str) -> None:
    """Run one dev action in a daemon thread; push a notification when done."""

    def _run() -> None:
        try:
            d = fn()
            status = str(d.get("status", ""))
            text = str(d.get("text", ""))[:280]
            if action == "push":
                _notify(f"[利贞] 推送：{text[:200]}")
                return
            label = {"awaiting": "有问题要问你", "done": "已完成",
                     "error": "出错", "running": "进行中"}.get(status, status)
            _notify(f"[利贞] {label}：{text or note}")
        except Exception as exc:  # noqa: BLE001
            _notify(f"[利贞] {action} 失败：{type(exc).__name__}")

    threading.Thread(target=_run, daemon=True, name=f"dev-{action}").start()


def start_dev_task(task: str) -> str:
    """Fire-and-forget: kick off ``dev_runner.start(task)`` in a thread."""
    task = str(task or "").strip()
    if not task:
        return ""
    _run_async("start", lambda: _dev_runner().start(task), task)
    return f"[利贞] 已开工：{task[:80]}（有进展我会通知你）"


def answer_dev_task(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return "用法：#a <给利贞的答复>"
    _run_async("answer", lambda: _dev_runner().answer(text), text)
    return "[利贞] 已收到答复，继续中…"


def commit_dev_task() -> str:
    def _commit() -> dict:
        d = _dev_runner()._load()
        msg = ("chore(remote-dev): " + str(d.get("task", ""))[:40]).strip()
        return _dev_runner().commit(msg)

    _run_async("commit", _commit, "")
    return "[利贞] 正在提交…"


def push_dev_task() -> str:
    _run_async("push", lambda: _dev_runner().push(), "")
    return "[利贞] 正在推送…"


def dev_status_text() -> str:
    try:
        d = _dev_runner()._load()
    except Exception as exc:  # noqa: BLE001
        return f"[利贞] 状态读取失败：{type(exc).__name__}"
    return (f"[利贞] 状态={d.get('status', '?')} | "
            f"任务={str(d.get('task', ''))[:60]} | "
            f"最近：{str(d.get('text', ''))[:120]}")


def handle_dev_command(text: str) -> str | None:
    """Owner-side dev console commands (#dev/#a/#ds/#y/#n/#push).

    Returns the reply text, or None when the text is not a dev command.
    """
    low = str(text or "").strip().lower()
    stripped = str(text or "").strip()
    if low in ("#devstatus", "#ds"):
        return dev_status_text()
    if low in ("#y", "#commit"):
        return commit_dev_task()
    if low == "#n":
        return "[利贞] 好的，不提交，改动留在工作区。"
    if low == "#push":
        return push_dev_task()
    for prefix in ("#a", "#答"):
        if stripped == prefix:
            return "用法：#a <给利贞的答复>"
        if stripped.startswith(prefix + " "):
            return answer_dev_task(stripped[len(prefix):])
    if stripped == "#dev" or stripped.startswith("#dev "):
        task = stripped[4:].strip()
        if not task:
            return "用法：#dev <任务>"
        return start_dev_task(task)
    return None


__all__ = [
    "answer_dev_task",
    "commit_dev_task",
    "dev_status_text",
    "extract_dev_task",
    "handle_dev_command",
    "push_dev_task",
    "start_dev_task",
]
