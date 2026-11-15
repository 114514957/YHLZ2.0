# -*- coding: utf-8 -*-
"""把 attn_implementation 的默认与配置改成 eager（Gemma4AudioModel 不支持 sdpa）。"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

p = os.path.join(ROOT, "dist", "material_v13", "train_v13.py")
t = io.open(p, encoding="utf-8").read()
before = t
t = t.replace('cfg.get("attn_implementation", "sdpa")',
              'cfg.get("attn_implementation", "eager")')
t = t.replace('or "sdpa"', 'or "eager"')
io.open(p, "w", encoding="utf-8").write(t)
print("trainer 改动：%s" % ("有" if t != before else "无"))

for q in (os.path.join(ROOT, "dist", "material_v13", "config", "finetune.gemma4.v13.json"),
          os.path.join(ROOT, "dist", "_v13_pack", "smoke60.json")):
    if not os.path.exists(q):
        print("缺 %s" % q)
        continue
    c = json.load(io.open(q, encoding="utf-8"))
    c["attn_implementation"] = "eager"
    io.open(q, "w", encoding="utf-8").write(json.dumps(c, ensure_ascii=False, indent=2))
    print("改好：%s（attn=%s）" % (os.path.basename(q), c["attn_implementation"]))

# 确认训练器里现在没有残留 sdpa 默认
rest = [ln.strip() for ln in io.open(p, encoding="utf-8") if "attn_implementation" in ln]
print("\n训练器相关行：")
for ln in rest[:6]:
    print("   " + ln[:110])
