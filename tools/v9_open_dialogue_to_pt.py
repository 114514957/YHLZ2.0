#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 LCCC 对话块接进 PT 的 speaking_general 池（**按 PT 的文档口径打包**）。

2026-10-21 教训：PT 的 `v9_pt_corpus.py` 会丢弃 `len(text) < 40` 的文档。
第一版把「一块对话 = 一篇文档」直接追加，结果 **17,027 块里 7,032 块（41%）因太短被扔**
（我这些对话平均只有 52 字符）。PT 要的是**成篇的文档**，不是碎句。

改法：
  · 单块归一化后 ≥ 60 字符 → 自成一篇
  · 不足 → **连续打包**，直到凑够 ≥ 200 字符才成一篇（用空行分隔，像真文档）

用法：
    python tools/v9_open_dialogue_to_pt.py --in <素材.md> --dry-run
    python tools/v9_open_dialogue_to_pt.py --in <素材.md> --append
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TARGET = os.path.join(ROOT, "data", "pd", "v9_open_dialogue.jsonl")
MIN_SINGLE = 40        # PT 的丢弃门槛就是 40，所以 ≥40 一律单独成篇（2026-10-21 实测最优）
TARGET_DOC = 200       # 只有 <40 的才连续打包到这个长度


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def parse_blocks(path: str):
    text = io.open(path, encoding="utf-8").read()
    out = []
    for b in re.split(r"(?m)^## ", text)[1:]:
        name = b.split("\n")[0].strip()
        turns, role = [], None
        for ln in b.split("\n")[1:]:
            s = ln.strip()
            if s.startswith("### "):
                role = "用户" if "问" in s else "对方"
            elif s and not s.startswith("-") and role:
                turns.append((role, s))
                role = None
        if len(turns) >= 2:
            body = "\n".join("%s：%s" % (r, t) for r, t in turns)
            out.append((name, body))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--append", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source-tag", default="open:lccc-screened")
    ap.add_argument("--license", default="MIT")
    a = ap.parse_args()

    blocks = parse_blocks(a.inp)
    print("%s ｜%d 块" % (os.path.basename(a.inp), len(blocks)))
    lens = sorted(len(t) for _, t in blocks)
    n = len(lens)
    print("单块长度：中位 %d｜p90 %d｜最小 %d｜最大 %d"
          % (lens[n // 2], lens[int(n * 0.9)], lens[0], lens[-1]))

    # 打包：长的单飞，短的连打
    docs, buf, buf_len = [], [], 0
    for name, body in blocks:
        if len(body) >= MIN_SINGLE:
            docs.append((name, body))
        else:
            buf.append(body)
            buf_len += len(body)
            if buf_len >= TARGET_DOC:
                docs.append(("bundle-%04d" % len(docs), "\n\n".join(buf)))
                buf, buf_len = [], 0
    if buf:
        if buf_len >= 40:
            docs.append(("bundle-%04d" % len(docs), "\n\n".join(buf)))
        elif docs:
            # 残余并进最后一篇，别丢
            docs[-1] = (docs[-1][0], docs[-1][1] + "\n\n" + "\n\n".join(buf))
    print("打包后 %d 篇｜长度中位 %d｜平均 %d 字符"
          % (len(docs), sorted(len(t) for _, t in docs)[len(docs) // 2],
             sum(len(t) for _, t in docs) // max(1, len(docs))))

    existing = []
    if os.path.exists(TARGET):
        existing = [json.loads(x) for x in io.open(TARGET, encoding="utf-8") if x.strip()]
    print("现有 PT 开源对话 %d 条" % len(existing))
    seen = {d.get("content_hash") for d in existing}

    rows, dup, short = [], 0, 0
    for name, body in docs:
        t = re.sub(r"\s+", "", body)
        if len(t) < 40:
            short += 1
            continue
        h = sha16(t)
        if h in seen:
            dup += 1
            continue
        seen.add(h)
        rows.append({"text": body, "source": a.source_tag,
                     "source_id": "odlg#lccc#%s" % name,
                     "group_id": a.source_tag, "license": a.license,
                     "chars": len(body), "content_hash": h})

    print("新增 %d 篇（重复 %d｜过短丢弃 %d）｜合计 %s 字符"
          % (len(rows), dup, short, format(sum(r["chars"] for r in rows), ",")))
    print("追加后 PT 开源对话：%d 篇" % (len(existing) + len(rows)))

    if a.dry_run or not rows:
        for r in rows[:2]:
            print("\n样例：\n%s" % r["text"][:260])
        return 0

    bak = TARGET.replace(".jsonl", "_append前_20261021b.jsonl")
    if os.path.exists(TARGET):
        shutil.copy2(TARGET, bak)
    with io.open(TARGET, "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("已追加（备份 %s）" % os.path.basename(bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
