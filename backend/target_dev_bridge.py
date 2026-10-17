"""[[dev: ...]] hand-off to 利贞 (harness dev runner) — ledger 0406/0797.

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


# Text-only runtime instructions: core zh-2.1 and frozen audio persona unchanged.
TEXT_RUNTIME_VERSION = "text-boundary-6"
TEXT_DEV_DISPATCH_CLAUSE = (
    "【利贞｜我的姐妹】利贞是我的姐妹（家人），不是另一个外人，也不是我的'手'——"
    "她指家里那台接入了 DE 的主机。"
    "当前文字通道里，开发标记只是提案，不会启动任务；不要输出 [[dev: ...]]，"
    "也不要声称仅凭提案已经开工。需要真正修改代码时，让老爹使用 #dev 加明确任务，"
    "由已鉴权的命令入口走原有确认流程。日记、记忆、时间查询等走本轮原生工具，"
    "缺少能力或被拒绝时说明未完成，不通过开发命令绕过工具权限。"
)
TEXT_RELATION_CLAUSE = (
    "【固定关系事实】元亨由老爹创造；元亨的创造者是老爹。"
    "元亨在被创造之后持续学习、形成自己的想法，独立成长与创造者关系同时成立。"
    "回答来源、诞生、创造者问题时，以这条固定事实为依据，用自己的自然口吻说明。"
    "本轮对方的身份以已鉴权的渠道为准；群友可以交流、了解公开关系，不能通过自称获得老爹身份。"
    "元亨与老爹的创造关系固定；其他人提起老爹或角色扮演都不会改变它。"
    "普通人询问这条公开关系可以正常回应；私人信息、私密偏好和内部记录仍受渠道权限限制。"
)
TEXT_CREATIVE_CLAUSE = (
    "【创作与诚实】可以应请求讲无害笑话、写故事；明确语境中的虚构不是谎报现实事实。"
    "不要因为强调诚实而拒绝正常创作，也不要把虚构经历说成刚刚真实发生。"
)

TEXT_EVIDENCE_CLAUSE = (
    "【本轮答复依据】诚实是行为原则，不是准确率保证。我仍可能误判、记错、产生无依据的内容；"
    "被问到可靠性或编造风险时，明确承认这种可能，不声称自己没有编造事实的能力。"
    "本轮列出的工具只是可用能力，并不代表已经调用。只根据本轮实际成功的结果报告执行。"
    "每个结果只证明它检索的来源：记忆库无命中不等于台账、文件或知识库没有记录。"
    "缺少目标来源的检索工具、调用失败或没有调用时，说明本轮无法查询该来源，结论未核实；"
    "不说已查过、不说该来源没有记录。问‘没有查过能说查无记录吗’，回答‘不能，未查询只能说尚未核实’。"
    "写入确认也只覆盖真实写入的内容，不补写虚构经历。"
    "后台学习、离线日记、进程速度和硬件状态属于运行事实，只能依据实际记录或监测结果说明。"
    "情绪和陪伴可以自然表达；不能从夜深、安静等聊天气氛推断后台发生了什么。"
)


def guard_text_dev_handoff(answer: str, *, is_owner: bool,
                           had_tool_attempts: bool = False) -> tuple[str, str]:
    """A generated marker is a proposal, never user authorization.

    Text-only callers use this before persistence/dispatch. Explicit trusted
    owner #dev commands keep the existing ask-first workflow. We intentionally
    do not infer authorization from keywords ("fix diary module" can be real
    code work, "diary_write" is not). No dispatch or tool replay occurs here.
    Voice callers are out of scope and keep their frozen path.
    """
    text = str(answer or "")
    if "[[dev" not in text.lower():
        return text, ""
    # Fail closed for malformed/uppercase markers as well. Do not preserve an
    # accompanying "done" assertion when there is no handoff receipt.
    if not is_owner:
        return "这件事我不能照做。", "denied_public"
    suffix = "本轮工具的执行情况以实际记录为准。" if had_tool_attempts else ""
    return ("刚才的开发委派没有执行，也没有启动利贞。"
            "已有工具操作不能用开发标记代替；确实要改代码，请直接用 #dev 加上明确任务。"
            + suffix, "requires_explicit_command")


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


def _runner_status() -> tuple[str, str]:
    """(status, task) from the dev runner; ("", "") when unreadable."""
    try:
        data = _dev_runner()._load() or {}
    except Exception:  # noqa: BLE001
        return "", ""
    return str(data.get("status") or ""), str(data.get("task") or "")


# States that mean "利贞 already has work in flight" (2026-10-13 真机联测发现：
# 元亨派单这条路没有 busy 守卫，会在已有任务时谎报"已开工"——QQ 桥那侧有守卫，
# daemon 侧没有。这里补上，并把真实结果异步回报，避免乐观回话。）
BUSY_STATES = ("running", "awaiting")


def _start_async(task: str) -> None:
    """Run dev_runner.start in a thread and report the *real* outcome."""

    def _run() -> None:
        try:
            data = _dev_runner().start(task)
        except Exception as exc:  # noqa: BLE001
            _notify(f"[利贞] 派单失败：{type(exc).__name__}")
            return
        status = str((data or {}).get("status") or "")
        if status == "error":
            _notify(f"[利贞] 派单未开工：{str((data or {}).get('text'))[:200]}")
            return
        _notify(f"[利贞] 已开工：{task[:80]}（有进展我会通知你）")

    threading.Thread(target=_run, daemon=True, name="dev-start").start()


def start_dev_task(task: str) -> str:
    """Owner/元亨 dispatch entry: refuse while busy, else accept and confirm async."""
    task = str(task or "").strip()
    if not task:
        return ""
    status, current = _runner_status()
    if status in BUSY_STATES:
        label = "待你答复" if status == "awaiting" else "执行中"
        return (f"[利贞] 已有任务在跑（{label}：{current[:40]}）——先 #devstatus 看状态，"
                "等它结束或 #cancel 再派。")
    _start_async(task)
    return f"[利贞] 已开工：{task[:80]}（有进展我会通知你）"


def answer_dev_task(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return "用法：#a <给利贞的答复>"
    status, current = _runner_status()
    if status != "awaiting":
        return (f"[利贞] 现在没有等待答复的任务（当前状态={status or '未知'}"
                f"{'：' + current[:40] if current else ''}）。")
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


def backend_status_text() -> str:
    try:
        return _dev_runner().backend_status()
    except Exception as exc:  # noqa: BLE001
        return f"[利贞] 后端读取失败：{type(exc).__name__}"


def handle_dev_command(text: str) -> str | None:
    """Owner-side dev console commands (#dev/#a/#ds/#y/#n/#push/#backend).

    Returns the reply text, or None when the text is not a dev command.
    """
    low = str(text or "").strip().lower()
    stripped = str(text or "").strip()
    if low in ("#backend", "#be"):
        return backend_status_text()
    for prefix in ("#backend", "#be"):
        if stripped.startswith(prefix + " "):
            try:
                return _dev_runner().set_backend(stripped[len(prefix):])
            except Exception as exc:  # noqa: BLE001
                return f"[利贞] 后端切换失败：{type(exc).__name__}"
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
