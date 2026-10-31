#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把宪章扫描的"一档硬红线"命中逐条带上下文打出来（只读）。

用途：一档命中必须逐条人看。本脚本输出每条命中的**规则 / 片段 / 命中位置前后 60 字**，
按文件与人审优先级排序，便于一次性判定"是问题"还是"拒绝样本/讨论语境"。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tools"))
from v9_constitution_scan import HARD_RULES, MATERIAL_GLOBS, CORPUS_FILES  # noqa: E402


def show(s: str) -> None:
    print(s)


def hits_with_context(text: str):
    for name, pat in HARD_RULES:
        for m in re.finditer(pat, text):
            a = max(0, m.start() - 60)
            b = min(len(text), m.end() + 60)
            yield name, m.group(0), text[a:b].replace("\n", " ")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    total = 0
    print("=" * 78)
    print("一档硬红线 · 逐条上下文（素材文件）")
    print("=" * 78)
    for g in MATERIAL_GLOBS:
        for p in sorted(glob.glob(os.path.join(PROJECT_ROOT, g))):
            if os.path.basename(p).startswith("_"):
                continue
            rel = os.path.relpath(p, PROJECT_ROOT)
            text = io.open(p, "r", encoding="utf-8", errors="replace").read()
            rows = list(hits_with_context(text))
            if not rows:
                continue
            print("\n--- %s（%d 处）---" % (rel, len(rows)))
            for name, frag, ctx in rows[:12]:
                total += 1
                print("  [%s] 「%s」" % (name, frag))
                print("      …%s…" % ctx)

    print("\n" + "=" * 78)
    print("一档硬红线 · 逐条上下文（语料集，只打前若干条）")
    print("=" * 78)
    for rel in CORPUS_FILES:
        p = os.path.join(PROJECT_ROOT, rel)
        if not os.path.exists(p):
            continue
        n = 0
        print("\n--- %s ---" % rel)
        with io.open(p, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msgs = rec.get("messages")
                text = ("\n".join(str(m.get("content") or "") for m in msgs)
                        if isinstance(msgs, list) else str(rec.get("text") or ""))
                rows = list(hits_with_context(text))
                if rows:
                    n += 1
                    total += 1
                    if n <= 10:
                        print("  行%d [%s] 「%s」" % (i, rows[0][0], rows[0][1]))
                        print("      …%s…" % rows[0][2][:150])
        print("  （该文件一档命中记录数：%d）" % n)

    print("\n一档命中合计（去重前）：%d 处" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
