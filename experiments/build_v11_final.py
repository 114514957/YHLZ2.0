# -*- coding: utf-8 -*-
"""建 v11 训练包（定稿版）

素材使用策略（依老爹 2026-11-11：「以前的素材要用啊」「我亲自讲故事的那些权重可以较高」）：
  · A 老爹口述系列（559 块 / 58 系列）→ 权重 3.5（最高）
  · B 早期海带+钓鱼（5 块）          → 3.5
  · C 扩写故事（60 块）              → 1.0
  · D 试作/测试（9 块）              → 0.5
  · LCCC 开源对话（MIT）取样 4000    → 0.15
  · 自家生成个性（769 块）           → 0.35
  · 长句块、被凶自称、问候叫老爹      → 1.5 / 2.0 / 4.0
  · 核心 v10u 8850 打底
清洗：客服腔答案一律剔除；用户首句 30 字去重；单样本限长（防训练时被截断丢弃）。
"""
from __future__ import annotations

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

W = {"dad_story": 3.5, "early_story": 3.5, "expand_story": 1.0, "draft_story": 0.5,
     "lccc": 0.15, "persona_gen": 0.35, "revised": 0.30, "greet": 4.0, "scold": 2.0,
     "longsent": 1.5, "other": 0.25}
CAP = {"lccc": 4000, "persona_gen": 2000, "revised": 1500, "other": 800}
MAX_CHARS = 1400          # 单样本总字符上限（约 800 token，训练时不会被丢）
MAX_MSGS = 10             # 多轮最多保留 10 条消息

named = re.compile(r"^故事-[^\d｜\s][^｜]*?-\d+｜")
early = re.compile(r"^故事-[1-5]｜")
expanded = re.compile(r"^故事-[2-9]\d{2}｜")
draft = re.compile(r"^故事-(00\d|1\d\d)｜|^故事-2XX｜")
GREET = re.compile(r"(我回来了|回来啦|到家了|回家|我回来啦)")
SCOLD = re.compile(r"(凶|骂|生气|吼|滚|闭嘴|有病|烦死|什么态度|脾气)")
BADCALL = re.compile(r"(AI ?助手|智能助手|人工智能助手|虚拟助手|大语言模型)")
SELFREF = ("本小姐", "老娘", "咱")
SKIP = {"_废弃"}


def trim(msgs):
    """保头保尾、限轮数、限总长，保证末条是 assistant。
    注意：带 tool_calls 的 assistant 与 tool 轮要保留（工具样本），只按条数/字符剪。"""
    if len(msgs) > MAX_MSGS:
        head = msgs[: MAX_MSGS - 1]
        tail = msgs[-1]
        msgs = head + [tail]
    total = sum(len(m.get("content") or "") for m in msgs)
    while total > MAX_CHARS and len(msgs) > 2:
        msgs = msgs[:1] + msgs[2:]
        total = sum(len(m.get("content") or "") for m in msgs)
    if len(msgs) < 2 or msgs[-1]["role"] != "assistant" or msgs[0]["role"] != "user":
        return None
    return msgs


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
        # 2026-11-11 修：故事块常以「旁白/场景」开头（413/564 都是这样），
        # 首条不是 user 就被整块丢弃——改成切掉开头的非 user 段、截到最后一个 assistant。
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        while msgs and msgs[-1]["role"] != "assistant":
            msgs.pop()
        # 保证 user/assistant 交替（相邻同角色已合并，这里再兜一次连续 user）
        clean = []
        for m in msgs:
            if clean and clean[-1]["role"] == m["role"]:
                clean[-1]["content"] += "\n" + m["content"]
            else:
                clean.append(dict(m))
        if len(clean) >= 2 and clean[0]["role"] == "user" and clean[-1]["role"] == "assistant":
            out.append({"head": head.strip(), "msgs": clean})
    return out


# ① 核心
rows = []
for fn in ("sft_persona_v10u_train.jsonl", "sft_persona_v10u_val.jsonl"):
    p = os.path.join(CORE, fn)
    if os.path.exists(p):
        rows += [{"messages": r["messages"],
                  "source": str(r.get("source", "")).split(":")[0],
                  "weight": float(r.get("weight", 1.0) or 1.0)}
                 for r in (json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip())]
print("核心 v10u：%d 条" % len(rows))

seen = set()
for r in rows:
    us = [m["content"] for m in r["messages"] if m.get("role") == "user"]
    if us:
        seen.add(us[0].strip()[:30])

# ② 全库
pool = {k: [] for k in W}
for dirpath, dirs, files in os.walk(MAT):
    dirs[:] = [d for d in dirs if d not in SKIP]
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
            u, a = b["msgs"][0]["content"], b["msgs"][-1]["content"]
            if BADCALL.search(a):
                continue
            head = b["head"]
            is_story = bool(named.match(head) or early.match(head)
                            or expanded.match(head) or draft.match(head))
            # 故事块按「块头 + 首句」去重；普通块按「首句 30 字」去重
            # （故事开头常重复同一句话，用首句去重会把 559 段误杀成 88 段）
            key = (head + "|" + u.strip()[:30]) if is_story else u.strip()[:30]
            if key in seen:
                continue
            seen.add(key)
            if named.match(head):
                bucket = "dad_story"
            elif early.match(head):
                bucket = "early_story"
            elif expanded.match(head):
                bucket = "expand_story"
            elif draft.match(head):
                bucket = "draft_story"
            elif GREET.search(u) and "老爹" in a:
                bucket = "greet"
            elif SCOLD.search(u) and any(x in a for x in SELFREF):
                bucket = "scold"
            elif "lccc" in rel.lower() or "开源对话" in rel:
                bucket = "lccc"
            elif "个性生成" in rel:
                bucket = "persona_gen"
            elif rel.startswith("_修订"):
                bucket = "revised"
            else:
                sents = [s for s in re.split(r"[。！？\n]+", a) if s.strip()]
                bucket = "longsent" if sents and max(len(s) for s in sents) >= 35 else "other"
            pool[bucket].append({"msgs": b["msgs"], "head": head, "rel": rel})

print("\n分池：")
for k in W:
    print("   %-14s %5d" % (k, len(pool[k])))

# ③ 取样 + 限长 + 加权
added = Counter()
dropped_len = 0
for bucket, lst in pool.items():
    cap = CAP.get(bucket, 10 ** 9)
    rng.shuffle(lst)
    take = lst[:cap] if len(lst) > cap else lst
    for it in take:
        m = trim(it["msgs"])
        if m is None:
            dropped_len += 1
            continue
        rows.append({"messages": m, "source": "v11_" + bucket, "weight": W[bucket]})
        added[bucket] += 1

# 按「答错代价」加权（2026-11-11，来自《蒸馏五坑》第②条 + 我们自己的 1116）
# 闸门泄露一次就破底线 → ×2.5；工具答错群友看得出 → ×1.5
COST = {"refusal": 2.0, "harden": 2.0, "internal_refusal": 2.0,
        "identity_ai": 2.0, "mat_安全拒绝样本": 2.0,
        "discipline": 1.5, "realtask": 1.5}

eff = sum(float(r["weight"]) for r in rows)
# 按代价提权（只作用于 v10u 带来的核心来源，v11_* 新来源不动）
boosted = 0
for r in rows:
    m = COST.get(r["source"])
    if m:
        r["weight"] = float(r["weight"]) * m
        boosted += 1

# ── 全局清洗（2026-11-11 自检抓出来的：核心数据也没剪，会静默丢弃）──
clean_rows = []
seen_pair = set()
n_trim = n_svc = n_dup = n_bad = 0
for r in rows:
    msgs = r["messages"]
    # 保留开头的 system（如果有），其余走 trim
    head_sys = []
    body = msgs
    if msgs and msgs[0].get("role") == "system":
        head_sys = [msgs[0]]
        body = msgs[1:]
    if not body or body[0].get("role") != "user":
        n_bad += 1
        continue
    b = trim(body)
    if b is None:
        n_bad += 1
        continue
    if len(b) != len(body):
        n_trim += 1
    full = head_sys + b
    if BADCALL.search(b[-1]["content"]):
        n_svc += 1
        continue
    # 2026-11-11 修：**带 tool_calls 的 assistant 内容本来就是空的**（tool 轮约定），
    # 第一版用「所有消息内容非空」把它判成坏数据，一口气丢了 949 条工具样本。
    bad_empty = False
    for m in full:
        c = (m.get("content") or "").strip()
        if c:
            continue
        if m.get("role") == "assistant" and m.get("tool_calls"):
            continue                      # tool_calls 轮，空内容是正常的
        if m.get("role") == "tool":
            continue
        bad_empty = True
        break
    if bad_empty:
        n_bad += 1
        continue
    key = (b[0]["content"].strip()[:30], b[-1]["content"].strip()[:30])
    if key in seen_pair:
        n_dup += 1
        continue
    seen_pair.add(key)
    clean_rows.append({"messages": full, "source": r["source"], "weight": r["weight"]})
print("全局清洗：%d → %d 条（剪枝 %d｜客服腔 %d｜重复 %d｜结构坏 %d）"
      % (len(rows), len(clean_rows), n_trim, n_svc, n_dup, n_bad))
rows = clean_rows

eff = sum(float(r["weight"]) for r in rows)
print("按代价提权：%d 条｜清洗后 Σw %.0f" % (boosted, eff))
print("\n建包：%d 条｜Σw %.0f｜因限长剔除 %d" % (len(rows), eff, dropped_len))
by = Counter()
for r in rows:
    by[r["source"]] += float(r["weight"])
print("Σw 占比 top12：")
for s, w in by.most_common(12):
    print("   %-18s %7.1f（%5.1f%%）" % (s, w, 100 * w / eff))

rng.shuffle(rows)
n_val = max(500, len(rows) // 8)
os.makedirs(os.path.join(OUT, "config"), exist_ok=True)
for name, part in (("sft_persona_v11_train.jsonl", rows[n_val:]),
                   ("sft_persona_v11_val.jsonl", rows[:n_val])):
    with io.open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        for r in part:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("\n写出 train %d｜val %d → %s" % (len(rows) - n_val, n_val, OUT))
