# -*- coding: utf-8 -*-
"""建/更新记忆语义索引 → `cache/memvec.db`。

用法：
  python tools/memory_index_build.py            # 增量（内容没变就复用）
  python tools/memory_index_build.py --force    # 全量重算
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.memory_recall_semantic import SemanticIndex, default_paths  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略内容哈希，全量重算")
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    db, out = default_paths(ROOT)
    db = a.db or db
    out = a.out or out
    idx = SemanticIndex(out)
    stat = idx.build(db, force=a.force)
    print("记忆语义索引：%s" % json.dumps(stat, ensure_ascii=False))
    print("  池 %d 条 → 入库 %d 条（复用 %d、重算 %d）｜%.1f 秒"
          % (stat["pool"], stat["indexed"], stat["reused"], stat["rebuilt"],
             stat["seconds"]))
    print("  文件：%s" % os.path.relpath(str(out), ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
