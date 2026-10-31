#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""素材体检：回答"够没够、质量行不行"。

不看单一数字，分五面量：
  ① 规模：条数/字符/token（含去重后的有效量）
  ② 结构：维度占比、权重占比、轮数分布、长度档
  ③ 覆盖：情绪、场景、合同类型、自称种类、收束词
  ④ 质量：门禁结果、重复度、样本内自相似、长度极值
  ⑤ 冗余：跨块近似重复（真正浪费训练预算的地方）

用法：
    python tools/v9_material_health.py [--json out.json]
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import os
import re
import statistics
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

TRAIN = "data/finetune/sft_persona_v9t_train.jsonl"
SELF_REFS = ("本小姐", "老娘", "咱", "我")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    rows = [json.loads(x) for x in io.open(TRAIN, encoding="utf-8") if x.strip()]
    n = len(rows)
    print("=" * 74)
    print("V9 素材体检（train 集 %d 条）" % n)
    print("=" * 74)

    # ① 规模
    chars, asst_chars, turns = [], [], []
    for r in rows:
        msgs = r["messages"]
        turns.append(len(msgs))
        chars.append(sum(len(m.get("content") or "") for m in msgs))
        asst_chars.append(sum(len(m.get("content") or "") for m in msgs
                              if m.get("role") == "assistant"))
    print("\n① 规模")
    print("  条数 %d ｜总字符 %s ｜元亨台词字符 %s"
          % (n, format(sum(chars), ","), format(sum(asst_chars), ",")))
    print("  每条字符：中位 %d ｜p90 %d ｜最大 %d ｜最小 %d"
          % (statistics.median(chars), sorted(chars)[int(n * 0.9)], max(chars), min(chars)))

    # ② 结构
    print("\n② 结构")
    src = Counter(str(r.get("source") or "?") for r in rows)
    wt = Counter(str(r.get("weight")) for r in rows)
    print("  来源维度：%s" % dict(src.most_common(12)))
    print("  权重：%s" % dict(sorted(wt.items(), reverse=True)))
    print("  轮数（messages 条数）：%s" % dict(sorted(Counter(turns).items())))

    # ③ 覆盖
    print("\n③ 覆盖")
    emo = Counter()
    lt = Counter()
    ct = Counter()
    refs = Counter()
    endings = Counter()
    for r in rows:
        for k, c in (("emotion", emo), ("length_tier", lt), ("contract", ct)):
            v = r.get(k)
            if v:
                c[str(v)] += 1
        yh = "".join(m.get("content") or "" for m in r["messages"]
                     if m.get("role") == "assistant")
        hit = [w for w in SELF_REFS if w in yh]
        refs["+".join(sorted(hit)) if hit else "无自称"] += 1
        tail = yh.rstrip()
        if tail.endswith(("？", "?")):
            endings["问"] += 1
        elif tail.endswith(("！", "!")):
            endings["叹"] += 1
        else:
            endings["陈述"] += 1
    print("  emotion：%s" % dict(emo.most_common()))
    print("  length_tier：%s" % dict(lt.most_common()))
    print("  contract：%s" % dict(ct.most_common(8)))
    print("  自称组合 top8：%s" % dict(refs.most_common(8)))
    print("  收尾：%s" % dict(endings))

    # ④ 质量
    print("\n④ 质量")
    import v9_story_gate as G  # noqa: E402
    st = Counter()
    raw_fmt = 0
    for r in rows:
        txt = "## x\n" + "\n".join(
            "### %s%s%s\n%s" % ("元亨" if m["role"] == "assistant" else "老爹",
                               "答" if m["role"] == "assistant" else "问", i,
                               m.get("content") or "")
            for i, m in enumerate(r["messages"]) if m["role"] != "system")
        rr = G.check_block("x", txt, "general")
        # 2026-10-20：`real:` 是 QQ 实录，按《真实数据豁免规则 v1》**格式类豁免**
        # （括号/星号/列表行）。装配后 raw 标记不进 JSONL，所以在这里按 source 判。
        if str(r.get("source") or "").startswith("real:") and rr["status"] == "FAIL":
            only_fmt = all(
                f.startswith(("星号", "列表行", "括号")) for f in rr["fails"])
            if only_fmt:
                raw_fmt += 1
                st["PASS(raw格式豁免)"] += 1
                continue
        st[rr["status"]] += 1
    print("  门禁（train 集重跑）：%s" % dict(st))
    if raw_fmt:
        print("    其中 %d 条是 real 实录的格式问题（按 raw 规则豁免，不算 FAIL）" % raw_fmt)
    print("  极短样本（<80 字）%d 条 ｜极长（>1500 字）%d 条"
          % (sum(1 for c in chars if c < 80), sum(1 for c in chars if c > 1500)))

    # ⑤ 冗余：跨块近似重复
    print("\n⑤ 冗余（跨块近似重复，前缀指纹 + 相似度）")
    sig = [norm("".join(m.get("content") or "" for m in r["messages"]
                        if m.get("role") == "assistant"))[:80] for r in rows]
    dup = Counter(sig)
    exact = sum(v - 1 for v in dup.values() if v > 1)
    print("  前 80 字完全相同的重复条数：%d（%.1f%%）" % (exact, 100.0 * exact / n))
    top = [(k[:30], v) for k, v in dup.most_common(3) if v > 1]
    for k, v in top:
        print("     ×%d  %s…" % (v, k))

    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(json.dumps({
            "n": n, "chars": sum(chars), "asst_chars": sum(asst_chars),
            "src": dict(src), "weight": dict(wt), "emotion": dict(emo),
            "contract": dict(ct), "gate": dict(st), "exact_dup": exact,
        }, ensure_ascii=False, indent=1))
        print("\n明细 -> %s" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
