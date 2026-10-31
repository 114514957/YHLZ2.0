#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修复"同块内元亨三答重复同一段故事"的块（实测 6 块，含已手工修的对话-20）。

要求：三个回答**各自推进**，第一答讲起因/背景，第二答讲过程/转折，第三答讲结果，
**已说过的细节不许再讲一遍**；全部事实细节保留，只是分配到不同轮。元亨口吻不变。

用法：
    python tools/v9_fix_dupanswers.py --dry-run
    python tools/v9_fix_dupanswers.py
"""
from __future__ import annotations

import argparse
import difflib
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

SYS = (
    "你在修订「元亨」项目的中文对话素材。只输出 Markdown 对话块，不解释。\n"
    "【要修的病】一个块里有 2-3 个「元亨答」，它们**几乎逐字重复同一段故事**。\n"
    "这样训出来的模型会「回答任何问题都重复同一段」，彻底废掉。\n"
    "【怎么修】让每个回答**各自推进**，互不重复：\n"
    "  第 1 答 → 只讲起因与场景（发生什么、当时什么样）\n"
    "  第 2 答 → 只讲过程与转折（怎么做的、卡在哪、怎么变）\n"
    "  第 3 答 → 只讲结果与收尾（最后怎样、什么感受）\n"
    "【铁律】\n"
    "1. **所有事实细节必须保留**（时间、数字、动作、物件、对话），只是**分配到不同轮**，"
    "不许因为怕重复就把细节删掉。\n"
    "2. 前一轮说过的细节，后一轮**不许再复述**。要接着往下说。\n"
    "3. 元亨口吻不变：活泼、傲娇、爱损人；自称在 我/咱/本小姐/老娘 之间按情绪切换。\n"
    "4. **禁词**：我这边、我接、我认、稳了、很稳、别指望；不许出现「理论上来说」。\n"
    "5. 禁止括号动作、旁白、Markdown、列表行。\n"
    "6. 保留块头元数据行与轮次标题（`### 老爹问N` / `### 利贞问N` / `### 元亨答N`）不变。\n"
    "7. 块之间用一行 `=====` 分隔；每块以 `## ` 开头。\n"
)


def load_key() -> str:
    import scene_v8 as sv
    return sv.load_key()


def ds_call(key: str, user: str, max_tokens: int = 8000) -> str:
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": user}],
        "temperature": 0.9, "max_tokens": max_tokens, "stream": False,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"].get("content", "")


def dup_check(block: str) -> str:
    import v9_story_gate as G
    ts = G.parse_turns(block)
    ans = [t[3].strip() for t in ts if t[0] == "元亨" and t[1] == "答" and len(t[3]) > 40]
    for i in range(len(ans)):
        for j in range(i + 1, len(ans)):
            r = difflib.SequenceMatcher(None, ans[i], ans[j]).ratio()
            if r >= 0.70:
                return "第%d/%d答仍相似 %.2f" % (i + 1, j + 1, r)
    return ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import v9_story_gate as G
    p = os.path.join(MAT, "对话样本.md")
    text = io.open(p, encoding="utf-8", errors="replace").read()
    bad = []
    for blk in G.parse_blocks(text):
        ts = G.parse_turns(blk)
        ans = [t[3].strip() for t in ts if t[0] == "元亨" and t[1] == "答" and len(t[3]) > 40]
        hit = False
        for i in range(len(ans)):
            for j in range(i + 1, len(ans)):
                if difflib.SequenceMatcher(None, ans[i], ans[j]).ratio() >= 0.70:
                    hit = True
                    break
            if hit:
                break
        if hit:
            bad.append(blk.rstrip() + "\n")
    print("待修块: %d -> %s" % (len(bad), [b.split("\n", 1)[0][3:][:14] for b in bad]))

    key = load_key()
    outs, failed = [], []
    for i in range(0, len(bad), 2):
        chunk = bad[i:i + 2]
        user = ("请逐块改写下面 %d 个块（让多个回答各自推进、互不重复），"
                "输出同样数量，用 `=====` 分隔。\n\n" % len(chunk)
                + "\n===== 原始块 =====\n".join(chunk))
        try:
            resp = ds_call(key, user)
        except Exception as exc:  # noqa: BLE001
            print("  [%d] API 失败: %s" % (i, exc))
            continue
        got = [x.strip() for x in re.split(r"(?m)^=+$", resp) if x.strip()]
        for b in got:
            why = dup_check(b)
            if why:
                failed.append((b.split("\n", 1)[0][:24], why))
            else:
                outs.append(b)
        print("  [%d/%d] 返回 %d，通过 %d" % (i + len(chunk), len(bad), len(got),
                                            len(outs) - (len(outs) - len(got) - len(failed))))

    print("\n通过 %d，失败 %d" % (len(outs), len(failed)))
    for f in failed:
        print("   失败 %s: %s" % f)
    if a.dry_run:
        for b in outs[:1]:
            print("\n" + "=" * 74)
            print(b[:1200])
        return 0
    if outs:
        os.makedirs(OUT_DIR, exist_ok=True)
        path = os.path.join(OUT_DIR, "去重复_%s.md" % time.strftime("%Y%m%d_%H%M%S"))
        io.open(path, "w", encoding="utf-8").write("\n\n".join(outs) + "\n")
        print("已写 ->", os.path.relpath(path, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
