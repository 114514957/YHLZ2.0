#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""素材现状盘点 v2（口径修正）：块 = `## ` 级标题；并统计主体性违规与禁词。"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAT = os.path.join(ROOT, "docs", "素材")
FIN = os.path.join(ROOT, "data", "finetune")
BANNED = ["我这边", "我接", "我认", "稳了", "很稳", "这个稳", "别指望"]

H2 = re.compile(r"^##\s+\S", re.M)
H3 = re.compile(r"^###\s+\S", re.M)
# 元亨在提问 = 主体性违规（M2）
YUAN_ASK = re.compile(r"^###\s*元亨\s*问", re.M)
YUAN_ANS = re.compile(r"^###\s*元亨\s*答", re.M)
LIZHEN_ANS = re.compile(r"^###\s*利贞\s*答", re.M)
DADIE = re.compile(r"^###\s*老爹", re.M)


def scan_md() -> list[dict]:
    rows = []
    for name in sorted(os.listdir(MAT)):
        if not name.endswith(".md"):
            continue
        p = os.path.join(MAT, name)
        txt = io.open(p, encoding="utf-8", errors="replace").read()
        rows.append({
            "file": name,
            "blocks": len(H2.findall(txt)),
            "turns": len(H3.findall(txt)),
            "chars": len(txt),
            "banned": sum(txt.count(b) for b in BANNED),
            "yuan_ask": len(YUAN_ASK.findall(txt)),
            "yuan_ans": len(YUAN_ANS.findall(txt)),
            "lizhen_ans": len(LIZHEN_ANS.findall(txt)),
            "dadie": len(DADIE.findall(txt)),
        })
    return rows


def v9_stats() -> dict:
    p = os.path.join(FIN, "sft_v9_all.jsonl")
    if not os.path.exists(p):
        return {}
    weight, src, turns = Counter(), Counter(), Counter()
    tools = banned_rec = 0
    banned_hits = Counter()
    out_chars = 0
    n = 0
    for line in io.open(p, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        n += 1
        r = json.loads(line)
        meta = r.get("meta") or {}
        weight[str(meta.get("weight"))] += 1
        src[str(meta.get("source") or meta.get("source_id") or "?").split(":")[0]] += 1
        outp = r.get("output") or []
        turns[len(outp)] += 1
        txt = ""
        for o in outp:
            txt += str(o.get("assistant") or "")
            if o.get("tool_call"):
                tools += 1
        out_chars += len(txt)
        hit = False
        for b in BANNED:
            c = txt.count(b)
            if c:
                banned_hits[b] += c
                hit = True
        if hit:
            banned_rec += 1
    return {"records": n, "weight": dict(weight), "source": dict(src.most_common()),
            "turns": dict(sorted(turns.items())), "tool_calls": tools,
            "banned_records": banned_rec, "banned_hits": dict(banned_hits),
            "out_chars": out_chars}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=" * 92)
    print("素材现状盘点（口径：块 = `## ` 级标题；轮 = `### `）")
    print("=" * 92)

    md = [r for r in scan_md() if r["blocks"] or r["turns"]]
    print("\n【一、素材库 docs/素材/】")
    print("  %-28s %6s %7s %9s %6s %8s %8s" %
          ("文件", "块数", "轮数", "字符", "禁词", "元亨问", "元亨答"))
    T = Counter()
    for r in md:
        print("  %-28s %6d %7d %9d %6d %8d %8d" %
              (r["file"], r["blocks"], r["turns"], r["chars"], r["banned"],
               r["yuan_ask"], r["yuan_ans"]))
        for k in ("blocks", "turns", "chars", "banned", "yuan_ask", "yuan_ans"):
            T[k] += r[k]
    print("  %-28s %6d %7d %9d %6d %8d %8d" %
          ("合计", T["blocks"], T["turns"], T["chars"], T["banned"],
           T["yuan_ask"], T["yuan_ans"]))

    st = v9_stats()
    if st:
        print("\n【二、V9 导出稿 data/finetune/sft_v9_all.jsonl】")
        print("  记录 %d ｜ 元亨输出字符 %d ｜ 工具调用 %d" %
              (st["records"], st["out_chars"], st["tool_calls"]))
        print("  轮数分布: %s" % st["turns"])
        print("  权重分布: %s" % st["weight"])
        print("  来源分布: %s" % st["source"])
        print("  ⚠️ 含禁词: %d 条 ｜ 命中 %s" % (st["banned_records"], st["banned_hits"]))
        # token 估算：实测 0.90 token/汉字
        print("  元亨输出 token 估算: 约 %d（0.90 token/字符）" % int(st["out_chars"] * 0.90))

    print("\n【三、距目标】")
    tot = st.get("records", 0)
    print("  80,000 条目标 ｜ 现有 %d ｜ **%.2f%%** ｜ 还差 %d" %
          (tot, 100.0 * tot / 80000, 80000 - tot))

    print("\n【四、其他数据集（可用但未并入）】")
    for name, desc in (("corpus_qq.jsonl", "QQ 群语料（一般素材，低权重）"),
                       ("corpus_qq_raw.jsonl", "原始抓取（未清洗）"),
                       ("tool_use_v8.jsonl", "工具轨迹（已含在 v9 内）")):
        p = os.path.join(FIN, name)
        if os.path.exists(p):
            n = sum(1 for _ in io.open(p, encoding="utf-8", errors="replace"))
            print("  %-24s %6d 条  %s" % (name, n, desc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
