# -*- coding: utf-8 -*-
"""检查 daemon 的 /api/ POST 例外与 prompt 相关处理是否在位，缺则补。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "target_daemon.py")
t = io.open(P, encoding="utf-8").read()

i = t.find('startswith("/api/")')
print("--- do_POST 例外处 ---")
print(t[max(0, i - 100):i + 240])

print("\n--- 处理函数 ---")
for k in ("/api/prompt_restore", "/api/prompt_snapshot", "/api/prompt_versions"):
    print("%-24s %s" % (k, "有" if k in t else "没有"))

# 若例外没扩，就扩
if "prompt_restore" not in t[max(0, i - 200):i + 300]:
    old_candidates = [
        '("/api/try_turn", "/api/eval_run")',
        '("/api/try_turn",\n                 "/api/eval_run")',
    ]
    fixed = False
    for old in old_candidates:
        if old in t:
            t = t.replace(
                old,
                '("/api/try_turn", "/api/eval_run", "/api/prompt_restore",\n'
                '                 "/api/prompt_snapshot")', 1)
            fixed = True
            break
    if not fixed:
        # 兜底：按 /api/ 前缀判断改写成白名单
        import re
        m = re.search(r'if self\.path\.startswith\("/api/"\)[^:]*:\n', t)
        if m:
            seg = m.group(0)
            new = ('        if self.path.startswith("/api/") and not self.path.startswith(\n'
                   '                ("/api/try_turn", "/api/eval_run", "/api/prompt_restore",\n'
                   '                 "/api/prompt_snapshot")):\n')
            t = t.replace(seg, new, 1)
            fixed = True
    print("例外已" + ("扩好" if fixed else "⚠ 未能自动修改，需人工"))
    io.open(P, "w", encoding="utf-8").write(t)
else:
    print("例外已包含 prompt 路径")
