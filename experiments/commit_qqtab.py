# -*- coding: utf-8 -*-
"""提交 QQ 登录修复 + QQ 独立菜单。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_qqtab.txt")
L = [
    "fix(workbench): QQ 登录唤起修复 + QQ 独立菜单",
    "",
    "老爹反馈：①工作站 QQ 登录唤起失败 ②QQ 提示词/qqm 之类别一股脑塞右菜单",
    "",
    "① 根因：工作台的二维码接口只认 NapCat **无头模式**写出的 qrcode.png；",
    "   而我们的 NapCat 是**带窗口登录**的 → 永远 404 → 看着像「唤起失败」。",
    "   - 新增 control 动作 `napcat_window`：用 `cmd /c start` 打开可见的",
    "     qqwatch/shell/launcher-user.bat <uin>（可扫码）；路径做了两级候选，避免再算错目录",
    "   - 二维码 404 时前端不再显示破图，改为明确指引 + 状态轮询",
    "",
    "② 新增顶级「QQ」页签：元亨 QQ / 群聊白名单 / 群情报 三张卡由 JS 搬进该页",
    "   （DOM 移动，不改卡片内容），不再挤在状态页右栏",
    "",
    "验证：napcat_window 返回 ok 并弹出窗口；页面含 QQ 页签、两个按钮、状态位、搬卡脚本。",
]
io.open(MSG, "w", encoding="utf-8").write("\n".join(L) + "\n")
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-60:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-120:])
