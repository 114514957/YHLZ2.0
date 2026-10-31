#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""素材符合性审查：把"要求"逐条落到可测项，逐文件给结论。

审查维度（来源于我们自己的规范）：
  A 结构   ：块结构、轮次问/答配对、必备元数据
  B 身份   ：只有 老爹/元亨/利贞 发言；大肥鱼无台词；元亨在答位
  C 内容门 ：禁词、助手腔、报告腔、括号动作、Markdown、分号冒号（仅提示）
  D 风格   ：句长起伏、短句占比、留白、称呼、自称多样性
  E 规模   ：块数/轮数/字符

用法：
    python tools/v9_conformance_audit.py [--json 输出路径]
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
MAT = os.path.join(ROOT, "docs", "素材")

import v9_story_gate as G  # noqa: E402

REQUIRED_META = ("emotion", "length_tier", "contract")  # 与 finetune_assemble.py:152 一致
ALLOWED_SPEAKERS = {"老爹", "元亨", "利贞", "陌生人", "朋友", "群友"}  # 与门禁 allowed_speakers 一致


def scan_file(path: str) -> dict:
    text = io.open(path, encoding="utf-8", errors="replace").read()
    blocks = G.parse_blocks(text)
    n_blocks = n_turns = 0
    fail_c = collections.Counter()
    warn_c = collections.Counter()
    meta_missing = collections.Counter()
    speakers = collections.Counter()
    yuan_ask = 0
    feiyu = 0
    bad_pair = 0
    neg_blocks = 0
    status_c = collections.Counter()
    for blk in blocks:
        if not G.parse_turns(blk) and not G.parse_meta(blk):
            continue
        n_blocks += 1
        name = blk.splitlines()[0][3:][:40]
        r = G.check_block(name, blk, "general")
        # 负样本（raw 记录里元亨说了客服腔）：内容不合格是**预期**的，不计 FAIL
        if r.get("negative"):
            neg_blocks += 1
            continue
        for f in r["fails"]:
            fail_c[re.sub(r"[×x]\d+", "", str(f)).split(":")[0].strip()] += 1
        for w in r["warns"]:
            warn_c[re.sub(r"[（(].*?[)）]", "", str(w)).split(":")[0].strip()] += 1
        # 元数据
        metas = dict(G.parse_meta(blk))
        for k in REQUIRED_META:
            if k not in metas:
                meta_missing[k] += 1
        status_c[str(metas.get("status", "(无)"))] += 1
        # 轮次/发言人
        turns = G.parse_turns(blk)
        n_turns += len(turns)
        heads = re.findall(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", blk, re.MULTILINE)
        seq = []
        for who, kind, num in heads:
            who = who.strip()
            speakers[who] += 1
            seq.append((who, kind))
            if who not in ALLOWED_SPEAKERS and "大肥鱼" in who:
                feiyu += 1
        if seq and seq[0] == ("元亨", "问"):
            yuan_ask += 1
        # 问/答交替检查
        for i, (who, kind) in enumerate(seq):
            want = "问" if i % 2 == 0 else "答"
            if kind != want:
                bad_pair += 1
                break
    return {
        "file": os.path.basename(path), "blocks": n_blocks, "turns": n_turns,
        "fails": dict(fail_c.most_common()), "warns": dict(warn_c.most_common()),
        "meta_missing": dict(meta_missing), "status": dict(status_c),
        "speakers": dict(speakers.most_common()),
        "yuan_ask_first": yuan_ask, "feiyu_lines": feiyu, "bad_pair": bad_pair,
        "neg_blocks": neg_blocks,
        "fail_total": sum(fail_c.values()), "warn_total": sum(warn_c.values()),
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(ROOT, "cache", "conformance.json"))
    a = ap.parse_args()

    rows = []
    for f in sorted(os.listdir(MAT)):
        if not f.endswith(".md"):
            continue
        r = scan_file(os.path.join(MAT, f))
        if r["blocks"]:
            rows.append(r)

    print("=" * 96)
    print("素材符合性审查（docs/素材/，口径：门禁 general）")
    print("=" * 96)
    print("%-24s %6s %7s %6s %6s %8s %8s" % ("文件", "块数", "轮数", "FAIL", "WARN", "元亨首问", "配对错"))
    tot = collections.Counter()
    for r in rows:
        print("%-24s %6d %7d %6d %6d %8d %8d"
              % (r["file"], r["blocks"], r["turns"], r["fail_total"],
                 r["warn_total"], r["yuan_ask_first"], r["bad_pair"]))
        for k in ("blocks", "turns", "fail_total", "warn_total", "yuan_ask_first", "bad_pair"):
            tot[k] += r[k]
    print("%-24s %6d %7d %6d %6d %8d %8d"
          % ("合计", tot["blocks"], tot["turns"], tot["fail_total"],
             tot["warn_total"], tot["yuan_ask_first"], tot["bad_pair"]))

    print("\n【A 结构·元数据缺失】")
    mm = collections.Counter()
    for r in rows:
        for k, v in r["meta_missing"].items():
            mm[k] += v
    print("  ", dict(mm) or "无缺失")

    print("\n【B 身份】")
    sp = collections.Counter()
    for r in rows:
        for k, v in r["speakers"].items():
            sp[k] += v
    print("  发言人分布:", dict(sp.most_common(8)))
    print("  大肥鱼有台词:", sum(r["feiyu_lines"] for r in rows), "处")
    print("  首轮即元亨问:", tot["yuan_ask_first"], "块")
    print("  问/答未交替:", tot["bad_pair"], "块")

    print("\n【C 内容门·FAIL 原因合计】")
    fc = collections.Counter()
    for r in rows:
        for k, v in r["fails"].items():
            fc[k] += v
    for k, v in fc.most_common(10):
        print("   %-28s %4d" % (k, v))

    print("\n【D 风格·WARN 原因合计】")
    wc = collections.Counter()
    for r in rows:
        for k, v in r["warns"].items():
            wc[k] += v
    for k, v in wc.most_common(10):
        print("   %-28s %4d" % (k, v))

    with io.open(a.json, "w", encoding="utf-8") as fh:
        json.dump({"rows": rows, "total": dict(tot)}, fh, ensure_ascii=False, indent=1)
    print("\n明细: %s" % os.path.relpath(a.json, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
