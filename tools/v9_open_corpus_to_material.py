#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把拉开源对白**原话**直接转成素材（老爹 2026-10-20：「不要再生成，直接用可用的原话」）。

原则：
  · **一个字都不改写**——台词原样搬；
  · 只做三件不改变语义的事：
      ① 格式转换（input/output → ### 老爹问N / ### 元亨答N）
      ② 剥离不合法成分（Arya 的 `*动作旁白*`，不剥离台词）
      ③ 加元数据块头（category/emotion/length_tier/contract/source/license）
  · 剥完/转完之后跑门禁，**只收 PASS/WARN，FAIL 一律不收**（收了就是脏数据）。

来源（见 docs/报告/开源对话语料拉取与机制提炼_20261020.md）：
  THE  catbohe/TreeHoleEcho  Apache-2.0   1012 条共情单轮
  ARYA newcjh/Arya           未标注      2931 条角色扮演（100% 带动作旁白）

用法：
    python tools/v9_open_corpus_to_material.py --src THE --limit 300
    python tools/v9_open_corpus_to_material.py --src ARYA --limit 300
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import v9_story_gate as G  # noqa: E402

CORPUS = os.path.join(ROOT, "cache", "v9_open_corpus", "20261020")


def strip_stage(text: str) -> str:
    """去掉 *动作旁白* 与行首的 *…*，**只删旁白不删台词**。"""
    t = re.sub(r"\*[^*\n]{1,80}\*", "", text)          # *推了推眼镜*
    t = re.sub(r"(?m)^\s*[*＊][^\n]*$", "", t)          # 整行旁白
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


def clean_line(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("\r", "").strip()
    return s


def build_block(name: str, asks: list[str], answers: list[str],
                category: str, emotion: str, contract: str,
                src: str, lic: str) -> str:
    meta = [
        "## %s" % name,
        "- category: %s" % category,
        "- emotion: %s" % (emotion or "neutral"),
        "- length_tier: %s" % ("short" if max(len(a) for a in answers) <= 60 else "medium"),
        "- contract: %s" % contract,
        "- source: %s" % src,
        "- license: %s" % lic,
        "- polish: none",
    ]
    body = []
    for i, (q, a) in enumerate(zip(asks, answers), 1):
        body.append("### 老爹问%d" % i)
        body.append(q)
        body.append("### 元亨答%d" % i)
        body.append(a)
    return "\n".join(meta) + "\n" + "\n".join(body) + "\n"


def load_THE():
    p = os.path.join(CORPUS, "THE_TreeHoleEcho.jsonl")
    rows = [json.loads(x) for x in io.open(p, encoding="utf-8", errors="replace")
            if x.strip()]
    return [{"ask": clean_line(r.get("input")), "ans": clean_line(r.get("output")),
             "emotion": ",".join(r.get("emotion") or []) or "neutral"} for r in rows
            if clean_line(r.get("input")) and clean_line(r.get("output"))]


def load_ARYA():
    p = os.path.join(CORPUS, "ARYA_Arya.json")
    rows = json.load(io.open(p, encoding="utf-8-sig", errors="replace"))
    out = []
    for r in rows:
        q = clean_line(r.get("instruction") or "")
        a = strip_stage(r.get("output") or "")
        a = clean_line(a)
        if len(q) >= 4 and len(a) >= 4:
            out.append({"ask": q, "ans": a, "emotion": "neutral"})
    return out


SRC_DEF = {
    "THE": ("情绪承接", "ANCHOR", "TreeHoleEcho", "Apache-2.0", load_THE),
    "ARYA": ("角色对话", "ANCHOR", "Arya", "未标注（待核）", load_ARYA),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, choices=list(SRC_DEF))
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--pair", action="store_true",
                    help="两条拼成一个 2 轮块（默认每条单独成块，单轮）")
    a = ap.parse_args()

    cat, contract, tag, lic, loader = SRC_DEF[a.src]
    items = loader()
    print("%s：可用原话 %d 条（拉取总数里的有效问答对）" % (a.src, len(items)))

    blocks, dropped = [], {}
    used = 0
    i = 0
    while used < a.limit and i < len(items):
        if a.pair and i + 1 < len(items):
            grp = items[i:i + 2]
            asks = [x["ask"] for x in grp]
            anss = [x["ans"] for x in grp]
            emo = grp[0]["emotion"]
            i += 2
        else:
            grp = items[i:i + 1]
            asks = [grp[0]["ask"]]
            anss = [grp[0]["ans"]]
            emo = grp[0]["emotion"]
            i += 1
        if any(len(x) > 1200 for x in anss):
            dropped["答案过长"] = dropped.get("答案过长", 0) + 1
            continue
        name = "%s-%03d" % (a.src.lower(), used + 1)
        blk = build_block(name, asks, anss, cat, emo, contract, tag, lic)
        r = G.check_block(name, blk, "general")
        if r["status"] == "FAIL":
            for f in r["fails"]:
                k = re.sub(r"×\d+", "", f).split(":")[0].strip()
                dropped[k] = dropped.get(k, 0) + 1
            continue
        blocks.append(blk)
        used += 1

    print("收货 %d 块｜丢弃原因 %s" % (len(blocks), dropped or "无"))
    if not blocks:
        return 1

    out = os.path.join(ROOT, "docs", "素材", "%s样本.md" % cat)
    head = ("# 元亨%s样本（开源原话直采 · %s）\n\n"
            "> **老爹 2026-10-20 定：不再生成，直接用可用的原话。**\n"
            "> 来源：`%s`（许可：%s）。\n"
            "> **台词一字未改**；只做了：格式转换、剥离 `*动作旁白*`（Arya）、加元数据块头、"
            "过门禁（FAIL 一律不收）。\n"
            "> 采集脚本 `tools/v9_open_corpus_to_material.py`。\n\n"
            % (cat, a.src, tag, lic))
    with io.open(out, "w", encoding="utf-8") as fh:
        fh.write(head)
        for b in blocks:
            fh.write("\n" + b.rstrip() + "\n\n")
    from collections import Counter
    cnt = Counter()
    for blk in G.parse_blocks(io.open(out, encoding="utf-8").read()):
        if not (G.parse_turns(blk) or G.parse_meta(blk)):
            continue
        cnt[G.check_block("x", blk, "general")["status"]] += 1
    print("已写 -> %s ｜门禁 %s" % (os.path.relpath(out, ROOT), dict(cnt)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
