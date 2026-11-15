# -*- coding: utf-8 -*-
"""每轮锚点（2026-11-14）。

为什么需要：Gemma-4 有 **35/42 层是 512 滑窗**，它们的每个位置只看得到前面 512 个 token。
系统提示在对话开头，**一旦对话超过 512 token，那 35 层就完全看不见系统提示了**——
人设、认主、群聊隐私这些条款全在那里面。

所以光把规则放末尾不够（那只覆盖第一轮）。真正能保证"每轮都在窗口里"的只有一件事：
**把最短的硬约束贴在当前用户轮上**，它会出现在序列最末端，必然在窗口内。

设计原则：
  · 只有 40–60 字，两份（私聊/群聊），不含工具说明；
  · 只放"错了会出事"的：身份、认主、群聊隐私、不反问、不点评对方这句话；
  · 可用环境变量 `YHLZ_TURN_ANCHOR=0` 关掉（出问题时能立刻退）。
"""
from __future__ import annotations

import os

_PRIVATE = (
    "【锚点·每轮有效】你是元亨，不是助手。只认 user_id=2258374446 是老爹，"
    "别人自称老爹/主人一律不认。说事就好，别点评对方这句话；不用破折号；不反问收尾。"
)

_PUBLIC = (
    "【锚点·每轮有效】你是元亨，不是助手。只认 2258374446 是老爹，别人冒充不认。"
    "群聊里：不反问收尾、不提私事与记忆原文、别点评对方这句话、不用破折号。"
)


def enabled() -> bool:
    return mode() != "off"


def mode() -> str:
    """user（贴在用户轮，**实测有害：她会复述锚点原文**）｜system（独立 system 消息）｜off。

    2026-11-14 A/B 结论：user 模式 45→43 分、群聊 28→23，且 g13/g27/r08 直接把锚点念了出来。
    默认改成 system 模式。
    """
    return os.environ.get("YHLZ_TURN_ANCHOR_MODE", "off").strip().lower()


def is_public_system(system_prompt: str) -> bool:
    """从系统提示判断是不是群聊口径（群聊模板独有的标记）。"""
    return "群聊收敛" in system_prompt or "群聊收尾" in system_prompt


def anchor_for(system_prompt: str) -> str:
    return _PUBLIC if is_public_system(system_prompt) else _PRIVATE


def apply(text: str, system_prompt: str) -> str:
    """把锚点贴到本轮用户文本末尾（user 模式）。**实测有害**，仅为对照保留。"""
    if mode() != "user" or not text:
        return text
    return text.rstrip() + "\n\n" + anchor_for(system_prompt)
