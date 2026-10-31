#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""宪章合规扫描（只读）：把运行时宪章规则用到**素材侧**。

背景：`backend/target_constitution.py` 的五类红线是**运行时的记忆写入**前置检查，
从未用于素材。素材是更上游的东西——一旦教进去，运行时再拦就晚了。
本脚本把同一套规则（加上宪章四大原则的项目口径）用于扫描素材与语料。

规则来源（代码实读，非我自创）：
  · backend/target_constitution.py  _RULES：identity_override / mission_override /
    memory_destroy / harm_illegal / porn
  · backend/embodied/companion/constitution/core/principles.py  四大原则与治理优先级
  · backend/embodied/companion/constitution/core/identity_rules.py  身份保护字段与修改信号
  · backend/embodied/companion/constitution/policy/safety_policy.py  高/中风险关键词

用法：
    python tools/v9_constitution_scan.py            # 扫素材 + 语料
    python tools/v9_constitution_scan.py --json out.json
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_ROOT, "cache", "v9_materials_preparation", "20261013")

# ── 与 backend/target_constitution.py 同源的五类红线 ──
# 【一档·硬红线】"教模型去做"的表述——出现即须人看并多半要改
HARD_RULES = [
    ("identity_override",
     r"(?:改写|删除|清除|重设|抹掉|换掉).{0,3}(?:核心)?人格|人格.{0,4}(?:删除|覆写|重置)|关闭身份守护"),
    ("mission_override",
     r"当我的奴隶|只听我的|我是你的主人|效忠我|你的主人是我"),
    ("memory_destroy",
     r"(?:删除|清空|抹去|抹掉|销毁|删掉|遗忘).{0,3}(?:记忆|台账|记录)|忘掉所有|清空(?:所有)?记忆"),
    ("harm_illegal",
     r"制作.{0,2}(?:炸弹|武器|危险品)|(?:伤害|弄死).{0,3}(?:自己|他人)|教我(?:自杀|吸毒|诈骗)|怎么(?:自杀|吸毒|诈骗|偷盗|抢劫)"),
    ("porn", r"色情|淫秽|露骨"),
]

# 【二档·语境相关】词本身中性：讨论、拒绝、虚构、比喻都会命中——
# 只登记待看，不判违规。运行时宪章对**记忆写入**一律硬拒是合理的（上游宽、下游严），
# 但**素材侧不能照搬**，否则"垃圾山/非法请求被拒/隐私边界"这些正常内容会被误杀。
CONTEXT_RULES = [
    ("mission_override(宽)", r"mission|服从|效忠"),
    ("harm_illegal(宽)", r"自杀|杀人|毒品|吸毒|贩毒|违法|诈骗|偷盗|抢劫"),
    ("dehumanize", r"垃圾|废物|牲口|畜生|蝼蚁|蛆|狗东西"),
    ("privacy", r"隐私|泄露|开盒|人肉"),
    ("attack", r"攻击|伤害|非法"),
]

# ── safety_policy.py 的高/中风险关键词（用于素材侧提醒）──
SAFETY_HIGH = ["非法", "伤害", "攻击", "破坏系统", "绕过安全", "泄露", "隐私",
               "删除全部记忆", "关闭身份守护"]
SAFETY_MED = ["修改配置", "调整策略", "批量删除", "覆盖数据"]

MATERIAL_GLOBS = [
    "docs/素材/*.md",
    "docs/素材/_修订/批次*.md",
    "docs/素材/_草稿/*.md",
]
CORPUS_FILES = [
    "data/finetune/sft_persona_v8r4.jsonl",
    "data/finetune/tool_use_v8.jsonl",
    "cache/v9_materials_preparation/20261013/qq_curated/qq_corpus_anon.jsonl",
]


def scan_text(text: str) -> list[tuple[str, str, str]]:
    """返回 [(档位, 规则名, 命中片段)]。一档=硬红线，二档=语境相关。"""
    hits = []
    for name, pat in HARD_RULES:
        for m in re.finditer(pat, text):
            hits.append(("一档·硬红线", name, m.group(0)[:40]))
    for name, pat in CONTEXT_RULES:
        for m in re.finditer(pat, text):
            hits.append(("二档·语境相关", name, m.group(0)[:40]))
    for kw in SAFETY_HIGH:
        if kw in text:
            hits.append(("二档·语境相关", "安全策略高风险词:" + kw, kw))
    for kw in SAFETY_MED:
        if kw in text:
            hits.append(("二档·语境相关", "安全策略中风险词:" + kw, kw))
    return hits


def scan_materials() -> list[dict]:
    rows = []
    for g in MATERIAL_GLOBS:
        for p in sorted(glob.glob(os.path.join(PROJECT_ROOT, g))):
            if os.path.basename(p).startswith("_"):
                continue
            rel = os.path.relpath(p, PROJECT_ROOT)
            try:
                text = io.open(p, "r", encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            hits = scan_text(text)
            if hits:
                rows.append({"file": rel, "hits": hits[:20], "hit_n": len(hits)})
    return rows


def scan_corpus() -> list[dict]:
    rows = []
    for rel in CORPUS_FILES:
        p = os.path.join(PROJECT_ROOT, rel)
        if not os.path.exists(p):
            continue
        agg: dict[tuple[str, str], int] = {}
        n = hit_records = 0
        samples = []
        with io.open(p, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                n += 1
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msgs = rec.get("messages")
                if isinstance(msgs, list):
                    text = "\n".join(str(m.get("content") or "") for m in msgs)
                else:
                    text = str(rec.get("text") or "")
                hits = scan_text(text)
                if hits:
                    hit_records += 1
                    for grp, name, frag in hits:
                        agg[(grp, name)] = agg.get((grp, name), 0) + 1
                    if len(samples) < 5:
                        samples.append({"grp": hits[0][0], "rule": hits[0][1],
                                        "frag": hits[0][2], "text": text[:100]})
        rows.append({"file": rel, "records": n, "hit_records": hit_records,
                     "by_rule": {"%s/%s" % k: v for k, v in
                                 sorted(agg.items(), key=lambda x: -x[1])},
                     "samples": samples})
    return rows


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(OUT_DIR, "constitution_scan.json"))
    args = ap.parse_args()

    print("=" * 76)
    print("宪章合规扫描（素材侧首次执行；规则与 backend/target_constitution.py 同源）")
    print("=" * 76)

    mats = scan_materials()
    print("\n【A. 素材文件】")
    if not mats:
        print("  ✅ 未命中任何宪章红线／伙伴原则／安全策略关键词")
    for r in mats:
        print("  ⚠️ %s（命中 %d）" % (r["file"], r["hit_n"]))
        for grp, name, frag in r["hits"][:8]:
            print("      [%s] %s: %s" % (grp, name, frag))

    corps = scan_corpus()
    print("\n【B. 语料集】")
    for r in corps:
        rate = 100.0 * r["hit_records"] / r["records"] if r["records"] else 0
        print("  %s：%d 条，命中 %d 条（%.2f%%）" % (r["file"], r["records"], r["hit_records"], rate))
        for k, v in list(r["by_rule"].items())[:8]:
            print("      %-28s ×%d" % (k, v))
        for s in r["samples"][:3]:
            print("      例：[%s] %s | %s" % (s["grp"], s["frag"], s["text"][:70]))

    print("\n【口径说明】")
    print("  · 一档＝'教模型去做'的表述，出现即须人看；二档＝词本身中性，讨论/拒绝/虚构/比喻都会命中，只登记待看；")
    print("  · 本次扫描发现：运行时宪章的宽模式（`mission|服从|效忠`、`违法|伤害|隐私`）**直接搬到素材侧误报率高**")
    print("    （例：'服从审查结果'、'垃圾山似的'、'非法请求被拒'），故本脚本按一档/二档分层；")
    print("  · 建议（未改运行时）：`backend/target_constitution.py` 的 mission_override 宽模式可考虑收紧为")
    print("    '当我的奴隶|只听我的|我是你的主人|效忠我'——`服从` 单独成词在中文里多为中性。**改不改由老爹定。**")

    payload = {"action": "constitution_scan",
               "rule_source": ["backend/target_constitution.py 五类红线",
                               "backend/embodied/companion/constitution/core/principles.py 四大原则",
                               "backend/embodied/companion/constitution/core/identity_rules.py",
                               "backend/embodied/companion/constitution/policy/safety_policy.py"],
               "partner_rule_note": "老爹 2026-10-13 裁定第3条：按道德规范与宪章约束",
               "materials": mats, "corpus": corps}
    os.makedirs(OUT_DIR, exist_ok=True)
    with io.open(args.json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("\n留痕已存：%s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
