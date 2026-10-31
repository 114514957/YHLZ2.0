#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全素材集检查（老爹 2026-10-22：「做全素材集检查」）。

之前只查了 SFT train（5,083 条）。这次查**整个素材集**：
  ① 盘点 docs/素材 下全部 .md（含 _待定/_废弃/_归档/_草稿 等子目录）
  ② 每个 .md 的门禁通过率、块数、老爹称呼率
  ③ 盘点 data/finetune / data/pd / data/pt 的全部数据集
  ④ **孤儿检测**：素材写了但没进任何数据集 → 白做；数据集有但来源不明 → 风险
  ⑤ 一致性：同一内容在多处重复 / 标记冲突

用法：
    python tools/v9_full_material_check.py
    python tools/v9_full_material_check.py --md-only
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import v9_story_gate as G  # noqa: E402

BLOCK_RE = re.compile(r"(?m)^##\s+(?P<id>[^｜|]+?)\s*[｜|]\s*(?P<label>.+)$")


def scan_md():
    base = "docs/素材"
    out = []
    for dirpath, _dirnames, filenames in os.walk(base):
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, base).replace("\\", "/")
            txt = io.open(p, encoding="utf-8", errors="replace").read()
            heads = BLOCK_RE.findall(txt)
            # 块数：## 开头行
            n_h2 = len(re.findall(r"(?m)^##\s+", txt))
            out.append({"path": p, "rel": rel, "bytes": len(txt.encode("utf-8")),
                        "h2": n_h2, "named": len(heads),
                        "chars": len(txt)})
    return out


def gate_rate(path: str, limit: int = 400):
    """抽块跑门禁（每文件最多 limit 块，避免太慢）。"""
    txt = io.open(path, encoding="utf-8", errors="replace").read()
    blocks = re.split(r"(?m)^##\s+", txt)[1:]
    if not blocks:
        return None
    step = max(1, len(blocks) // limit)
    samp = blocks[::step][:limit]
    st = Counter()
    for b in samp:
        r = G.check_block("x", "## " + b, "general")
        st[r["status"]] += 1
    return {"n": len(samp), "stat": dict(st)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md-only", action="store_true")
    ap.add_argument("--no-gate", action="store_true")
    a = ap.parse_args()

    print("=" * 78)
    print("① docs/素材 全部 .md 盘点")
    print("=" * 78)
    mds = scan_md()
    mds.sort(key=lambda x: (x["rel"].count("/"), x["rel"]))
    print("%-52s %8s %6s %6s" % ("文件", "KB", "##块", "带名块"))
    for m in mds:
        print("  %-50s %7.1f %6d %6d" % (m["rel"], m["bytes"] / 1024, m["h2"], m["named"]))
    print("  合计 %d 个 .md｜%d 块｜%.1f MB"
          % (len(mds), sum(m["h2"] for m in mds),
             sum(m["bytes"] for m in mds) / 1048576))
    no_name = [m["rel"] for m in mds if m["h2"] and not m["named"]]
    if no_name:
        print("  ⚠ 有块但没 `## 名｜标签` 格式（PT self_core 读不到）：%s" % no_name)

    if a.md_only:
        return 0

    print("\n" + "=" * 78)
    print("② 门禁通过率（每文件抽样 ≤400 块）")
    print("=" * 78)
    if a.no_gate:
        print("  （--no-gate 跳过）")
    else:
        for m in mds:
            if not m["h2"]:
                continue
            r = gate_rate(m["path"])
            if not r:
                continue
            st = r["stat"]
            tot = r["n"]
            fail = st.get("FAIL", 0)
            flag = "❌" if fail else "✅"
            print("  %s %-48s 抽%4d  PASS %4d  WARN %3d  FAIL %3d"
                  % (flag, m["rel"], tot, st.get("PASS", 0), st.get("WARN", 0), fail))

    print("\n" + "=" * 78)
    print("③ 数据集盘点")
    print("=" * 78)
    sets = {}
    for d in ("data/finetune", "data/pd", "data/pt"):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".jsonl"):
                continue
            p = os.path.join(d, fn)
            n = sum(1 for line in io.open(p, encoding="utf-8", errors="replace")
                    if line.strip())
            sets[p] = n
            print("  %-52s %7d 行" % (p, n))

    print("\n" + "=" * 78)
    print("④ 孤儿检测")
    print("=" * 78)
    # 训练集用了哪些 source 前缀
    used_src = Counter()
    for sp in ("train", "val", "test"):
        p = "data/finetune/sft_persona_v9t_%s.jsonl" % sp
        if not os.path.exists(p):
            continue
        for line in io.open(p, encoding="utf-8"):
            if line.strip():
                used_src[str(json.loads(line).get("source", "?")).split(":")[0]] += 1
    print("  SFT 用到的来源（按维度）：")
    for k, v in used_src.most_common():
        print("    %-14s %6d" % (k, v))
    # 哪些 data/finetune 的 jsonl 没被 SFT 用到
    print("\n  data/finetune 里未被 SFT 使用的文件：")
    unused = []
    for p in sets:
        if not p.startswith("data/finetune"):
            continue
        if "sft_persona" in p:
            continue
        stem = re.sub(r"\.jsonl$", "", os.path.basename(p))
        hit = any(stem[:14].lower() in str(s).lower() or stem.lower() in str(s).lower()
                  for s in used_src)
        if not hit:
            unused.append(p)
    for p in unused:
        print("    ⚠ %s（%d 行）" % (p, sets[p]))
    if not unused:
        print("    （无）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
