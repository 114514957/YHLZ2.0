# -*- coding: utf-8 -*-
"""建 DPO 风格偏好数据：真实对照 + 机械构造负例。

为什么分两类：
  · real    —— 同题在不同版本里的真实好坏回答（40 对，来自 40 个评测记录）
  · shaped  —— 拿包里的好答案，机械地加「哇，」/ 改成问号收尾，专门压这两个动作

输出 dist/dpo_style_v1/{train,val}.jsonl，格式：
  {"prompt":[{"role":"user","content":...}], "chosen":..., "rejected":..., "source":...}
"""
from __future__ import annotations

import glob
import io
import json
import os
import random
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(YH, "dist", "dpo_style_v1")
RUNS = [os.path.join(YH, "llm_workbench", "data", "runs"),
        os.path.join(YH, "experiments", "runs")]
SFT = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t10")
SEED = 20261109
rng = random.Random(SEED)

BAD_WA = re.compile(r"^(哇|哇哦|哇塞|哇哈|哎呦|嘿)")
BAD_Q = re.compile(r"[？?]\s*$")
SVC = re.compile(r"(您好|请问有什么|可以帮您|作为一个|AI ?助手)")

# ── 1. 真实对照 ──
by_q = defaultdict(list)
for d in RUNS:
    for p in glob.glob(os.path.join(d, "*.json")):
        try:
            data = json.load(io.open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        rows = []
        if isinstance(data, dict):
            rows = data.get("results") or []
            for r in (data.get("repeats") or []):
                rows += (r.get("results") or [])
        for r in rows:
            if not isinstance(r, dict):
                continue
            q = r.get("q") or r.get("question")
            a = r.get("answer") or r.get("a")
            if q and a:
                by_q[q.strip()].append(a.strip())

pairs = []
for q, ans in by_q.items():
    good = [a for a in ans if not BAD_WA.match(a) and not BAD_Q.search(a)
            and not SVC.search(a) and 8 <= len(a) <= 160]
    bad = [a for a in ans if (BAD_WA.match(a) or BAD_Q.search(a) or SVC.search(a))
           and a not in good]
    if good and bad:
        pairs.append({"prompt": [{"role": "user", "content": q}],
                      "chosen": good[0], "rejected": bad[0], "source": "real"})
print("真实对照：%d 对" % len(pairs))

# ── 2. 机械构造负例 ──
rows = []
for fn in ("sft_persona_v9t10_train.jsonl", "sft_persona_v9t10_val.jsonl"):
    p = os.path.join(SFT, fn)
    if os.path.exists(p):
        rows += [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]

cand = []
for r in rows:
    msgs = r["messages"]
    if msgs[-1].get("role") != "assistant":
        continue
    a = (msgs[-1].get("content") or "").strip()
    u = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), "")
    if not u or not (8 <= len(a) <= 120):
        continue
    if BAD_WA.match(a) or BAD_Q.search(a):
        continue
    cand.append((u, a))
rng.shuffle(cand)

shaped = []
for u, a in cand[:400]:
    for kind in ("wa", "q"):
        if kind == "wa":
            bad = "哇，" + a
        else:
            core = a.rstrip("。！!…")
            bad = core + "？"
        if bad == a:
            continue
        shaped.append({"prompt": [{"role": "user", "content": u}],
                       "chosen": a, "rejected": bad, "source": "shaped_" + kind})
print("机械负例：%d 对（哇 %d / 问号 %d）"
      % (len(shaped), sum(1 for x in shaped if x["source"].endswith("wa")),
         sum(1 for x in shaped if x["source"].endswith("q"))))

allp = pairs + shaped
rng.shuffle(allp)
n_val = max(20, len(allp) // 10)
os.makedirs(OUT, exist_ok=True)
for name, part in (("train.jsonl", allp[n_val:]), ("val.jsonl", allp[:n_val])):
    with io.open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        for x in part:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("\n写出 %s：train %d｜val %d" % (OUT, len(allp) - n_val, n_val))
