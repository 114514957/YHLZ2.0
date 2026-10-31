#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""图书素材质量核查：重复章节、空白章、异常短章、乱码。"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "cache", "book_index.json")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    idx = json.load(io.open(IDX, encoding="utf-8"))
    for b in idx["books"]:
        hashes: dict[str, list[str]] = defaultdict(list)
        empty, tiny, mojibake = [], [], []
        for ch in b["files"]:
            p = os.path.join(ROOT, ch["path"])
            raw = open(p, "rb").read()
            text = raw.decode("utf-8", errors="replace")
            body = re.sub(r"\s+", "", text)
            if not body:
                empty.append(ch["file"])
            elif len(body) < 300:
                tiny.append((ch["file"], len(body)))
            if body.count("\ufffd") > 3 or len(re.findall(r"[\x00-\x08]", text)) > 5:
                mojibake.append(ch["file"])
            hashes[hashlib.sha256(body.encode("utf-8")).hexdigest()].append(ch["file"])

        dups = {h: fs for h, fs in hashes.items() if len(fs) > 1}
        print("\n== %s ==" % b["book"])
        print("  章节 %d ｜ 空章 %d ｜ 极短章(<300字) %d ｜ 疑似乱码 %d"
              % (b["chapters"], len(empty), len(tiny), len(mojibake)))
        print("  **完全重复的章节组: %d 组，涉及 %d 个文件**"
              % (len(dups), sum(len(v) for v in dups.values())))
        for h, fs in list(dups.items())[:5]:
            print("     重复: %s" % ", ".join(f[:5] for f in fs[:6]))
        if tiny:
            print("  极短章样例:", tiny[:3])
        if mojibake:
            print("  乱码样例:", mojibake[:3])
    return 0


if __name__ == "__main__":
    sys.exit(main())
