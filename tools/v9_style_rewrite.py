#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按《角色研读样张 v1》六条风格规则重写元亨对白。

只改"怎么说"，不改"说什么"：事实、技术点、结论一条不动。
禁词与"理论上来话"仍按老规矩禁。

用法：
    python tools/v9_style_rewrite.py --start 0 --count 6 --dry-run
    python tools/v9_style_rewrite.py --start 0 --count 60
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

BANNED = ["我这边", "我接", "我认", "稳了", "很稳", "这个稳", "别指望"]
BAD_HEAD = re.compile(r"^###\s*(利贞答|利贞补充|老爹答|元亨问)", re.M)
GOOD_HEAD = re.compile(r"^###\s*(老爹问|利贞问|元亨答)(\d+)\s*$", re.M)

SYS = (
    "你在修订「元亨」项目的中文对话素材。只输出 Markdown 对话块，不解释。\n"
    "【任务】只改**元亨怎么说话**，不改她说了什么——事实、技术点、结论、数字**一个字不许动**。\n"
    "【六条风格铁律】\n"
    "1. **句长要起伏**：多数小句 8–25 字；一段里允许出现**一句** 45–90 字的长句（用逗号推进）。"
    "**不许每句都长、都匀。**\n"
    "2. **自称随场合换**：情绪上来用「本小姐」「老娘」，平常说「我」「咱」。同一块里**至少两种**。\n"
    "3. **有的句子用收束词起头**：好吧 / 好了 / 那是 / 其实 / 不过 / 诶 / 哎 / 嘿。\n"
    "4. **留白**：整块里**至少一处**用「……」把话断在半路，不说完。\n"
    "5. **开口可以先叫对方**：老爹 / 利贞。整块**至少一处**。\n"
    "6. **可以反问，但不许客服式**：禁止「需要我…吗」「要不要我…」「还有什么可以帮您」「为您」「帮您」。\n"
    "【硬禁】禁词：我这边、我接、我认、稳了、很稳、这个稳、别指望。"
    "元亨嘴里不许出现「理论上来说」。\n"
    "【禁止】括号动作、旁白、Markdown、助手腔、日文韩文俄文。\n"
    "【格式】块之间用一行 `=====` 分隔；每块以 `## ` 开头；"
    "轮次只用 `### 老爹问N` / `### 利贞问N` / `### 元亨答N`，问与答严格交替；"
    "元亨答永远是作答方。保留块头元数据行不变。\n"
)


def load_key() -> str:
    import scene_v8 as sv
    return sv.load_key()


def ds_call(key: str, user: str, max_tokens: int = 6000) -> str:
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": user}],
        "temperature": 0.85, "max_tokens": max_tokens, "stream": False,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"].get("content", "")


def split_blocks(text: str) -> list[str]:
    return [b.strip() for b in re.split(r"(?m)^=+$", text) if b.strip()]


def style_metrics(block: str) -> dict:
    """块级风格指标（与门禁同口径）。"""
    ans = re.findall(r"^###\s*元亨答\d+\s*$(.*?)(?=^###|\Z)", block, re.M | re.S)
    text = "\n".join(a.strip() for a in ans)
    clauses = [c for c in re.split(r"[，。！？；、…\n\s]+", text) if c.strip()]
    lens = [len(c) for c in clauses]
    if not lens:
        return {}
    sl = sorted(lens)
    med = sl[len(sl) // 2]
    p90 = sl[int(len(sl) * 0.9)]
    return {
        "clauses": len(lens),
        "med": med, "p90": p90,
        "ratio": round(p90 / med, 2) if med else 0,
        "short_ratio": round(sum(1 for x in lens if x <= 20) / len(lens), 2),
        "ellipsis": "…" in text,
        "call": bool(re.search(r"老爹|利贞", text)),
    }


def validate(block: str) -> str:
    if not block.startswith("## "):
        return "块头不是 ## "
    if BAD_HEAD.search(block):
        return "非法轮次标题"
    heads = GOOD_HEAD.findall(block)
    if len(heads) < 2:
        return "有效轮次不足 2"
    kinds = [h[0] for h in heads]
    if kinds[0] not in ("老爹问", "利贞问"):
        return "首轮不是提问"
    for i, k in enumerate(kinds):
        want = "问" if i % 2 == 0 else "答"
        if ("问" if k.endswith("问") else "答") != want:
            return "问/答未交替（第%d轮 %s）" % (i + 1, k)
    for w in BANNED:
        if w in block:
            return "禁词 %s" % w
    if re.search(r"^###\s*元亨答\d+\s*$(.*?)(?=^###|\Z)", block, re.M | re.S):
        for m in re.finditer(r"^###\s*元亨答\d+\s*$(.*?)(?=^###|\Z)", block, re.M | re.S):
            if "理论上来说" in m.group(1):
                return "元亨用了「理论上来说」"
    return ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--batch", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    txt = io.open(os.path.join(MAT, "对话样本.md"), encoding="utf-8",
                  errors="replace").read()
    _h, *parts = re.split(r"(?m)^##\s+", txt)
    allblocks = ["## " + b.rstrip() + "\n" for b in parts]
    sel = allblocks[a.start:a.start + a.count]
    print("总块数 %d｜本次 %d 块（start=%d）" % (len(allblocks), len(sel), a.start))

    key = load_key()
    outs, failed = [], []
    t0 = time.time()
    for i in range(0, len(sel), a.batch):
        chunk = sel[i:i + a.batch]
        user = ("请按六条风格规则改写下面 %d 个块，输出同样数量的块，用 `=====` 分隔。\n\n"
                "===== 原始块 =====\n" % len(chunk)) + "\n===== 原始块 =====\n".join(chunk)
        try:
            resp = ds_call(key, user)
        except Exception as exc:  # noqa: BLE001
            print("  [%d] API 失败: %s" % (i, exc))
            continue
        got = split_blocks(resp)
        ok = 0
        for b in got:
            why = validate(b)
            if why:
                failed.append((b.split("\n", 1)[0], why))
            else:
                outs.append(b)
                ok += 1
        print("  [%d/%d] 返回 %d，通过 %d" % (i + len(chunk), len(sel), len(got), ok))

    print("\n通过 %d 块，失败 %d" % (len(outs), len(failed)))
    for f in failed[:6]:
        print("   失败 %s: %s" % f)
    if outs:
        ms = [style_metrics(b) for b in outs]
        ms = [m for m in ms if m]
        if ms:
            print("\n风格指标（均值）：p90/中位=%.2f ｜ 短句占比=%.0f%% ｜ 留白=%.0f%% ｜ 称呼=%.0f%%"
                  % (sum(m["ratio"] for m in ms) / len(ms),
                     sum(m["short_ratio"] for m in ms) / len(ms) * 100,
                     sum(1 for m in ms if m["ellipsis"]) / len(ms) * 100,
                     sum(1 for m in ms if m["call"]) / len(ms) * 100))

    if a.dry_run:
        print("\n" + "=" * 74)
        for b in outs[:2]:
            print(b[:900])
            print("-" * 74)
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "风格重做_%s_%d-%d.md"
                     % (time.strftime("%Y%m%d_%H%M%S"), a.start, a.start + len(sel)))
    with io.open(p, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(outs) + "\n")
    print("\n已写 %d 块 -> %s（用时 %.0fs）"
          % (len(outs), os.path.relpath(p, ROOT), time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
