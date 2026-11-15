# -*- coding: utf-8 -*-
"""建 v11 训练包：把以前没用的素材全部纳入，按错误清单的规矩配权重。

规矩（来自 1113/1136/1151）：
  · 新增来源 Σw 不能倒灌：LCCC 取样封顶，个性生成限权重
  · 长句稀缺（st02）→ 故事/长块加权
  · 问候叫老爹、被凶自称极缺 → 最高权重
  · 客服腔答案一律剔除
  · 只扫 _废弃 之外的所有目录（上一版漏了子目录，这次全扫）
"""
from __future__ import annotations

import glob
import io
import json
import os
import random
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
CORE = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")
OUT = os.path.join(YH, "dist", "retrain_pkg_gemma_v11")
rng = random.Random(20261111)

# 各来源的取用上限与权重
CAP = {"lccc": 4000, "个性生成": 2000, "修订版": 1500, "故事": 200, "其它": 800}
W = {"lccc": 0.15, "个性生成": 0.35, "修订版": 0.30, "故事": 1.5,
     "老爹口述": 3.5,      # 老爹亲自讲剧情、我写的那批（台账 0357/0359）——最高权重
     "问候": 4.0, "被凶": 2.0, "长句": 1.5, "其它": 0.25}
# 老爹口述的故事编号（台账 0357 海带 1..5、0359 黄河钓鱼）
DAD_STORY = re.compile(r"^故事-(?:[1-5]｜|黄河钓鱼)")

GREET = re.compile(r"(我回来了|回来啦|到家了|回家|我回来啦)")
SCOLD = re.compile(r"(凶|骂|生气|吼|滚|闭嘴|有病|烦死|什么态度|脾气)")
BADCALL = re.compile(r"(AI ?助手|智能助手|人工智能助手|虚拟助手|大语言模型)")
SELFREF = ("本小姐", "老娘", "咱")
SKIP_DIRS = {"_废弃"}


def parse_blocks(path):
    md = io.open(path, encoding="utf-8", errors="replace").read()
    out = []
    for part in re.split(r"^##\s+", md, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        if "示例" in head or "<" in head:
            continue
        if re.search(r"^\s*-\s*status\s*[:：]\s*drop", body, re.M):
            continue
        segs = re.split(r"^###\s+(.*)$", body, flags=re.M)
        msgs = []
        for i in range(1, len(segs) - 1, 2):
            title, text = segs[i].strip(), segs[i + 1].strip()
            if not text:
                continue
            role = "assistant" if "元亨" in title else "user"
            if msgs and msgs[-1]["role"] == role:
                msgs[-1]["content"] += "\n" + text
            else:
                msgs.append({"role": role, "content": text})
        if len(msgs) >= 2 and msgs[0]["role"] == "user" and msgs[-1]["role"] == "assistant":
            out.append({"head": head.strip(), "msgs": msgs, "file": path})
    return out


def long_enough(a, n=35):
    sents = [s for s in re.split(r"[。！？\n]+", a) if s.strip()]
    return bool(sents) and max(len(s) for s in sents) >= n


# ① 核心（v10u 打底）
rows = []
for fn in ("sft_persona_v10u_train.jsonl", "sft_persona_v10u_val.jsonl"):
    p = os.path.join(CORE, fn)
    if os.path.exists(p):
        rows += [{"messages": r["messages"], "source": str(r.get("source", "")).split(":")[0],
                  "weight": float(r.get("weight", 1.0) or 1.0)}
                 for r in (json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip())]
print("核心 v10u：%d 条" % len(rows))
seen = set()
for r in rows:
    us = [m["content"] for m in r["messages"] if m.get("role") == "user"]
    if us:
        seen.add(us[0].strip()[:30])

# ② 全库扫（含子目录）
pool = {"lccc": [], "个性生成": [], "修订版": [], "故事": [], "老爹口述": [],
        "问候": [], "被凶": [], "长句": [], "其它": []}
for dirpath, dirs, files in os.walk(MAT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for f in files:
        if not f.endswith(".md") or f.endswith(("_改名块头前.md", "_压缩前.md", "_补称呼前.md")):
            continue
        p = os.path.join(dirpath, f)
        rel = os.path.relpath(p, MAT)
        try:
            blocks = parse_blocks(p)
        except Exception:  # noqa: BLE001
            continue
        for b in blocks:
            u = b["msgs"][0]["content"]
            a = b["msgs"][-1]["content"]
            if BADCALL.search(a):
                continue
            key = u.strip()[:30]
            if key in seen:
                continue
            seen.add(key)
            item = {"messages": b["msgs"], "rel": rel, "u": u, "a": a,
                    "head": b["head"]}
            if DAD_STORY.match(b["head"]):
                pool["老爹口述"].append(item)
            elif GREET.search(u) and "老爹" in a:
                pool["问候"].append(item)
            elif SCOLD.search(u) and any(x in a for x in SELFREF):
                pool["被凶"].append(item)
            elif b["head"].startswith("故事"):
                pool["故事"].append(item)
            elif "lccc" in rel.lower() or "开源对话" in rel:
                pool["lccc"].append(item)
            elif "个性生成" in rel:
                pool["个性生成"].append(item)
            elif rel.startswith("_修订"):
                pool["修订版"].append(item)
            elif long_enough(a):
                pool["长句"].append(item)
            else:
                pool["其它"].append(item)

print("\n去重后各池：")
for k, v in pool.items():
    print("   %-8s %5d" % (k, len(v)))

# ③ 取样 + 加权
added = Counter()
for bucket, lst in pool.items():
    cap = CAP.get(bucket, 800)
    rng.shuffle(lst)
    take = lst[:cap] if cap and len(lst) > cap else lst
    w = W[bucket]
    for it in take:
        rows.append({"messages": it["messages"], "source": "v11_" + bucket, "weight": w})
        added[bucket] += len(take) and 1
    print("   %-8s 取 %5d｜权重 %.2f｜Σw %7.1f"
          % (bucket, len(take), w, len(take) * w))

eff = sum(float(r["weight"]) for r in rows)
print("\n合计 %d 条｜Σw %.0f" % (len(rows), eff))
by = Counter()
for r in rows:
    by[r["source"]] += float(r["weight"])
print("Σw 占比 top10：")
for s, w in by.most_common(10):
    print("   %-18s %7.1f（%5.1f%%）" % (s, w, 100 * w / eff))

# ④ 切分 + 落盘
rng.shuffle(rows)
n_val = max(400, len(rows) // 8)
os.makedirs(os.path.join(OUT, "config"), exist_ok=True)
for name, part in (("sft_persona_v11_train.jsonl", rows[n_val:]),
                   ("sft_persona_v11_val.jsonl", rows[:n_val])):
    with io.open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        for r in part:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("\n写出 train %d｜val %d → %s" % (len(rows) - n_val, n_val, OUT))
