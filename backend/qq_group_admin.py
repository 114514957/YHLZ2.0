# -*- coding: utf-8 -*-
"""QQ 群白名单管理（工作台功能，2026-11-13）

工作台要能「列出元亨号加入的所有群 → 老爹勾选 → 生效」。

三件事：
1. `list_groups()`   —— 走 OneBot WS（NapCat 3001）调 `get_group_list`
2. `get_whitelist()` —— 读白名单：**环境变量 YHLZ_QQ_GROUPS 优先**（兼容老用法），
                        否则读 `config/qq_groups_whitelist.json`
3. `set_whitelist()` —— 写那份 JSON

`tools/qq_bot.py::_allowed_groups()` 也改成同样顺序读，所以**保存后下一句就生效**，
不用重启桥（它是每个事件都调一次）。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
CONFIG = _ROOT / "config" / "qq_groups_whitelist.json"


def _ws_url() -> str:
    """带 access_token 的 WS 地址（token 在 config/qqwatch.local.json，不进源码）。"""
    try:
        from backend.qq_token import ws_url  # noqa: PLC0415

        return ws_url()
    except Exception:  # noqa: BLE001
        return "ws://127.0.0.1:3001"


def _split(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,，;；\s]+", raw or "") if p.strip()]


def _read_file() -> dict:
    try:
        d = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def get_whitelist() -> dict:
    """返回 {'groups': [...], 'source': 'env'|'file'|'none'}。"""
    env = os.getenv("YHLZ_QQ_GROUPS", "").strip()
    if env:
        return {"groups": _split(env), "source": "env"}
    d = _read_file()
    groups = [str(x) for x in (d.get("groups") or []) if str(x).strip()]
    return {"groups": groups, "source": "file" if CONFIG.exists() else "none"}


def set_whitelist(groups: list[str]) -> dict:
    """保存白名单。空列表＝不限制（与桥的语义一致）。"""
    clean: list[str] = []
    for g in groups or []:
        s = str(g).strip()
        if s.isdigit() and s not in clean:
            clean.append(s)
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "groups": clean,
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": ("空列表 = 不限制（所有群）；由工作台「群聊白名单」写入。"
                 "环境变量 YHLZ_QQ_GROUPS 若已设置，则环境变量优先。"),
    }
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(CONFIG)
    return {"ok": True, "groups": clean, "saved_to": str(CONFIG)}


async def _call(action: str, params: dict | None = None, timeout: float = 8.0) -> Any:
    import websockets  # noqa: PLC0415

    echo = "yh-%d" % int(time.time() * 1000)
    req = {"action": action, "params": params or {}, "echo": echo}
    async with websockets.connect(_ws_url(), open_timeout=4) as ws:
        await ws.send(json.dumps(req, ensure_ascii=False))
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("等待 %s 响应超时" % action)
            raw = await asyncio.wait_for(ws.recv(), timeout=left)
            try:
                msg = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            if msg.get("echo") == echo:
                return msg


def list_groups(timeout: float = 8.0) -> dict:
    """取元亨号加入的全部群。失败时返回 ok=False + 原因（工作台照原样显示）。"""
    try:
        msg = asyncio.run(_call("get_group_list", {}, timeout))
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "error": "%s: %s" % (type(ex).__name__, str(ex)[:120]),
                "groups": [], "whitelist": get_whitelist()}
    if msg.get("status") != "ok" and msg.get("retcode") not in (0, None):
        return {"ok": False, "error": "OneBot 返回 %s" % msg.get("retcode"),
                "groups": [], "whitelist": get_whitelist()}
    raw = (msg.get("data") or [])
    groups = []
    for g in raw if isinstance(raw, list) else []:
        gid = str(g.get("group_id") or "")
        if not gid:
            continue
        groups.append({
            "id": gid,
            "name": g.get("group_name") or gid,
            "count": g.get("member_count") or g.get("max_member_count") or 0,
        })
    groups.sort(key=lambda x: -int(x.get("count") or 0))
    return {"ok": True, "groups": groups, "whitelist": get_whitelist(),
            "count": len(groups)}


def snapshot() -> dict:
    """工作台一次拿全：群列表 + 当前白名单。"""
    return list_groups()
