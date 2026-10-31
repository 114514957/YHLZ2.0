#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 opendialogue 压到 ~15%：从 2,000 块里挑最优的 700 块，其余归档。

老爹 2026-10-21「压缩」。按实测影响定的：34.2% 会把元亨的自称率从 49.4% 压到 0.3%、
长句能力抹成 0、叫"老爹"率压 80 倍。压到 15% 能保住对话节奏又不冲掉人格。

挑选口径（打分，不随机砍）：
  · 多轮优先：3 轮 > 2 轮 > 1 轮
  · 句长合适：元亨平均 8–40 字（太短是碎片，太长不像口语）
  · 有态度：否定/反问/感叹/损人/玩笑
  · **先剔垃圾**：纯笑声/纯重复字符/纯标点/全程 <6 字
"""
from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import v9_story_gate as G  # noqa: E402

P = os.path.join(ROOT, "docs", "素材", "开源对话样本.md")
ARCHIVE = os.path.join(ROOT, "docs", "素材", "_待定", "开源对话样本_未入选_20261021.md")

ATTITUDE = re.compile(r"不是|才不|谁|凭什么|怎么|干嘛|别|少来|凭啥|不服|笑话|"
                      r"我就|偏|倒|哼|哈|呸|滚|反了|有趣|有意思|离谱|夸张")
REPEAT = re.compile(r"(.)\1{5,}")          # 同一字符连 6 次以上
ONLY_LAUGH = re.compile(r"^[哈呵嘿嘻嗯哦噢额啊呀嘛哈~～\s。，！？、…]*$")


def parse(b: str):
    name = b.split("\n")[0].strip()
    meta, turns, cur, role = [], [], False, None
    for ln in b.split("\n")[1:]:
        s = ln.strip()
        if s.startswith("- "):
            meta.append(s)
        elif s.startswith("### "):
            role = "老爹" if "问" in s else "元亨"
            cur = True
        elif cur and role and s:
            turns.append((role, s))
            cur = False
    return name, meta, turns


def junk(turns) -> str:
    ys = [t for r, t in turns if r == "元亨"]
    if not ys:
        return "无元亨"
    if all(ONLY_LAUGH.match(t) for t in ys):
        return "纯语气词/笑声"
    if any(REPEAT.search(t) for t in ys):
        return "重复字符"
    if all(len(t) < 6 for t in ys):
        return "全短碎片"
    return ""


def score(turns) -> float:
    ys = [t for r, t in turns if r == "元亨"]
    lens = [len(t) for t in ys]
    avg = sum(lens) / len(lens)
    s = min(len(ys), 3) * 2.0
    s += 3.0 if 8 <= avg <= 40 else (1.5 if 5 <= avg < 8 or 40 < avg <= 60 else 0.0)
    s += min(sum(len(ATTITUDE.findall(t)) for t in ys), 2) * 1.5
    return s, avg, len(ys)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=700)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    text = io.open(P, encoding="utf-8").read()
    head = re.search(r"(?ms)^(.*?)(?=^## )", text).group(1)
    raw = re.split(r"(?m)^## ", text)[1:]
    print("现有 %d 块，目标保留 %d 块" % (len(raw), a.keep))

    pool, bad = [], {}
    for b in raw:
        name, meta, turns = parse(b)
        why = junk(turns)
        if why:
            bad[why] = bad.get(why, 0) + 1
            continue
        sc, avg, nr = score(turns)
        pool.append({"name": name, "meta": meta, "turns": turns,
                     "sc": sc, "avg": avg, "nr": nr})
    print("先剔垃圾 %d 块：%s" % (sum(bad.values()), bad))

    pool.sort(key=lambda r: (-r["sc"], -r["nr"], -r["avg"]))
    keep, drop = pool[:a.keep], pool[a.keep:]
    print("候选 %d → 保留 %d ｜归档 %d" % (len(pool), len(keep), len(drop)))

    def render(rec):
        body, qi, ai = [], 0, 0
        for r, t in rec["turns"]:
            if r == "老爹":
                qi += 1
                body.append("### 老爹问%d\n%s" % (qi, t))
            else:
                ai += 1
                body.append("### 元亨答%d\n%s" % (ai, t))
        return "## %s\n" % rec["name"] + "\n".join(rec["meta"]) + "\n" + "\n".join(body) + "\n"

    new_head = head.replace(
        "> **通过者的台词一字未改**",
        "> **通过者的台词一字未改**（本批按 2026-10-21「压缩」从 2,000 块里择优保留 %d 块，"
        "其余归档至 `_待定/开源对话样本_未入选_20261021.md`）" % len(keep))
    if a.dry_run:
        al = sorted(r["avg"] for r in keep)
        from collections import Counter
        print("保留集画像：轮数 %s ｜句长中位 %.0f"
              % (dict(sorted(Counter(r["nr"] for r in keep).items())), al[len(al) // 2]))
        return 0

    os.makedirs(os.path.dirname(ARCHIVE), exist_ok=True)
    with io.open(ARCHIVE, "w", encoding="utf-8") as fh:
        fh.write("# 开源对话样本（未入选，%d 块）\n\n> 2026-10-21 压缩后归档，"
                 "保留在池里备用。\n\n" % len(drop))
        for r in drop:
            fh.write("\n" + render(r).rstrip() + "\n\n")
    with io.open(P, "w", encoding="utf-8") as fh:
        fh.write(new_head)
        for r in keep:
            fh.write("\n" + render(r).rstrip() + "\n\n")

    # 复核门禁
    cnt = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for b in re.split(r"(?m)^## ", io.open(P, encoding="utf-8").read())[1:]:
        if not b.strip():
            continue
        rr = G.check_block("x", "## " + b, "general")
        cnt[rr["status"]] = cnt.get(rr["status"], 0) + 1
    print("写回 %d 块｜归档 %d 块｜门禁 %s" % (len(keep), len(drop), cnt))
    print("归档 -> %s" % os.path.relpath(ARCHIVE, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
