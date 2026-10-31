#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修素材块头，让 PT 的 `load_self_core()` 能读到。

2026-10-21 发现：PT `v9_pt_corpus.py` 的块头正则是
    BLOCK_RE = r"^##\\s+(?P<id>[^｜|]+?)\\s*[｜|]\\s*(?P<label>.+)$"
**要求 `## id｜标签` 带竖线分隔**。但库里多数素材写成 `## 性-p00001`（无分隔），
于是 PT 一个都读不到 —— self_core 只有 2,026，且几乎全是《对话样本.md》。

SFT 侧不受影响（`finetune_assemble._blocks()` 只按 `## ` 切分，不看头部格式）。

本脚本只给**属于"她自己"的文件**补竖线；`开源对话样本.md` 故意不修
（LCCC 是别人的对话，不该进 self_core）。

用法：
    python tools/v9_fix_block_names.py --dry-run
    python tools/v9_fix_block_names.py
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

# 文件 → 分隔线右侧的标签
TARGETS = {
    "个性样本.md": "个性",
    "教样本.md": "教",
    "哲学观点样本.md": "哲学",
    "比喻理解样本.md": "比喻",
    "情绪承接样本.md": "情绪承接",
    "优质样本.md": "优质",
}
OK_RE = re.compile(r"^##\s+[^｜|]+?\s*[｜|]\s*.+$")


def fix_line(line: str, label: str) -> str:
    body = line[2:].strip()
    if OK_RE.match(line.rstrip()):
        return line
    # 已是「## id 标签」用空格的，把首个空格换成分隔线
    m = re.match(r"^(\S+)\s+(.+)$", body)
    if m:
        return "## %s｜%s" % (m.group(1), m.group(2).strip())
    return "## %s｜%s" % (body, label)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    for fn, label in TARGETS.items():
        p = os.path.join(ROOT, "docs", "素材", fn)
        if not os.path.exists(p):
            print("  %-22s 不存在，跳过" % fn)
            continue
        text = io.open(p, encoding="utf-8").read()
        m = re.search(r"(?ms)^(.*?)(?=^## )", text)
        head = m.group(1) if m else ""
        raw = re.split(r"(?m)^##\s+", text)[1:]
        out, changed = [], 0
        for b in raw:
            lines = b.split("\n")
            old = "## " + lines[0].strip()
            new = fix_line(old, label)
            if new != old:
                changed += 1
            if a.dry_run and changed <= 2 and new != old:
                print("    %s  →  %s" % (old[:36], new[:44]))
            lines[0] = new[3:]
            blk = "## " + "\n".join(lines).rstrip() + "\n"
            # 门禁复检（改块头不该影响判定，但要确认）
            rr = G.check_block("x", blk, "general")
            if rr["status"] == "FAIL":
                out.append("## " + b.rstrip() + "\n")
            else:
                out.append(blk)
        print("  %-22s %4d 块｜改名 %4d%s"
              % (fn, len(out), changed, "" if not a.dry_run else "（dry-run）"))
        if a.dry_run or not changed:
            continue
        bak = p.replace(".md", "_改名块头前.md")
        shutil.copy2(p, bak)
        with io.open(p, "w", encoding="utf-8") as fh:
            fh.write(head)
            for blk in out:
                fh.write("\n" + blk.rstrip() + "\n\n")
        print("      已写回（备份 %s）" % os.path.basename(bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
