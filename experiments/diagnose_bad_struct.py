# -*- coding: utf-8 -*-
"""查那 949 条"结构坏"到底是什么：工具样本？还是空/错位。"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
CORE = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")

rows = []
for fn in ("sft_persona_v10u_train.jsonl", "sft_persona_v10u_val.jsonl"):
    p = os.path.join(CORE, fn)
    if os.path.exists(p):
        rows += [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]

roles = Counter()
bad = []
for r in rows:
    msgs = r["messages"]
    rl = tuple(m.get("role") for m in msgs)
    roles[rl[0] if rl else "空"] += 1
    body = msgs[1:] if msgs and msgs[0].get("role") == "system" else msgs
    ok = bool(body) and body[0].get("role") == "user" and body[-1].get("role") == "assistant" \
        and all((m.get("content") or "").strip() for m in msgs)
    if not ok:
        bad.append((rl, msgs))

print("首条角色分布：%s" % dict(roles))
print("结构坏 %d 条" % len(bad))
shape = Counter(b[0] for b in bad)
print("\n坏样本的角色序列（前 8 种）：")
for s, n in shape.most_common(8):
    print("   %-52s ×%d" % (str(s)[:52], n))
print("\n样例：")
for rl, msgs in bad[:3]:
    print("   roles=%s" % (rl,))
    for m in msgs[:4]:
        c = (m.get("content") or "")
        print("      %-9s %r%s" % (m.get("role"), c[:60], " [tool_calls]" if "tool_calls" in m else ""))
    print()
