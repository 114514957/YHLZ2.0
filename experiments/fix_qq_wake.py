# -*- coding: utf-8 -*-
"""QQ 登录唤起修复 + QQ 独立菜单（台账 1261）。

问题：工作台「唤起登录」只调 napcat_login，而二维码接口只认 NapCat **无头模式**
写出的 `qrcode.png`；老爹的 NapCat 是**带窗口**登录的 → 永远 404 → 看着像"唤起失败"。

三处改动：
  ① 新增 control 动作 `napcat_window`：用 `cmd /c start` 打开 `launcher-user.bat`（可见窗口，可扫码）
  ② 二维码 404 时前端给明确指引（不再显示破图）；并自动轮询登录状态
  ③ 新建「QQ」顶级菜单，把 元亨 QQ / 群聊白名单 / 群情报 三张卡搬过去（DOM 移动，不动内容）
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

# ── ① 后端：新增 napcat_window 动作 ───────────────────────────────
P1 = os.path.join(ROOT, "backend", "console_server.py")
t = io.open(P1, encoding="utf-8").read()
if '"napcat_window"' not in t:
    anchor = '        if action in ("napcat_login", "qq_switch"):'
    add = '''        if action == "napcat_window":
            # 2026-11-16（台账 1261）：打开**可见的** NapCat 登录窗口（可扫码）。
            # 我们的 NapCat 是带窗口登录的，不会写 qrcode.png，所以二维码接口必然 404——
            # 与其让老爹以为"唤起失败"，不如直接给他一个能扫码的窗口。
            try:
                import subprocess as _sp
                shell = _PROJECT_ROOT.parent / "qqwatch" / "shell"
                bat = shell / "launcher-user.bat"
                if not bat.exists():
                    return {"ok": False, "error": "找不到 %s" % bat}
                uin = str(body.get("uin", "") or BOT_UIN)
                _sp.Popen(
                    ["cmd", "/c", "start", "", "launcher-user.bat", uin],
                    cwd=str(shell), close_fds=True,
                    creationflags=getattr(_sp, "CREATE_NEW_CONSOLE", 0))
                _log("control", "napcat_window %s" % uin)
                return {"ok": True,
                        "note": "已打开 NapCat 登录窗口（元亨号 %s）：在窗口里扫码登录" % uin}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": "%s: %s"
                        % (type(exc).__name__, str(exc)[:120])}
'''
    assert anchor in t
    t = t.replace(anchor, add + anchor, 1)
    io.open(P1, "w", encoding="utf-8").write(t)
    print("① 后端已加 napcat_window")
else:
    print("① 已有 napcat_window")
