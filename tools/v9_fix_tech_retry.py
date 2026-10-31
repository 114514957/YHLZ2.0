#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""补跑：只重写指定的技术块（按块头精确匹配）。"""
from __future__ import annotations

import io
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
MAT = os.path.join(ROOT, "docs", "素材")
REV = os.path.join(MAT, "_修订")

from v9_fix_tech_asker import ds_call, load_key, split_blocks, validate  # noqa: E402


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("用法: v9_fix_tech_retry.py 对话-34,对话-133,...")
        return 2
    keys = [k.strip() for k in sys.argv[1].split(",") if k.strip()]
    want = {"## %s｜技术" % k: k for k in keys}

    src = io.open(os.path.join(MAT, "对话样本.md"), encoding="utf-8", errors="replace").read()
    _h, *parts = re.split(r"(?m)^##\s+", src)
    picked = []
    for b in parts:
        block = "## " + b.rstrip() + "\n"
        key = block.split("\n", 1)[0].strip()
        if key in want:
            picked.append(block)
    print("命中 %d / 请求 %d 块" % (len(picked), len(keys)))

    k = load_key()
    outs, failed = [], []
    for i in range(0, len(picked), 3):
        chunk = picked[i:i + 3]
        user = ("请逐块改写下面 %d 个块，输出同样数量的块，用 `=====` 分隔。\n\n"
                "===== 原始块 =====\n" % len(chunk)) + "\n===== 原始块 =====\n".join(chunk)
        try:
            resp = ds_call(k, user)
        except Exception as exc:  # noqa: BLE001
            print("  [%d] API 失败: %s" % (i, exc))
            continue
        for b in split_blocks(resp):
            why = validate(b)
            if why:
                failed.append((b.split("\n", 1)[0], why))
            else:
                outs.append(b)
        print("  [%d/%d] 累计通过 %d" % (i + len(chunk), len(picked), len(outs)))

    print("\n通过 %d 块" % len(outs))
    for f in failed:
        print("   失败 %s: %s" % f)
    if outs:
        p = os.path.join(REV, "技术块改写_补跑_%s.md" % time.strftime("%Y%m%d_%H%M%S"))
        with io.open(p, "w", encoding="utf-8") as fh:
            fh.write("\n\n".join(outs) + "\n")
        print("已写: %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
