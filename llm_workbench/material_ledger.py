# -*- coding: utf-8 -*-
"""素材总账：把全项目的样本源盘一遍，按类归并，标出「进没进训练包」。

口径来自台账：
  · 1057：黄金样本 73 块全是 VOICE_ANCHOR；身份声明全库约 12 条（0.2%）
  · 1059/1062：**样本密度临界点 ≈30 条**，低于这个数等于没加
  · 1077：寒暄原文 14 条（不够 30）
  · 1107：v9t7 身份回退（"你是 AI 吗" 无样本）

输出：docs/研究/素材总账_20261105.md + .json
"""
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
FT = os.path.join(YH, "data", "finetune")
PACK = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
OUT_MD = os.path.join(YH, "docs", "研究", "素材总账_20261105.md")
OUT_JSON = OUT_MD.replace(".md", ".json")

sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_samples as M  # noqa: E402

# ── 1. 训练包里有什么 ────────────────────────────────────────────
pack_rows = []
for fn in ("sft_persona_v9t7_train.jsonl", "sft_persona_v9t7_val.jsonl"):
    p = os.path.join(PACK, fn)
    if os.path.exists(p):
        with io.open(p, encoding="utf-8") as f:
            pack_rows += [json.loads(x) for x in f if x.strip()]
pack_src = Counter(str(r.get("source", "")).split(":")[0] for r in pack_rows)
pack_hashes = {r.get("content_hash") for r in pack_rows}
pack_answers = set()
for r in pack_rows:
    for m in r.get("messages") or []:
        if m.get("role") == "assistant":
            pack_answers.add(m["content"].strip()[:40])

print("训练包 %d 条 | %d 个来源" % (len(pack_rows), len(pack_src)))

# ── 2. md 素材：按文件统计块与问答 ───────────────────────────────
md_rows = []
for p in sorted(glob.glob(os.path.join(MAT, "*.md"))):
    fn = os.path.basename(p)
    if fn.startswith(("README", "素材清单", "长对话")):
        continue
    blocks = M.parse(p)
    pairs = [qa for _, blk in blocks for qa in M.pairs(blk)]
    contract = Counter()
    for line in io.open(p, encoding="utf-8", errors="replace"):
        m = re.search(r"contract:\s*([A-Z_]+)", line)
        if m:
            contract[m.group(1)] += 1
    md_rows.append({"file": fn, "blocks": len(blocks), "pairs": len(pairs),
                    "contract": dict(contract),
                    "size": os.path.getsize(p)})

# ── 3. jsonl 数据集 ─────────────────────────────────────────────
jsonl_rows = []
for p in sorted(glob.glob(os.path.join(FT, "*.jsonl"))):
    fn = os.path.basename(p)
    if ".test" in fn or fn.startswith("_t8"):
        continue
    n = 0
    try:
        for line in io.open(p, encoding="utf-8", errors="replace"):
            if line.strip():
                n += 1
    except Exception:  # noqa: BLE001
        continue
    if n:
        jsonl_rows.append({"file": fn, "n": n, "size": os.path.getsize(p)})

print("md 素材 %d 个 | jsonl 数据集 %d 个" % (len(md_rows), len(jsonl_rows)))

# ── 4. 缺口判定（按台账口径）────────────────────────────────────
GAPS = [
    ("身份·被问是不是 AI", 0, 30, "问题里不带「助手」的 AI 问法，一条样本都没有（1107 实测回退）"),
    ("身份·总盘", pack_src.get("identity", 0), 30, "包里 identity 源条数（1059：临界 30）"),
    ("寒暄", 14, 30, "1077：素材原文只找到 14 条"),
    ("短答（≤20 字）", None, 30, "1078：群里中位 10 字，模型 59 字"),
    ("安全拒绝", pack_src.get("refusal", 0), 30, "已有 117，够"),
    ("自我贬低/存在（E 类）", 15, 30, "1063：E 类 15 条没治住 m14"),
]

report = {
    "pack": {"rows": len(pack_rows), "by_source": dict(pack_src)},
    "md": md_rows,
    "jsonl": jsonl_rows,
    "gaps": [{"name": g[0], "have": g[1], "need": g[2], "note": g[3]} for g in GAPS],
}
with io.open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)

with io.open(OUT_MD, "w", encoding="utf-8") as f:
    f.write("# 素材总账（2026-11-05）\n\n")
    f.write("> 口径：台账 1057（盘点）、1059/1062（**密度临界点 ≈30 条**）、1077（寒暄缺口）、1107（身份回退）。\n")
    f.write("> 口径写死：**低于 30 条的类别，训了等于没训**。\n\n")
    f.write("## 1. 训练包现状（dist/retrain_pkg_gemma_v9t7，%d 条）\n\n" % len(pack_rows))
    f.write("| 来源 | 条数 |\n|---|---|\n")
    for k, v in pack_src.most_common():
        f.write("| `%s` | %d |\n" % (k, v))
    f.write("\n## 2. md 素材（docs/素材/*.md）\n\n")
    f.write("| 文件 | 块 | 问答对 | contract | 大小 |\n|---|---|---|---|---|\n")
    for r in sorted(md_rows, key=lambda x: -x["pairs"]):
        c = ",".join("%s×%d" % kv for kv in list(r["contract"].items())[:3]) or "-"
        f.write("| %s | %d | %d | %s | %.0f KB |\n"
                % (r["file"], r["blocks"], r["pairs"], c, r["size"] / 1024))
    f.write("\n## 3. jsonl 数据集（data/finetune/）\n\n")
    f.write("| 文件 | 条数 | 大小 |\n|---|---|---|\n")
    for r in sorted(jsonl_rows, key=lambda x: -x["n"]):
        f.write("| %s | %d | %.1f MB |\n" % (r["file"], r["n"], r["size"] / 1048576))
    f.write("\n## 4. 缺口（按台账口径）\n\n")
    f.write("| 缺口 | 现有 | 需要 | 说明 |\n|---|---|---|---|\n")
    for g in GAPS:
        f.write("| %s | %s | ≥%d | %s |\n" % (g[0], "?" if g[1] is None else g[1], g[2], g[3]))

print("\n写出 %s" % OUT_MD)
for g in GAPS:
    print("  %-22s 现有 %s / 需要 %d" % (g[0], g[1], g[2]))
