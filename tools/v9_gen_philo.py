#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从《苏菲的世界》产"元亨讲哲学"素材（落法 B/C，不抄译文）。

铁律（《原文引用与防失真规则 v1》）：
  · 概念名、哲学家的归属必须保真（「实体」「一元论」「史宾诺莎」不许换词）
  · **译文受保护** → 必须用元亨自己的话重述，不许照抄原句
  · 观点强度不许弱化（"必然"不许写成"大概"）
  · 元亨是讲的人，老爹/利贞是问的人

用法：
    python tools/v9_gen_philo.py --start 0 --count 6 --dry-run
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
MAT = os.path.join(ROOT, "docs", "素材")
OUT_DIR = os.path.join(MAT, "_草稿")
IDX = os.path.join(ROOT, "cache", "book_index.json")

SYS = (
    "你在为「元亨」项目写中文对话素材。只输出 Markdown 对话块，不解释。\n"
    "【输入】《苏菲的世界》的一段原文（哲学讲解，中译本）。\n"
    "【输出】一个 2-3 轮的对话块：**老爹或利贞提问，元亨讲解**。\n"
    "【铁律】\n"
    "1. **必须用自己的话重述**。中译文受版权保护，**不许照抄原句**；"
    "但**概念名与哲学家归属必须保真**（「实体」「一元论」「史宾诺莎」「笛卡尔」不许换词或改挂）。\n"
    "2. **观点强度不许弱化**：原文说「必然」就不许写成「可能」；说「唯一」就不许写成「之一」。\n"
    "3. 元亨是**讲解者**（作答方），老爹/利贞是提问方。轮次只用 "
    "`### 老爹问N` / `### 利贞问N` / `### 元亨答N`，问与答严格交替。\n"
    "4. **元亨口吻**：活泼、傲娇、爱损人、哲学感强；自称在 我/咱/本小姐/老娘 之间切换；"
    "短句为主，可留白（……）。\n"
    "5. **禁词**：我这边、我接、我认、稳了、很稳、别指望；不许出现「理论上来说」。\n"
    "6. **禁止**：括号动作、旁白、Markdown、列表行、助手腔、把小标题塞进对话。\n"
    "6b. **风格硬要求（实测不加就全是 WARN）**：\n"
    "   · 元亨至少要**称呼对方一次**（「老爹」「利贞」），不许通篇不叫人；\n"
    "   · 每块至少**一处留白**（用「……」）；\n"
    "   · **句长必须起伏**：短句（≤12 字）和长句（≥40 字）都要有，不许通篇中等长度；\n"
    "   · 破折号「——」每块**最多 2 个**。\n"
    "7. 块头格式（**source_book 必须写代号 PHILO-A，不许写真实书名**）：\n"
    "```\n## 哲-p<N>\n- category: 哲学\n- emotion: neutral\n- length_tier: medium\n"
    "- contract: FIDELITY_CLAUSE\n- source_book: PHILO-A\n- quote_type: B\n"
    "```\n"
    "9. **正文里也不许出现真实书名或原书角色名**（苏菲、艾伯特等），只讲哲学内容本身。\n"
    "8. 块之间用一行 `=====` 分隔。\n"
)


def load_key() -> str:
    import scene_v8 as sv
    return sv.load_key()


def ds_call(key: str, user: str, max_tokens: int = 5000) -> str:
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": user}],
        "temperature": 0.75, "max_tokens": max_tokens, "stream": False,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"].get("content", "")


def validate(block: str) -> str:
    import v9_story_gate as G
    r = G.check_block(block.split("\n", 1)[0][3:][:20], block, "general")
    if r["status"] == "FAIL":
        return "；".join(r["fails"])[:70]
    if not re.search(r"^###\s*元亨答\d+", block, re.M):
        return "没有元亨答"
    return ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--span", type=int, default=900)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    idx = json.load(io.open(IDX, encoding="utf-8"))
    book = next(b for b in idx["books"] if b["book"].startswith("苏菲"))
    chunks = []
    for ch in book["files"]:
        t = io.open(os.path.join(ROOT, ch["path"]), encoding="utf-8",
                    errors="replace").read()
        # 每个文件取中段、末段各一块，凑够素材量
        for frac in (0.35, 0.7):
            s = int(len(t) * frac)
            seg = t[s:s + a.span].strip()
            if len(seg) > 500:
                chunks.append((ch["file"][:5], seg))
    print("可用原文片段 %d 个" % len(chunks))
    sel = chunks[a.start:a.start + a.count]
    print("本次 %d 个（start=%d）" % (len(sel), a.start))

    key = load_key()
    outs, failed = [], []
    for i, (fid, seg) in enumerate(sel):
        user = ("原文片段（来自 %s）：\n\n%s\n\n"
                "请据此写一个对话块，编号用 P%d。" % (fid, seg, a.start + i + 1))
        try:
            resp = ds_call(key, user)
        except Exception as exc:  # noqa: BLE001
            print("  [%d] API 失败: %s" % (i, exc))
            continue
        blk = resp.strip()
        why = validate(blk)
        if why:
            failed.append((fid, why))
            print("  [%d] %s 未通过: %s" % (i, fid, why))
        else:
            outs.append(blk)
            print("  [%d] %s 通过" % (i, fid))

    print("\n通过 %d ｜失败 %d" % (len(outs), len(failed)))
    if a.dry_run:
        for b in outs[:2]:
            print("\n" + "=" * 74)
            print(b[:1000])
        return 0
    if outs:
        os.makedirs(OUT_DIR, exist_ok=True)
        p = os.path.join(OUT_DIR, "哲学生成_%s_%d-%d.md"
                         % (time.strftime("%Y%m%d_%H%M%S"), a.start, a.start + len(sel)))
        io.open(p, "w", encoding="utf-8").write("\n\n".join(outs) + "\n")
        print("已写 ->", os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
