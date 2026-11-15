# -*- coding: utf-8 -*-
"""全素材盘点（含所有子目录）vs 现有训练包，看还有什么没用上。"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u")
SKIP_DIRS = {"_废弃"}


def parse_blocks(path):
    """通用：`## 标题` 一块，块内 `### X` 按角色切；元亨=assistant，其余=user。"""
    md = io.open(path, encoding="utf-8", errors="replace").read()
    out = []
    for part in re.split(r"^##\s+", md, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        if "示例" in head or "<" in head:          # 跳过模板占位块
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


# ① 全库扫
all_blocks = []
per_file = Counter()
for dirpath, dirs, files in os.walk(MAT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for f in files:
        if not f.endswith(".md"):
            continue
        if f.endswith(("_改名块头前.md", "_压缩前.md", "_补称呼前.md")):
            continue
        p = os.path.join(dirpath, f)
        try:
            bs = parse_blocks(p)
        except Exception:  # noqa: BLE001
            continue
        for b in bs:
            rel = os.path.relpath(p, MAT)
            b["rel"] = rel
            all_blocks.append(b)
            per_file[rel] += 1

print("全库解析 %d 块，来自 %d 个文件" % (len(all_blocks), len(per_file)))
top = sum(v for k, v in per_file.items() if os.sep not in k)
sub = len(all_blocks) - top
print("  顶层 %d 块｜子目录 %d 块（以前完全没用）" % (top, sub))

# ② 现有包里的用户首句指纹
seen = set()
for fn in ("sft_persona_v10u_train.jsonl", "sft_persona_v10u_val.jsonl"):
    p = os.path.join(PKG, fn)
    if os.path.exists(p):
        for x in io.open(p, encoding="utf-8"):
            if x.strip():
                r = json.loads(x)
                us = [m["content"] for m in r["messages"] if m.get("role") == "user"]
                if us:
                    seen.add(us[0].strip()[:30])
print("包内已有用户首句指纹 %d" % len(seen))

# ③ 分类 + 去重
GREET = re.compile(r"(我回来了|回来啦|到家了|回家|我回来啦)")
SCOLD = re.compile(r"(凶|骂|生气|吼|滚|闭嘴|有病|烦死|什么态度|脾气)")
BADCALL = re.compile(r"(AI ?助手|智能助手|人工智能助手|虚拟助手|作为一个|大语言模型)")
SELFREF = ("本小姐", "老娘", "咱")

buckets = Counter()
new_blocks = 0
for b in all_blocks:
    u = b["msgs"][0]["content"]
    a = b["msgs"][-1]["content"]
    if BADCALL.search(a):
        buckets["drop_客服腔"] += 1
        continue
    key = u.strip()[:30]
    if key in seen:
        buckets["已在包内"] += 1
        continue
    seen.add(key)
    new_blocks += 1
    if b["head"].startswith("故事"):
        buckets["故事"] += 1
    elif GREET.search(u) and "老爹" in a:
        buckets["问候叫老爹"] += 1
    elif SCOLD.search(u) and any(x in a for x in SELFREF):
        buckets["被凶自称"] += 1
    else:
        buckets["其它"] += 1

print("\n去重后**新增** %d 块" % new_blocks)
for k, v in buckets.most_common():
    print("   %-12s %d" % (k, v))

print("\n子目录里块最多的文件（以前全没用）：")
for k, v in per_file.most_common(12):
    if os.sep in k:
        print("   %-58s %5d" % (k[:58], v))
