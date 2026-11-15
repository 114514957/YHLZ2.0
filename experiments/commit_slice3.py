# -*- coding: utf-8 -*-
"""提交第三片（星图/对话台/形象）+ 汇总。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_slice3.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "feat(workbench): 第三片——记忆星图、对话台（含会话隔离修复）、形象区\n\n"
    "④ 记忆星图（1259）\n"
    "- backend/memory_graph.py：节点=l2_items(active)，大小按 importance、\n"
    "  颜色按 type、形状按 role；边=共享关键词（退化时用文本 2-gram）\n"
    "- GET /api/memory_graph?limit=&min_importance=\n"
    "- 卡：canvas 力导向（无外部依赖）+ 按角色过滤 + 搜索高亮 + 点节点看原文\n"
    "- 实测：400 节点 / 626 边；角色 owner 80、engineering 138、her 87、unknown 95\n\n"
    "⑤ 对话台（1260）\n"
    "- 复用 /sessions、/history?session=、/talk；左侧会话列表、右侧记录与输入\n"
    "- 修了一个真 bug：/history 写死读 console 会话 → 切会话看到的永远是同一份记录。\n"
    "  改为按 ?session= 取对应会话；实测 console 20 条 / wb_test 0 条（已隔离）\n\n"
    "⑥ 形象区（1261）\n"
    "- 首屏嵌 iframe 指向 /avatar.html，另留「在新窗口打开」\n"
    "- 按老爹定论：原来的独立窗口照旧，两边都留\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-80:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-120:])
r = subprocess.run(["git", "log", "--oneline", "-4"], cwd=ROOT, capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
print(r.stdout)
