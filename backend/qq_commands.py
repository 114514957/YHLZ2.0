# -*- coding: utf-8 -*-
"""QQ 的 `#` 指令层（硬控制）：对话档位 + 退出任务 + 菜单。

背景（2026-11-16 台账 1279）：这套逻辑原本只在**全量桥** `tools/qq_bot.py` 里，
而线上跑的是 **Bridge Lite**，没有 `#` 处理 → 老爹的「#缄默」等硬控制全部失效。
daemon 是所有通道的汇合点，在这里实现一份，lite/full 都生效。

档位（沿用 2026-10-11 定义）：
  lively  活泼：保持现状（默认）
  reserved 内敛：群里只有 @ 她 或提到「元亨」才回
  silent  缄默：群里彻底沉默（@ 也不回），私聊也静默；**# 指令与系统通知不受影响**

状态落盘：cache/qq_mode.json（重启后保持）
"""
from __future__ import annotations

import io
import json
import re
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "cache", "qq_mode.json")
LABELS = {"lively": "活泼", "reserved": "内敛", "silent": "缄默"}
ALIASES = {
    "#活泼": "lively", "#lively": "lively",
    "#内敛": "reserved", "#reserved": "reserved",
    "#缄默": "silent", "#静默": "silent", "#silent": "silent", "#mute": "silent",
}

__all__ = ["handle", "mode", "set_mode", "should_reply", "menu"]


def _load() -> dict:
    try:
        with io.open(STATE, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def mode() -> str:
    m = str(_load().get("mode") or "lively")
    return m if m in LABELS else "lively"


def set_mode(m: str) -> str:
    if m not in LABELS:
        m = "lively"
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with io.open(STATE, "w", encoding="utf-8") as f:
            json.dump({"mode": m, "at": time.time()}, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass
    return m


def menu() -> str:
    return ("# 指令：\n"
            "#活泼  正常对话（默认）\n"
            "#内敛  群里只有 @ 我或提到「元亨」才回\n"
            "#缄默  彻底沉默（@ 也不回；# 指令仍可用）\n"
            "#档位  看当前档位\n"
            "#退出任务  退出任务模式（清掉工作状态）")


_AT = re.compile(r"\[\[at:\s*\d+\]\]")
_ATNAME = re.compile(r"^\s*@[^\s#]{1,24}\s*")


def _normalize(text: str) -> str:
    """去掉群消息里的 @ 前缀：`[[at: 3655185302]] #缄默` → `#缄默`。"""
    s = _AT.sub("", str(text or ""))
    s = _ATNAME.sub("", s)
    return s.strip()


def _is_owner(channel: str) -> bool:
    ch = str(channel or "")
    return ch.startswith("qq_p") or ch == "console"


def handle(text: str, channel: str = "") -> dict:
    """返回 {handled, reply, cmd, mode}；非指令返回 {}。"""
    raw = _normalize(text)
    if not raw.startswith("#"):
        # 非指令：按档位决定要不要回（缄默全静音；内敛群里没 @/没提名字就不回）
        return {"mute": not should_reply(channel, raw), "mode": mode()}

    low = raw.split()[0].lower() if raw.split() else raw.lower()
    first = raw.split()[0]

    if low in ("#档位", "#mode", "#status"):
        m = mode()
        return {"handled": True, "cmd": "mode", "mode": m,
                "reply": "当前档位：%s（%s）" % (LABELS[m], m)}

    for k, m in ALIASES.items():
        if first == k or low == k.lower():
            # 2026-11-16（台账 1280）：群聊也允许改档——老爹就是在群里发的；
            # 群里只有 @ 她或点名才有机会看到这句，实际不会被人乱用。
            set_mode(m)
            extra = ""
            if m == "silent":
                extra = "（@ 也不回，私聊同步静默；# 指令仍可用）"
            elif m == "reserved":
                extra = "（群里只有 @ 我或提到「元亨」才回）"
            return {"handled": True, "cmd": "mode", "mode": m,
                    "reply": "已切到「%s」%s" % (LABELS[m], extra)}

    if low in ("#帮助", "#help", "#菜单", "#menu"):
        return {"handled": True, "cmd": "menu", "reply": menu(), "mode": mode()}

    if first in ("#退出任务", "#退出"):
        # 只确认；工作状态由上层（如有）清理
        return {"handled": True, "cmd": "exit_task", "mode": mode(),
                "reply": "已退出任务模式。"}

    # 未知 # 指令：不派单、不调模型（2026-10-20 的教训）。
    # 群里不出声（免得群友乱打 # 换来一屏菜单），私聊才给菜单。
    if str(channel or "").startswith("qq_g"):
        return {"handled": True, "cmd": "unknown", "mode": mode(), "reply": ""}
    return {"handled": True, "cmd": "unknown", "mode": mode(),
            "reply": "未知指令：%s\n\n%s" % (first, menu())}


def should_reply(channel: str, text: str) -> bool:
    """内敛档：群里只有 @ 或提到名字才回。缄默档：一律不回（指令已在 handle 里处理）。"""
    m = mode()
    if m == "silent":
        return False
    if m == "reserved":
        ch = str(channel or "")
        if not ch.startswith("qq_g"):
            return True
        s = str(text or "")
        return ("元亨" in s) or ("[[at:" in s)
    return True
