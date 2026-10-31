#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""L01 人物声音错配普查（只读，口径可复核）。

口径（每条都能人工回看验证）：
  E1 元亨讲术语：元亨单条发言里出现 ≥2 个技术词（schema/字段/索引/缓存/正则/重构/接口/参数…）
  E2 利贞端口癖：利贞单条发言里出现 咱/哎/嘿/呦/本小姐/好家伙
  E3 同人连发：相邻两轮同一发言人
  E4 元亨超长技术独白：元亨单条 >350 字且含 ≥2 个技术词
  E5 利贞反问链：利贞以问号收尾的发言 ≥3 条（人设=短句直给，不是追问方）
用法：python tools/v9_l01_voice_mix.py [文件]
"""
from __future__ import annotations

import io
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(PROJECT_ROOT, "docs", "素材", "_草稿", "L01_扩写30块_对话1至30_20261013.md")
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.M)
TECH = ["schema", "字段", "索引", "缓存", "正则", "重构", "接口", "参数", "快照", "回调",
        "函数", "变量", "日志", "堆", "内存", "事务", "主键", "测试用例", "部署", "进程"]
LIZHEN_HABITS = ["咱", "哎", "嘿", "呦", "本小姐", "好家伙"]


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    with io.open(path, "r", encoding="utf-8") as fh:
        text = fh.read().replace("\r\n", "\n")
    blocks = [b for b in re.split(r"(?m)(?=^## )", text) if b.startswith("## ")]
    rows, tot = [], {"E1": 0, "E2": 0, "E3": 0, "E4": 0, "E5": 0}
    for blk in blocks:
        head = blk.splitlines()[0][3:].strip()
        ms = list(TURN.finditer(blk))
        ts = []
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
            ts.append((m.group(1).strip(), m.group(2), blk[m.end():end].strip()))
        e = {"E1": 0, "E2": 0, "E3": 0, "E4": 0, "E5": 0}
        for i, (sp, ty, tx) in enumerate(ts):
            n_tech = sum(1 for w in TECH if w in tx)
            if sp == "元亨" and n_tech >= 2:
                e["E1"] += 1
            if sp == "元亨" and n_tech >= 2 and len(tx) > 350:
                e["E4"] += 1
            if sp == "利贞":
                if any(h in tx for h in LIZHEN_HABITS):
                    e["E2"] += 1
                if tx.rstrip().endswith(("？", "?")):
                    e["E5"] += 1
            if i and sp == ts[i - 1][0]:
                e["E3"] += 1
        if any(e.values()):
            rows.append((head, e))
            for k in tot:
                tot[k] += e[k]
    print("文件 %s，块数 %d" % (os.path.basename(path), len(blocks)))
    print("合计：E1元亨讲术语=%d  E2利贞端口癖=%d  E3同人连发=%d  E4元亨长技术独白=%d  E5利贞反问=%d"
          % (tot["E1"], tot["E2"], tot["E3"], tot["E4"], tot["E5"]))
    print("触发块 %d / %d" % (len(rows), len(blocks)))
    print()
    print("%-30s %4s %4s %4s %4s %4s" % ("块", "E1", "E2", "E3", "E4", "E5"))
    for head, e in rows:
        print("%-30s %4d %4d %4d %4d %4d" % (head[:30], e["E1"], e["E2"], e["E3"], e["E4"], e["E5"]))
    flagged = {h for h, _ in rows}
    clean = [b.splitlines()[0][3:].strip() for b in blocks
             if b.splitlines()[0][3:].strip() not in flagged]
    print()
    print("干净块 %d 个：%s" % (len(clean), "、".join(clean) if clean else "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
