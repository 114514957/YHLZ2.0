#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给真实对话样本打 raw 标记，并把"元亨命中禁词/客服腔"的块降为 drop+负样本。

依据《真实数据豁免规则 v1》（2026-10-20）：
  · 四行标记齐 → 形态豁免、内容照查
  · 元亨轮命中禁词/客服腔 → 不进 SFT（status: drop + negative: true），留档供 DPO
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8")
import v9_story_gate as G  # noqa: E402

P = os.path.join(ROOT, "docs", "素材", "真实对话样本.md")
CAPTURED = "2026-09-13"   # 按 corpus_qq.jsonl 落盘时间推定

TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.M)
PATS = {
    "我这边": r"(?<![站在到靠偏冲])我这边",
    "我接": r"我接(?![着受近纳连地下过手脚不])",
    "我认": r"我认(?![输得识为可领真错命认不])",
    "稳了": r"(?<![靠站扶压撑抓握搁])稳了",
    "别指望": r"别指望",
    "客服腔": G.CONFIG["bad_words"]["客服腔"],
    "模板腔": G.CONFIG["bad_words"]["模板腔"],
    "报告腔": G.CONFIG["bad_words"]["报告腔"],
    "应答模板": G.CONFIG["bad_words"]["应答模板"],
}


def yh_hits(blk: str) -> list[str]:
    heads = list(TURN.finditer(blk))
    got = []
    for i, m in enumerate(heads):
        if m.group(1).strip() != "元亨":
            continue
        s = m.end()
        e = heads[i + 1].start() if i + 1 < len(heads) else len(blk)
        body = blk[s:e]
        for tag, pat in PATS.items():
            if re.search(pat, body):
                got.append(tag)
    return sorted(set(got))


text = io.open(P, encoding="utf-8", errors="replace").read()
head, *parts = re.split(r"(?m)^##\s+", text)
new, n_raw, n_drop = [], 0, 0
for b in parts:
    blk = "## " + b.rstrip() + "\n"
    if "raw:" in blk:
        new.append(blk)
        continue
    m = re.search(r"^- source:\s*(.+)$", blk, re.M)
    src = m.group(1).strip() if m else "unknown"
    hits = yh_hits(blk)
    lines = blk.split("\n")
    out = []
    for ln in lines:
        out.append(ln)
        if ln.startswith("- source:"):
            out += [
                "- raw: true",
                "- raw_source: %s" % src,
                "- raw_captured: %s" % CAPTURED,
                "- polish: forbidden",
            ]
    blk2 = "\n".join(out)
    if hits:
        blk2 = blk2.replace("- status: keep", "- status: drop")
        blk2 = blk2.rstrip() + (
            "\n- negative: true\n- note_negative: 元亨轮命中 %s（%s）——"
            "按《真实数据豁免规则 v1》不进 SFT，留档供 DPO\n" % ("/".join(hits), CAPTURED))
        n_drop += 1
        print("drop+negative: %-28s %s" % (blk.split("\n", 1)[0][3:][:26], "/".join(hits)))
    n_raw += 1
    new.append(blk2)

with io.open(P, "w", encoding="utf-8") as fh:
    fh.write(head.rstrip() + "\n")
    for x in new:
        fh.write("\n" + x.rstrip() + "\n")
print("\n打标记 %d 块｜降为负样本 %d 块" % (n_raw, n_drop))
