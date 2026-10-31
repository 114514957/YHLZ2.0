#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""角色语言画像：从已抽取的台词里统计自称、句长、语气、口癖、高频词。

只做统计与短句示例（≤60字），不做整段复制。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import statistics
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(CACHE, "char_voice_profile.json")

SELF_REFS = ["本小姐", "老娘", "咱", "人家", "本座", "朕", "我", "吾"]
STOP = set("""的 了 是 在 我 你 他 她 它 们 这 那 就 也 都 还 又 但 是 不 会 有 和 与 对 到 把 被
给 让 说 一个 什么 怎么 这个 那个 我们 你们 他们 自己 现在 时候 可以 已经 因为 所以 但是
如果 虽然 只是 不过 而且 就是 有点 有些 一样 这样 那样 这里 那里 知道 觉得 应该 需要""".split())


def load_all() -> dict[str, list[tuple[str, str]]]:
    data: dict[str, list[tuple[str, str]]] = {}
    for p in glob.glob(os.path.join(CACHE, "book_dialogue_v4_*.json")):
        d = json.load(io.open(p, encoding="utf-8"))
        for name, rows in d["samples"].items():
            data.setdefault(name, []).extend(rows)
    return data


def profile(lines: list[str]) -> dict:
    lens = [len(x) for x in lines]
    joined = "\n".join(lines)
    self_ref = {w: joined.count(w) for w in SELF_REFS if joined.count(w)}
    q = sum(1 for x in lines if x.rstrip().endswith(("？", "?")))
    ex = sum(1 for x in lines if x.rstrip().endswith("！"))
    dots = sum(1 for x in lines if "…" in x)
    # 高频词
    import jieba
    c = Counter()
    for line in lines:
        for w in jieba.cut(line):
            w = w.strip()
            if len(w) >= 2 and w not in STOP and not re.fullmatch(r"[\W_]+", w):
                c[w] += 1
    # 句首词（前 2 字）
    head = Counter(x[:2] for x in lines if len(x) >= 2)
    return {
        "n": len(lines),
        "len_mean": round(statistics.mean(lens), 1) if lens else 0,
        "len_median": round(statistics.median(lens), 1) if lens else 0,
        "len_p90": round(sorted(lens)[int(len(lens) * 0.9)], 1) if lens else 0,
        "len_max": max(lens) if lens else 0,
        "self_ref": self_ref,
        "question_ratio": round(q / max(len(lines), 1), 3),
        "exclaim_ratio": round(ex / max(len(lines), 1), 3),
        "ellipsis_ratio": round(dots / max(len(lines), 1), 3),
        "top_words": c.most_common(28),
        "top_heads": head.most_common(10),
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    data = load_all()
    if not data:
        print("没有抽取数据")
        return 2
    out = {}
    print("=" * 78)
    for name, rows in sorted(data.items(), key=lambda kv: -len(kv[1])):
        lines = [l for _, l in rows]
        p = profile(lines)
        out[name] = p
        print("\n【%s】%d 条台词" % (name, p["n"]))
        print("  句长 均值 %.1f / 中位 %.1f / p90 %.1f / 最长 %d"
              % (p["len_mean"], p["len_median"], p["len_p90"], p["len_max"]))
        print("  自称: %s" % p["self_ref"])
        print("  问句 %.0f%% ｜ 感叹 %.0f%% ｜ 含省略号 %.0f%%"
              % (p["question_ratio"] * 100, p["exclaim_ratio"] * 100,
                 p["ellipsis_ratio"] * 100))
        print("  高频词: %s" % "、".join(w for w, _ in p["top_words"][:16]))
        print("  句首: %s" % "、".join("%s(%d)" % (w, n) for w, n in p["top_heads"][:6]))
    json.dump(out, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已存: %s" % os.path.relpath(OUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
