# -*- coding: utf-8 -*-
"""策划前的现状盘点（只读）：所有 LLM 调用点、当前指向、可用的密钥与配置。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

print("=" * 70)
print("① 所有 LLM 调用点（谁在发请求）")
print("=" * 70)
PAT = re.compile(r"(api\.deepseek\.com|127\.0\.0\.1:8081|/v1/chat/completions|build_openai_compatible_llm_turn)")
for p in sorted(glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True)):
    if any(x in p for x in ("\\cache\\", "\\dist\\", "\\.venv", "\\venv")):
        continue
    try:
        t = io.open(p, encoding="utf-8", errors="replace").read()
    except Exception:  # noqa: BLE001
        continue
    hits = [ln.strip() for ln in t.splitlines() if PAT.search(ln)]
    if hits:
        rel = os.path.relpath(p, ROOT)
        print("\n  %s（%d 处）" % (rel, len(hits)))
        for h in hits[:4]:
            print("     " + h[:110])

print()
print("=" * 70)
print("② 当前 provider 配置（daemon / orchestrator 默认值）")
print("=" * 70)
for rel, pats in (
        ("backend/target_daemon.py", ("LOCAL_BASE", "LOCAL_MODEL", "provider")),
        ("backend/target_orchestrator.py", ("deepseek", "gemma", "def build_openai")),
):
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    t = io.open(p, encoding="utf-8", errors="replace").read()
    print("\n  %s" % rel)
    for ln in t.splitlines():
        s = ln.strip()
        if any(x in s for x in pats) and "=" in s and len(s) < 140:
            print("     " + s)

print()
print("=" * 70)
print("③ 环境里的密钥（只打指纹，不打明文）")
print("=" * 70)
for k in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
          "DASHSCOPE_API_KEY", "MOONSHOT_API_KEY", "ZHIPU_API_KEY", "YHLZ_LLM_KEY"):
    v = os.environ.get(k) or ""
    if v:
        print("     %-20s 存在，长度 %d，前缀 %s…" % (k, len(v), v[:4]))
    else:
        print("     %-20s 不在" % k)

print()
print("=" * 70)
print("④ 配置目录里与 provider 有关的文件")
print("=" * 70)
for p in sorted(glob.glob(os.path.join(ROOT, "config", "*.json"))):
    name = os.path.basename(p)
    if any(x in name.lower() for x in ("llm", "provider", "model", "api", "prompt")):
        try:
            d = json.load(io.open(p, encoding="utf-8"))
            keys = list(d)[:8] if isinstance(d, dict) else "(list)"
        except Exception:  # noqa: BLE001
            keys = "（读不了）"
        print("     %-32s %s" % (name, keys))

print()
print("=" * 70)
print("⑤ 工作台现有模块（前端卡片标题）")
print("=" * 70)
idx = os.path.join(ROOT, "assets", "webui", "index.html")
if os.path.exists(idx):
    t = io.open(idx, encoding="utf-8", errors="replace").read()
    cards = re.findall(r"<h3>([^<]{1,24})</h3>", t)
    print("     卡片 %d 个：%s" % (len(cards), "、".join(cards)))
    panels = re.findall(r'data-panel="([a-z]+)"', t)
    print("     页签：%s" % panels)
