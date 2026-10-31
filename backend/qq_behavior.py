"""Explicit recipient and persistent owner-work policy for QQ ingress."""
from __future__ import annotations
import re

RELEASE = frozenset({"#解除", "#解除命令", "#结束工作"})

# 0830：退出任务模式。命中后必须同时清掉 owner_work，否则下一条普通聊天
# 还会被当成 #dev 派出去（老爹「#退出任务 后依然在派单」的根因）。
EXIT_TASK = ("#退出任务", "#退出任务模式", "#退出")

# 只有这些显式指令才把主人切进「任务通道」（owner_work=True）。
# 语音/档位/档案/发图之类的 # 命令不再顺带打开，避免任意 # 指令之后
# 聊天被自动派单。
DEV_LANE = ("#dev", "#任务派发", "#y", "#commit", "#n", "#push", "#cancel",
            "#cancle", "#取消", "#取消任务", "#answer", "#答")


def _match_head(body: str, heads) -> bool:
    for head in heads:
        if body == head or body.startswith(head + " "):
            return True
    return False


def dev_exit_command(text: str) -> bool:
    """True for the exit-task-mode commands (with or without a job id)."""
    return _match_head(str(text or "").strip(), EXIT_TASK)


def dev_lane_command(text: str) -> bool:
    """True for commands that legitimately belong to the dev task lane."""
    return _match_head(str(text or "").strip(), DEV_LANE)
_COMMAND = re.compile(r"^(?:[#＃/]|(?:请|帮我|给我|麻烦)?(?:执行|运行|重启|启动|关闭|打开|删除|清理|修改|生成|查询|搜索|播放|切换|禁言|撤回|踢出|更新|部署|修复|处理|检查))")


def command_not_for_bot(text: str, ats, bot: str, names, *, owner_command=False,
                        owner_work=False) -> bool:
    body = str(text or "").strip()
    targets = {str(q) for q in ats if str(q) not in {"all", "0"}}
    called = any(name and str(name) in body for name in names)
    if targets and bot not in targets:
        return bool(_COMMAND.match(body))
    named = re.match(r"^([^，,:：\n]{1,20})[，,:：]\s*(.*)$", body)
    if named and not any(name and name in named[1] for name in names) and _COMMAND.match(named[2]):
        return True
    if not _COMMAND.match(body):
        return False
    return not (bot in targets or called or owner_command or owner_work)


def work_enabled(state: dict, owner: str) -> bool:
    entry = (state.get("owner_work") or {}).get(str(owner)) or {}
    return bool(entry.get("enabled"))


def set_work(state: dict, owner: str, enabled: bool, channel: str) -> dict:
    import time
    result = dict(state)
    work = dict(result.get("owner_work") or {})
    work[str(owner)] = {"enabled": bool(enabled), "channel": str(channel),
                        "updated_at": time.time()}
    result["owner_work"] = work
    return result


def work_released(state: dict, owner: str) -> bool:
    work = state.get("owner_work") or {}
    return str(owner) in work and not bool((work[str(owner)] or {}).get("enabled"))
