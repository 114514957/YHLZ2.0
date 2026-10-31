#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽角色台词 v4：用 jieba 词性标注（nr=人名）建角色词典，再按段落归属。

v3 用朴素正则建词典，被「的笑容/然开口/斟酌着/了一声」这类碎片污染，
且真实人名（阿尔杰）反而不在词典里 → 归属退化到"上一段说话人"，产生错判。

v4：jieba.posseg 抽 nr 词 + 目标角色强制入册 + 频次过滤。
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
CACHE = os.path.join(ROOT, "cache", "book_names_jieba.json")
QUOTE = re.compile(r"[“「]([^”」]{2,400})[”」]")


def paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n+|(?<=[。！？…”」])\s{2,}", text)
    return [p.strip() for p in parts if p.strip()]


def is_dialogue(q: str) -> bool:
    q = q.strip()
    if len(q) < 4:
        return False
    return bool(re.search(r"[。！？…，、；：]", q)) or len(q) >= 10


def build_names(book: dict, min_freq: int = 20, max_chapters: int = 0) -> list[str]:
    import jieba.posseg as pseg
    if os.path.exists(CACHE):
        try:
            d = json.load(io.open(CACHE, encoding="utf-8"))
            if d.get("book") == book["book"]:
                return d["names"]
        except Exception:
            pass
    c = Counter()
    files = book["files"][:max_chapters] if max_chapters else book["files"]
    for ch in files:
        text = io.open(os.path.join(ROOT, ch["path"]), encoding="utf-8",
                       errors="replace").read()
        for w, flag in pseg.cut(text):
            if flag.startswith("nr") and 2 <= len(w) <= 4:
                c[w] += 1
    names = [n for n, v in c.items() if v >= min_freq]
    names.sort(key=len, reverse=True)
    json.dump({"book": book["book"], "names": names, "full": dict(c.most_common(500))},
              io.open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return names


def find_speaker(seg: str, alt: str, tail_only: bool = False) -> str:
    """找说话人。

    tail_only=True 时只认"片段以 姓名…动词+冒号 结尾"这一种（用于回看上一段）——
    因为上一段若只是正文里提到某人（尤其是呼语「潘多拉，你…」），不能算她说话。
    """
    VERBS = r"(?:说道|问道|答道|笑道|喊道|叫道|叹道|强调|补充|继续|低声|轻声|沉声|说|道|问|答|喊|笑|叹|自语|嘟囔)"
    OBJ = r"(?:对|向|朝|跟|望着|看着|望向|看回|看向|回答|代替|替|给|和|冲|的|与|及|在|到|把|将|从|于|被)"
    pats = [
        re.compile(r"(" + alt + r")[^。！？\n]{0,14}?" + VERBS + r"\s*[：:]\s*$"),
    ]
    if tail_only:
        # 回退模式：**必须**以该角色名开头（"潘多拉静静地点了点头，然后问道："）。
        # 否则正文里被顺带提到的名字（"我摁了摁身旁潘多拉和维斯卡的脑袋，随口问道："）
        # 会被误当成说话人——第一人称小说里这种误判尤其多。
        pats = [re.compile(r"^\s*(" + alt + r")[^。！？\n]{0,14}?" + VERBS + r"\s*[：:]\s*$")]
    if not tail_only:
        pats += [
            re.compile(r"(" + alt + r")[^。！？\n]{0,14}?" + VERBS + r"\s*[：:]\s*[“「]"),
            re.compile(r"[”」]\s*(" + alt + r")[^。！？\n]{0,10}?" + VERBS),
        ]
    best, best_pos = "", -1
    for pat in pats:
        for m in pat.finditer(seg):
            if re.search(OBJ + r"$", seg[max(0, m.start() - 3):m.start()]):
                continue
            # 名字后紧跟「的」= 定语（"抚摸着潘多拉**的**头发，说道"），不是主语
            nxt = seg[m.end(1):m.end(1) + 1]
            if nxt == "的":
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
        print("用法: v9_book_dialogue4.py <书名> <角色1,角色2> [条数] [min_freq]")
        return 2
    kw = sys.argv[1]
    targets = [x.strip() for x in sys.argv[2].split(",") if x.strip()]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    min_freq = int(sys.argv[4]) if len(sys.argv) > 4 else 20

    idx = json.load(io.open(IDX, encoding="utf-8"))
    b = next((x for x in idx["books"] if kw in x["book"]), None)
    if not b:
        print("没找到:", kw)
        return 2

    names = build_names(b, min_freq)
    for t in targets:
        if t not in names:
            names.append(t)
    names.sort(key=len, reverse=True)
    alt = "|".join(re.escape(n) for n in names if n)
    print("== %s ==" % b["book"])
    print("jieba 人名 %d 个｜目标 %s" % (len(names), "、".join(targets)))
    print("词典前 20:", names[:20])

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
                # 只认"上一段以 姓名+动词+冒号 结尾"（提示符独占一段的写法）；
                # 否则正文里提到某人（尤其呼语「潘多拉，你…」）会被误当成说话人。
                spk = find_speaker(paras[i - 1][-60:], alt, tail_only=True)
            if not spk:
                stat["无法判定"] += 1
                continue
            if spk not in targets:
                stat["非目标"] += 1
                continue
            # 呼语过滤：引号前 10 字内出现「<该角色名>，」= 别人在叫她，不是她在说。
            # （实测漏网：「那什么，潘多拉，你是不是先和他们说点什么？」——名字不在开头）
            qs = [q for q in qs
                  if not re.search(r"^[^。！？]{0,10}" + re.escape(spk) + r"\s*[，,：:]", q)]
            if not qs:
                stat["呼语"] += 1
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

    tag = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", b["book"])[:12]
    out = os.path.join(ROOT, "cache", "book_dialogue_v4_%s.json" % tag)
    json.dump({"book": b["book"], "names": names[:400], "scanned": scanned,
               "stat": dict(stat), "samples": got},
              io.open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已存: %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
