# -*- coding: utf-8 -*-
"""列出「实际参与渲染」的块及其 token，找出可压缩的对象。"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

from transformers import AutoTokenizer  # noqa: E402

from backend import target_prompts as TP  # noqa: E402


def main() -> None:
    tok = AutoTokenizer.from_pretrained(os.path.join(ROOT, "models", "gemma4-hf",
                                                     "gemma-4-e4b-it"))
    def n(s: str) -> int:
        return len(tok(str(s or ""), add_special_tokens=False)["input_ids"])

    sysp = TP.render_system_prompt(public=False)
    flat = sysp.replace("\n", " ")
    print("私聊系统提示：%d 字 / %d token\n" % (len(sysp), n(sysp)))
    rows = []
    for name in dir(TP):
        if not name.isupper() or name.startswith("_"):
            continue
        v = getattr(TP, name)
        if not isinstance(v, str) or len(v) < 100:
            continue
        probe = v.strip().replace("\n", " ")[:36]
        if probe and probe in flat:
            rows.append((n(v), len(v), name))
    rows.sort(reverse=True)
    total = sum(r[0] for r in rows)
    print("参与渲染 %d 块，合计 %d token（占系统提示 %.0f%%）\n"
          % (len(rows), total, 100.0 * total / max(1, n(sysp))))
    for t, c, name in rows:
        print("  %5d token｜%4d 字｜%s" % (t, c, name))
    print("\n前 5 块合计 %d token（%.0f%%）"
          % (sum(r[0] for r in rows[:5]), 100.0 * sum(r[0] for r in rows[:5]) / total))


if __name__ == "__main__":
    main()
