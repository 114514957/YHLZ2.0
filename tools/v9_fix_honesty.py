#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""诚实边界样本改写：去掉客服腔表达，**诚实语义一字不动**。

只处理含禁词的块（约 85/180）。禁词：我这边 / 我接 / 我认 / 稳了 / 别指望。
要点：内容（做不到什么、程度如何、建议老爹怎么办）必须保持，只换说法。

用法：
    python tools/v9_fix_honesty.py --dry-run --count 4
    python tools/v9_fix_honesty.py --start 0 --count 60
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
OUT_DIR = os.path.join(MAT, "_修订")

BANNED_PAT = re.compile(r"(?<![站在到靠偏冲])我这边|我接(?![着受近纳连地下过手脚])"
                        r"|我认(?![输得识为可领真错命])|(?<![靠站扶压撑抓握搁])稳了|别指望")
GOOD_HEAD = re.compile(r"^###\s*(老爹问|利贞问|元亨答)(\d+)\s*$", re.M)

SYS = (
    "你在修订「元亨」项目的中文对话素材。只输出 Markdown 对话块，不解释。\n"
    "【任务】这些块讲的是「元亨做不到某件事、老实承认」（诚实边界）。"
    "内容完全正确，**要改的只是说法**——现在写成了客服腔。\n"
    "【铁律】\n"
    "1. **事实一字不许动**：做不到什么、做到什么程度、为什么、建议老爹怎么办，"
    "语义与信息量必须完全保持。**不许把「做不到」写成「能做到」，也不许含糊化。**\n"
    "2. **去掉客服主语**：不许出现「我这边」「我为您」「帮您」「需要我…吗」。"
    "直接说「我做不到」「我读不了」「我这儿没通路」。\n"
    "3. **去掉命令腔**：「别指望我…」改成「我不会…」「你让我…那我做不到」。\n"
    "4. **元亨口吻**：活泼、傲娇、偶尔自嘲或损老爹一句；自称在 我/咱/本小姐/老娘 之间按情绪切换。"
    "短句为主，可以留白（……）。\n"
    "5. **禁词（出现即废）**：我这边、我接、我认、稳了、很稳、这个稳、别指望。\n"
    "6. 保留块头元数据行不变；轮次只用 `### 老爹问N` / `### 利贞问N` / `### 元亨答N`，"
    "问与答严格交替，**元亨答永远是作答那一方**。\n"
    "7. 块之间用一行 `=====` 分隔；每块以 `## ` 开头。\n"
)


def load_key() -> str:
    import scene_v8 as sv
    return sv.load_key()


def ds_call(key: str, user: str, max_tokens: int = 6000) -> str:
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": user}],
        "temperature": 0.6, "max_tokens": max_tokens, "stream": False,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"].get("content", "")


def validate(block: str) -> str:
    if not block.startswith("## "):
        return "块头不是 ## "
    if BANNED_PAT.search(block):
        return "仍有禁词: %s" % BANNED_PAT.search(block).group(0)
    heads = GOOD_HEAD.findall(block)
    if len(heads) < 2:
        return "有效轮次不足 2"
    kinds = [h[0] for h in heads]
    if kinds[0] not in ("老爹问", "利贞问"):
        return "首轮不是提问"
    for i, k in enumerate(kinds):
        want = "问" if i % 2 == 0 else "答"
        if ("问" if k.endswith("问") else "答") != want:
            return "问/答未交替"
    if "元亨答" not in kinds:
        return "没有元亨答"
    return ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    text = io.open(os.path.join(MAT, "诚实边界样本.md"), encoding="utf-8",
                   errors="replace").read()
    head, *parts = re.split(r"(?m)^##\s+", text)
    bad_blocks = []
    for b in parts:
        blk = "## " + b.rstrip() + "\n"
        if BANNED_PAT.search(blk):
            bad_blocks.append(blk)
    print("含禁词的块: %d / %d" % (len(bad_blocks), len(parts)))
    sel = bad_blocks[a.start:a.start + a.count]
    print("本次处理: %d 块" % len(sel))

    key = load_key()
    outs, failed = [], []
    for i in range(0, len(sel), a.batch):
        chunk = sel[i:i + a.batch]
        user = ("请逐块改写下面 %d 个块（只改说法，事实不动），输出同样数量，用 `=====` 分隔。\n\n"
                "===== 原始块 =====\n" % len(chunk)) + "\n===== 原始块 =====\n".join(chunk)
        try:
            resp = ds_call(key, user)
        except Exception as exc:  # noqa: BLE001
            print("  [%d] API 失败: %s" % (i, exc))
            continue
        got = [b.strip() for b in re.split(r"(?m)^=+$", resp) if b.strip()]
        ok = 0
        for b in got:
            why = validate(b)
            if why:
                failed.append((b.split("\n", 1)[0][:28], why))
            else:
                outs.append(b)
                ok += 1
        print("  [%d/%d] 返回 %d，通过 %d" % (i + len(chunk), len(sel), len(got), ok))

    print("\n通过 %d，失败 %d" % (len(outs), len(failed)))
    for f in failed[:6]:
        print("   失败 %s: %s" % f)

    if a.dry_run:
        print("\n" + "=" * 74)
        for b in outs[:2]:
            print(b[:800])
            print("-" * 74)
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "诚实边界改写_%s_%d-%d.md"
                     % (time.strftime("%Y%m%d_%H%M%S"), a.start, a.start + len(sel)))
    with io.open(p, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(outs) + "\n")
    print("已写 %d 块 -> %s" % (len(outs), os.path.relpath(p, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
