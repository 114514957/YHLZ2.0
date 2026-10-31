#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成人工抽审清单（带抽审位置）：源文件行号 + 导出文件行号（只读）。

给老爹用：每一条都要能"翻到地方看"。因此每条记录都定位到：
  · **源**：`docs/素材/*.md` 里的块，给出文件与行号区间；
  · **导出**：`data/finetune/sft_persona_v8r4t_*.jsonl` 里的行号。

优先级（按"机器能指出的该看的地方"排）：
  P1 一档硬红线（CC:）——宪章级，必看
  P2 语料风险命中（risk: 广告/链接/诱导/隐私/号码…）——整改对象，必看
  P3 二档语境相关（cc2:）——多为良性，抽查即可
  P4 无命中对照样本——随机抽若干，验证"没命中的也真的没问题"

用法：
    python tools/v9_review_sheet.py --per-tier 40
    python tools/v9_review_sheet.py --per-tier 40 --seed 20261013
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import random
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIN = os.path.join(ROOT, "data", "finetune")
SPLITS = ["train", "val", "test"]
SPLIT_FILES = {s: os.path.join(FIN, "sft_persona_v8r4t_%s.jsonl" % s) for s in SPLITS}
OUT_DIR = os.path.join(ROOT, "cache", "v9_materials_preparation", "20261013")

SRC_GLOBS = [
    "docs/素材/*.md",
    "docs/素材/_修订/批次*.md",
    "docs/素材/_草稿/*.md",
]


def load_splits() -> list[dict]:
    rows = []
    for s, p in SPLIT_FILES.items():
        if not os.path.exists(p):
            continue
        with io.open(p, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                rec["_split"] = s
                rec["_line"] = i
                rows.append(rec)
    return rows


def build_src_index() -> list[tuple[str, str, int, int]]:
    """→ [(相对路径, 块标题, 起行, 止行)]。"""
    idx = []
    for g in SRC_GLOBS:
        for p in sorted(glob.glob(os.path.join(ROOT, g))):
            rel = os.path.relpath(p, ROOT)
            try:
                lines = io.open(p, "r", encoding="utf-8", errors="replace").read().splitlines()
            except Exception:
                continue
            start = None
            title = ""
            for i, ln in enumerate(lines, 1):
                if ln.startswith("## "):
                    if start is not None:
                        idx.append((rel, title, start, i - 1))
                    start, title = i, ln[3:].strip()
            if start is not None:
                idx.append((rel, title, start, len(lines)))
    return idx


def locate(rec: dict, src_index) -> list[tuple[str, str, int, int]]:
    """按 source_id 的块标识 + 首条 assistant 文本签名去源文件里找位置。"""
    sid = str(rec.get("source_id") or "")
    dim, _, bid = sid.partition("#")
    key = bid.strip()
    hits = []
    if key:
        # 精确优先：标题必须**以该标识开头且后面到边界**（避免 b4-104 匹到 b4-10）
        for rel, title, a, b in src_index:
            t = title.strip()
            if t == key or re.match(r"^%s(?![\d-])" % re.escape(key), t):
                hits.append((rel, title, a, b))
        if not hits:
            # 退一步：块族级匹配（对话-1535 匹到 对话-1535｜哲学）
            fam = re.match(r"([\u4e00-\u9fff]{1,4}[-_]?\d{1,5})", key)
            if fam:
                for rel, title, a, b in src_index:
                    if title.strip().startswith(fam.group(1)):
                        hits.append((rel, title, a, b))
    if hits:
        return hits[:2]
    # 退化：用首条 assistant 前 20 字在源文件里搜
    a_txt = next((str(m.get("content") or "") for m in rec.get("messages") or []
                  if m.get("role") == "assistant"), "")[:20]
    if len(a_txt) >= 8:
        for rel in {r for r, _t, _a, _b in src_index}:
            p = os.path.join(ROOT, rel)
            try:
                lines = io.open(p, "r", encoding="utf-8", errors="replace").read().splitlines()
            except Exception:
                continue
            for i, ln in enumerate(lines, 1):
                if a_txt in ln:
                    hits.append((rel, "（按内容定位）", max(1, i - 3), i + 3))
                    break
            if hits:
                break
    return hits[:2]


def first_assistant(rec: dict) -> str:
    for m in rec.get("messages") or []:
        if m.get("role") == "assistant":
            return str(m.get("content") or "")[:110].replace("\n", " ")
    return ""


def first_user(rec: dict) -> str:
    for m in rec.get("messages") or []:
        if m.get("role") == "user":
            return str(m.get("content") or "")[:60].replace("\n", " ")
    return ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-tier", type=int, default=40)
    ap.add_argument("--seed", type=int, default=20261013)
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "人工抽审清单_v8r4t.md"))
    args = ap.parse_args()

    rows = load_splits()
    if not rows:
        print("找不到 v8r4t 分片文件，先跑 tools/v9_trace_enrich.py")
        return 3
    src_index = build_src_index()
    rnd = random.Random(args.seed)

    tiers: dict[str, list[dict]] = {"P1": [], "P2": [], "P3": [], "P4": []}
    for r in rows:
        lab = str(r.get("safety_labels") or "none")
        if lab == "none":
            tiers["P4"].append(r)
            continue
        if "CC:" in lab:
            tiers["P1"].append(r)
        if "risk:" in lab:
            tiers["P2"].append(r)
        if "cc2:" in lab:
            tiers["P3"].append(r)

    picked = {}
    # P1/P2 是必看档：**全取**，不抽样（抽了就等于放掉一部分）；P3/P4 才抽样
    for t in ("P1", "P2"):
        picked[t] = tiers[t]
    for t in ("P3", "P4"):
        pool = list(tiers[t])
        rnd.shuffle(pool)
        picked[t] = pool[: args.per_tier]

    lines = []
    lines.append("# 人工抽审清单 · v8r4t（2026-10-13）")
    lines.append("")
    lines.append("> 用途：给国标要求的人工抽检留痕。**逐条勾选 = 签字**；")
    lines.append("> 勾选方式：把 `[ ]` 改成 `[x]`（认可）／`[!]`（要改）；空白视为未审。")
    lines.append("> 定位说明：**源**＝素材 .md 的块位置；**导出**＝`data/finetune/sft_persona_v8r4t_*.jsonl` 的行号。")
    lines.append("")
    lines.append("## 总体")
    lines.append("")
    lines.append("| 档 | 含义 | 池子总数 | 本次抽取 |")
    lines.append("|---|---|---:|---:|")
    lines.append("| **P1** | 一档硬红线（宪章级） | %d | %d |" % (len(tiers["P1"]), len(picked["P1"])))
    lines.append("| **P2** | 语料风险命中（广告/链接/隐私/号码…） | %d | %d |" % (len(tiers["P2"]), len(picked["P2"])))
    lines.append("| **P3** | 二档语境相关（多为良性） | %d | %d |" % (len(tiers["P3"]), len(picked["P3"])))
    lines.append("| **P4** | 无命中对照样本 | %d | %d |" % (len(tiers["P4"]), len(picked["P4"])))
    lines.append("")
    lines.append("合计待审 **%d** 条。P1/P2 建议全看，P3 抽查，P4 用于验证「没命中的是否真的没问题」。"
                 % sum(len(v) for v in picked.values()))
    lines.append("")

    tier_desc = {
        "P1": "一档硬红线（宪章级）：**必看**。先判「是拒绝样本/哲学讨论」还是「真的要学」——"
              "目前已知 P1 全是前者（安全拒绝正样本与哲学段落），但仍须你过目。",
        "P2": "语料风险命中：**必看**。多为群聊里的链接与营销话术，判定留/剔。",
        "P3": "二档语境相关：**抽查**。词本身中性（隐私/垃圾/服从），看上下文是否得体。",
        "P4": "无命中对照：**抽查**。检验扫描器有没有漏。",
    }

    for t in ("P1", "P2", "P3", "P4"):
        lines.append("---")
        lines.append("")
        lines.append("## %s（%d 条）" % (t, len(picked[t])))
        lines.append("")
        lines.append(tier_desc[t])
        lines.append("")
        for k, r in enumerate(picked[t], 1):
            locs = locate(r, src_index)
            loc_str = "；".join("%s L%d–L%d（%s）" % (a, c, d, b) for a, b, c, d in locs) or "（未在源文件定位到，属装配派生）"
            lines.append("### %s-%02d ｜ %s" % (t, k, r.get("source_id", "?")))
            lines.append("")
            lines.append("- [ ] 结论：认可 / 要改（圈一个，或写批注）")
            lines.append("- 标签：`%s`" % r.get("safety_labels"))
            lines.append("- 切分：`%s` 第 %d 行 ｜ 同意状态 `%s`" % (r["_split"], r["_line"], r.get("consent_status")))
            lines.append("- **抽审位置（源）**：%s" % loc_str)
            lines.append("- **抽审位置（导出）**：`data/finetune/sft_persona_v8r4t_%s.jsonl` 第 %d 行" % (r["_split"], r["_line"]))
            lines.append("- 用户：%s" % first_user(r))
            lines.append("- 元亨：%s" % first_assistant(r))
            lines.append("")

    os.makedirs(OUT_DIR, exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    payload = {"action": "review_sheet", "seed": args.seed, "per_tier": args.per_tier,
               "pools": {k: len(v) for k, v in tiers.items()},
               "picked": {k: len(v) for k, v in picked.items()},
               "out": os.path.relpath(args.out, ROOT)}
    with io.open(os.path.join(OUT_DIR, "review_sheet_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print("人工抽审清单已生成：%s" % os.path.relpath(args.out, ROOT))
    print("池子：P1 %d ／ P2 %d ／ P3 %d ／ P4 %d" % (len(tiers["P1"]), len(tiers["P2"]),
                                                    len(tiers["P3"]), len(tiers["P4"])))
    print("本次抽取：P1 %d ／ P2 %d ／ P3 %d ／ P4 %d（合计 %d 条）"
          % (len(picked["P1"]), len(picked["P2"]), len(picked["P3"]), len(picked["P4"]),
             sum(len(v) for v in picked.values())))
    # 一键查看用：打印 P1 全部位置
    print("\nP1 全部位置（必看）：")
    for k, r in enumerate(picked["P1"], 1):
        locs = locate(r, src_index)
        loc_str = "；".join("%s L%d–L%d" % (a, c, d) for a, _b, c, d in locs) or "（装配派生，看导出行）"
        print("  %2d. %-28s 源：%s ｜ 导出：%s 第 %d 行"
              % (k, r.get("source_id", "?")[:28], loc_str, r["_split"], r["_line"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
