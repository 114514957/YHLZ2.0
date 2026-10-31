#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽角色台词（v2：段落级归属）。

v1 问题：要求"姓名紧贴引号+说话动词"，召回极低（奥黛丽 759 条只抽到 13 条），
因为中文小说常写「奥黛丽想了想，说道：“…”」，名字与动词间有插入语。

v2 规则（段落级，符合中文小说排版习惯）：
  1. 按空行/换行切段，**一段通常只有一个说话人**；
  2. 段内出现 `名字…(说|道|问|答|笑|叹…)` → 该段引号归此人；
  3. 段内没有 → 看**上一段末尾** 30 字、**下一段开头** 30 字找 `名字+动词`；
  4. 仍判定不出的，丢弃（宁缺勿错）。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "cache", "book_index.json")
QUOTE = re.compile(r"[“「]([^”」]{2,400})[”」]")
VERB = r"(?:说道|问道|答道|笑道|喊道|叫道|叹道|低声道|轻声道|说|道|问|答|喊|笑|叹|自语|嘟囔)"


def is_dialogue(q: str) -> bool:
    """判断引号内是不是"说的话"（而非术语/强调）。

    台词特征：含句末或句中语气标点，或足够长且带逗号。
    术语特征：短名词短语，无任何标点。
    """
    q = q.strip()
    if len(q) < 4:
        return False
    if re.search(r"[。！？…，、；：]", q):
        return True
    return len(q) >= 10


def find_speaker_any(seg: str) -> str:
    """在片段里找**任何**说话人（不限目标角色）。

    必须先认全，再筛目标——否则"只找目标角色"会在目标没说话时，
    把上一段目标角色说的话错算到本段（实测过的真实错判）。
    """
    VERBS = r"(?:说道|问道|答道|笑道|喊道|叫道|叹道|强调|补充|继续|低声|轻声|沉声|说|道|问|答|喊|笑|叹|自语|嘟囔)"
    OBJ_MARK = r"(?:对|向|朝|跟|望着|看着|望向|看回|看向|回答|代替|替|给|和)"
    NAME = r"([\u4e00-\u9fa5]{2,4})"
    pats = [
        re.compile(NAME + r"[^。！？\n]{0,14}?" + VERBS + r"\s*[：:]\s*$"),
        re.compile(NAME + r"[^。！？\n]{0,14}?" + VERBS + r"\s*[：:]\s*[“「]"),
        re.compile(r"[”」]\s*" + NAME + r"[^。！？\n]{0,10}?" + VERBS),
    ]
    NOT_NAME = {"说到这里", "说到这里", "接着又说", "然后又说", "于是又说", "随后又说"}
    best, best_pos = "", -1
    for pat in pats:
        for m in pat.finditer(seg):
            n = m.group(1)
            if n in NOT_NAME:
                continue
            before = seg[max(0, m.start() - 3):m.start()]
            if re.search(OBJ_MARK + r"$", before):
                continue        # 宾语位 → 听话人，不是说话人
            if m.start() > best_pos:
                best, best_pos = n, m.start()
    return best


def paragraphs(text: str) -> list[str]:
    # 中文小说常以全角空格缩进 + 换行分段
    parts = re.split(r"\n+|(?<=[。！？…”」])\s{2,}", text)
    return [p.strip() for p in parts if p.strip()]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) < 3:
        print("用法: v9_book_dialogue2.py <书名关键词> <角色1,角色2,...> [每角色条数]")
        return 2
    book_kw = sys.argv[1]
    names = [x.strip() for x in sys.argv[2].split(",") if x.strip()]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    idx = json.load(io.open(IDX, encoding="utf-8"))
    b = next((x for x in idx["books"] if book_kw in x["book"]), None)
    if not b:
        print("没找到书:", book_kw)
        return 2
    print("== %s ｜ 角色: %s ==" % (b["book"], "、".join(names)))

    got: dict[str, list[tuple[str, str]]] = {n: [] for n in names}
    stat = Counter()
    scanned = 0
    for ch in b["files"]:
        p = os.path.join(ROOT, ch["path"])
        text = io.open(p, encoding="utf-8", errors="replace").read()
        scanned += 1
        paras = paragraphs(text)
        for i, para in enumerate(paras):
            quotes = [q for q in QUOTE.findall(para) if is_dialogue(q)]
            if not quotes:
                continue
            spk = find_speaker_any(para)
            if not spk and i > 0:
                # 只回看上一段（对话提示符常独占一段）。**不往后段找**——
                # 实测"往后段找"会把下一段的说话人错算到本段引号上。
                spk = find_speaker_any(paras[i - 1][-60:])
            if spk not in names:
                stat["非目标角色" if spk else "无法判定"] += 1
                continue
            stat[spk] += len(quotes)
            if len(got[spk]) < limit:
                for q in quotes:
                    if len(got[spk]) < limit and len(q) >= 4:
                        got[spk].append((ch["file"][:5], q.strip()))
        if all(len(v) >= limit for v in got.values()):
            break

    print("扫描 %d 章｜归属统计: %s" % (scanned, dict(stat)))
    for n in names:
        print("\n【%s】取样 %d 条" % (n, len(got[n])))
        for f, line in got[n]:
            print("   [%s] %s" % (f, line[:120]))

    out = os.path.join(ROOT, "cache", "book_dialogue_samples_v2.json")
    with io.open(out, "w", encoding="utf-8") as fh:
        json.dump({"book": b["book"], "scanned": scanned, "stat": dict(stat),
                   "samples": got}, fh, ensure_ascii=False, indent=1)
    print("\n已存: %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
