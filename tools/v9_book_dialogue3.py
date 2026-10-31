#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽角色台词 v3：两遍法（先建角色名词典，再归属）。

v1 太严（奥黛丽 759 条只抽到 13）；v2 姓名正则 `{2,4}` 贪婪把动词吃进名字
（「奥黛丽笑吟吟」里的"笑"被当名字一部分），召回崩到全书 10 条。

v3：
  pass1 扫全书，用 `(2-3字)(?:说|道|问|答|笑|叹|强调|继续)[：:]` 统计候选名，
        取频次 ≥ MIN_FREQ 的入词典（自动排除"说到这里"这类非人名）。
  pass2 用词典做**最长优先**交替匹配，再按段落判归属；只保留目标角色。
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
CAND = re.compile(r"([\u4e00-\u9fa5]{2,3})(?:说道|问道|答道|笑道|喊道|叫道|叹道|强调|补充|继续|低声|轻声|沉声|说|道|问|答|喊|笑|叹|自语|嘟囔)\s*[：:]")
STOPWORDS = set("""说到这里 接着又说 然后又说 于是又说 随后又说 顿了顿 沉默片刻 想了想
不知道 这时候 那时候 然后 于是 但是 可是 所以 如果 因为 虽然 只是 不过 而且 就是
有点 有些 什么 怎么 这个 那个 他们 我们 你们 自己 大家 别人 人家 对方 心里 心中
低声 轻声 沉声 大声 小声 忽然 突然 立刻 马上 终于 只好 只能 一边 接着 随后 紧跟着""".split())


def paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n+|(?<=[。！？…”」])\s{2,}", text)
    return [p.strip() for p in parts if p.strip()]


def is_dialogue(q: str) -> bool:
    q = q.strip()
    if len(q) < 4:
        return False
    if re.search(r"[。！？…，、；：]", q):
        return True
    return len(q) >= 10


def build_dict(book: dict, min_freq: int = 25) -> list[str]:
    c = Counter()
    for ch in book["files"]:
        text = io.open(os.path.join(ROOT, ch["path"]), encoding="utf-8",
                       errors="replace").read()
        for m in CAND.finditer(text):
            n = m.group(1)
            if n not in STOPWORDS:
                c[n] += 1
    names = [n for n, v in c.items() if v >= min_freq]
    names.sort(key=len, reverse=True)   # 最长优先
    return names


def find_speaker(seg: str, alt: str) -> str:
    VERBS = r"(?:说道|问道|答道|笑道|喊道|叫道|叹道|强调|补充|继续|低声|轻声|沉声|说|道|问|答|喊|笑|叹|自语|嘟囔)"
    OBJ_MARK = r"(?:对|向|朝|跟|望着|看着|望向|看回|看向|回答|代替|替|给|和)"
    pats = [
        re.compile(r"(" + alt + r")[^。！？\n]{0,14}?" + VERBS + r"\s*[：:]\s*$"),
        re.compile(r"(" + alt + r")[^。！？\n]{0,14}?" + VERBS + r"\s*[：:]\s*[“「]"),
        re.compile(r"[”」]\s*(" + alt + r")[^。！？\n]{0,10}?" + VERBS),
    ]
    best, best_pos = "", -1
    for pat in pats:
        for m in pat.finditer(seg):
            before = seg[max(0, m.start() - 3):m.start()]
            if re.search(OBJ_MARK + r"$", before):
                continue
            if m.start() > best_pos:
                best, best_pos = m.group(1), m.start()
    return best


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) < 3:
        print("用法: v9_book_dialogue3.py <书名关键词> <角色1,角色2> [每角色条数] [min_freq]")
        return 2
    kw = sys.argv[1]
    targets = [x.strip() for x in sys.argv[2].split(",") if x.strip()]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    min_freq = int(sys.argv[4]) if len(sys.argv) > 4 else 25

    idx = json.load(io.open(IDX, encoding="utf-8"))
    b = next((x for x in idx["books"] if kw in x["book"]), None)
    if not b:
        print("没找到:", kw)
        return 2

    names = build_dict(b, min_freq)
    # 目标角色强制入词典：奥黛丽这类常写「奥黛丽…想了片刻…道：」（名字与动词间有插入语），
    # 只靠"名字紧跟动词"统计会达不到阈值而被漏掉（实测 216 处带插入语 vs 11 处紧邻）。
    for t in targets:
        if t not in names:
            names.append(t)
    names.sort(key=len, reverse=True)
    missing = [t for t in targets if t not in names]
    print("== %s ==" % b["book"])
    print("角色词典 %d 个（频次≥%d）｜目标: %s" % (len(names), min_freq, "、".join(targets)))
    if missing:
        print("  ⚠️ 目标不在词典里（可能取名不准）:", missing)
    alt = "|".join(re.escape(n) for n in names if n)

    got = {t: [] for t in targets}
    stat = Counter()
    scanned = 0
    for ch in b["files"]:
        text = io.open(os.path.join(ROOT, ch["path"]), encoding="utf-8",
                       errors="replace").read()
        scanned += 1
        paras = paragraphs(text)
        for i, para in enumerate(paras):
            qs = [q for q in QUOTE.findall(para) if is_dialogue(q)]
            if not qs:
                continue
            spk = find_speaker(para, alt)
            if not spk and i > 0:
                spk = find_speaker(paras[i - 1][-60:], alt)
            if not spk:
                stat["无法判定"] += 1
                continue
            if spk not in targets:
                stat["非目标"] += 1
                continue
            stat[spk] += len(qs)
            for q in qs:
                if len(got[spk]) < limit:
                    got[spk].append((ch["file"][:5], q.strip()))
        if all(len(v) >= limit for v in got.values()):
            break

    print("扫描 %d 章｜%s" % (scanned, dict(stat)))
    for t in targets:
        print("\n【%s】取样 %d 条" % (t, len(got[t])))
        for f, line in got[t][:limit]:
            print("   [%s] %s" % (f, line[:110]))

    out = os.path.join(ROOT, "cache", "book_dialogue_v3.json")
    with io.open(out, "w", encoding="utf-8") as fh:
        json.dump({"book": b["book"], "names": names[:300], "scanned": scanned,
                   "stat": dict(stat), "samples": got}, fh, ensure_ascii=False, indent=1)
    print("\n已存: %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
