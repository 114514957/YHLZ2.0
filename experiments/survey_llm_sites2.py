# -*- coding: utf-8 -*-
"""补盘：密钥指纹 / provider 配置 / 工作台模块 / 真实 LLM 现场数（排除 artifacts 快照）。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

print("=== ① 环境密钥（只指纹）===")
found = False
for k in sorted(os.environ):
    if any(x in k.upper() for x in ("DEEPSEEK", "OPENAI", "ANTHROPIC", "DASHSCOPE",
                                     "MOONSHOT", "ZHIPU", "QWEN", "SILICON", "YHLZ_LLM")):
        v = os.environ.get(k) or ""
        print("   %-26s 长度 %-4d 前缀 %s…" % (k, len(v), v[:4]))
        found = True
if not found:
    print("   （没有找到任何大模型密钥环境变量）")

print("\n=== ② backend/config.py 里的 LLM 设置 ===")
p = os.path.join(ROOT, "backend", "config.py")
t = io.open(p, encoding="utf-8", errors="replace").read()
for ln in t.splitlines():
    s = ln.strip()
    if any(x in s.lower() for x in ("deepseek", "llm", "api_key", "base_url", "model")):
        print("   " + s[:120])

print("\n=== ③ llm_hybrid_compose 现状 ===")
p = os.path.join(ROOT, "backend", "llm_hybrid_compose.py")
if os.path.exists(p):
    t = io.open(p, encoding="utf-8", errors="replace").read()
    for ln in t.splitlines()[:40]:
        s = ln.strip()
        if s and not s.startswith("#"):
            print("   " + s[:120])

print("\n=== ④ 真实 LLM 现场（backedn/tools，排除 artifacts）===")
PAT = re.compile(r"127\.0\.0\.1:8081|api\.deepseek\.com")
sites = []
for p in glob.glob(os.path.join(ROOT, "backend", "*.py")) + \
        glob.glob(os.path.join(ROOT, "tools", "*.py")):
    if "test_" in os.path.basename(p):
        continue
    t = io.open(p, encoding="utf-8", errors="replace").read()
    n = len(PAT.findall(t))
    if n:
        sites.append((os.path.relpath(p, ROOT), n))
for rel, n in sorted(sites, key=lambda x: -x[1]):
    print("   %-42s %d 处" % (rel, n))
print("   合计 %d 个文件 / %d 处引用" % (len(sites), sum(n for _, n in sites)))

print("\n=== ⑤ 工作台模块 ===")
idx = os.path.join(ROOT, "assets", "webui", "index.html")
t = io.open(idx, encoding="utf-8", errors="replace").read()
panels = re.findall(r'data-panel="([a-z]+)"', t)
cards = re.findall(r"<h3>([^<]{1,26})</h3>", t)
print("   页签：%s" % panels)
print("   卡片 %d 个：%s" % (len(cards), "、".join(cards)))
