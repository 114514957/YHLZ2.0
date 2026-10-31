#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修"跨答分句重复"：同一句话同时出现在元亨两个回答里。

这是"三答重复同一段故事"的轻症版本——整体相似度不到 0.70 没被判 FAIL，
但单句照搬会让模型学到"换个问题也把那句话再说一遍"。

修法：让后一答**接着说**，不许复述前一答说过的句子；事实不许丢。

用法：
    python tools/v9_fix_dupclause.py --file docs/素材/对话样本.md --apply
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.M)

SYS = (
    "你在修订「元亨」项目的中文对话素材。只输出 Markdown 对话块，不解释。\n"
    "【要修的病】同一个块里，元亨的两个回答出现了**完全相同的句子**。\n"
    "模型学去会变成「换个问题也把那句话再说一遍」。\n"
    "【怎么修】\n"
    "· 后一个回答必须**接着说**：回答这一轮新问的东西，不许复述前面说过的句子。\n"
    "· **事实、细节、数字、结论一个都不许丢**——可以换角度重述，但不许删掉信息。\n"
    "· 元亨口吻不变：活泼、傲娇、爱损人；自称 我/咱/本小姐/老娘 切换。\n"
    "· 至少称呼对方一次；至少一处留白「……」；句长要有起伏。\n"
    "· 禁词：我这边、我接、我认、稳了、很稳、别指望；不许说「理论上来说」。\n"
    "· 禁止括号动作、旁白、Markdown、列表行；不许出现真实书名或原书角色名。\n"
    "· 保留块头元数据与轮次标题；块之间用一行 `=====` 分隔。\n"
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


def has_dup_clause(blk: str) -> bool:
    heads = list(TURN.finditer(blk))
    where: dict[str, set] = {}
    for i, m in enumerate(heads):
        s = m.end()
        e = heads[i + 1].start() if i + 1 < len(heads) else len(blk)
        for cl in re.split(r"[，。！？；：、,.;:!?…—]+", blk[s:e]):
            cl = cl.strip()
            if len(cl) >= 8:
                where.setdefault(cl, set()).add(i)
    return any(len(v) >= 2 for v in where.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(ROOT, "docs", "素材", "对话样本.md"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    import v9_story_gate as G
    raw = io.open(a.file, encoding="utf-8", errors="replace").read()
    head, *parts = re.split(r"(?m)^##\s+", raw)
    bad = []
    for b in parts:
        blk = "## " + b.rstrip() + "\n"
        if has_dup_clause(blk):
            bad.append(blk)
    print("跨答分句重复 %d 块" % len(bad))
    if a.limit:
        bad = bad[:a.limit]

    key = load_key()
    out, failed = [], []
    for i in range(0, len(bad), 2):
        chunk = bad[i:i + 2]
        user = ("请逐块改写，让后一答接着说、不复述前面说过的句子，"
                "输出同样数量，用 `=====` 分隔。\n\n"
                + "\n===== 原始块 =====\n".join(chunk))
        try:
            resp = ds_call(key, user)
        except Exception as exc:  # noqa: BLE001
            print("  [%d] API 失败: %s" % (i, exc))
            continue
        got = [x.strip() for x in re.split(r"(?m)^=+$", resp) if x.strip()]
        for b in got:
            if has_dup_clause(b):
                failed.append((b.split("\n", 1)[0][:20], "仍有重复分句"))
            elif G.check_block("x", b, "general")["status"] == "FAIL":
                failed.append((b.split("\n", 1)[0][:20], "门禁 FAIL"))
            else:
                out.append(b)
        print("  [%d/%d] 返回 %d｜累计通过 %d" % (i + len(chunk), len(bad), len(got), len(out)))

    print("\n通过 %d｜失败 %d" % (len(out), len(failed)))
    for f in failed[:5]:
        print("   失败 %s: %s" % f)
    if a.apply and out:
        m = {b.split("\n", 1)[0][3:].strip(): b for b in out}
        nb, used = [], 0
        for b in parts:
            blk = "## " + b.rstrip() + "\n"
            k = blk.split("\n", 1)[0][3:].strip()
            if k in m:
                nb.append(m[k])
                used += 1
            else:
                nb.append(blk)
        with io.open(a.file, "w", encoding="utf-8") as fh:
            fh.write(head.rstrip() + "\n")
            for x in nb:
                fh.write("\n" + x.rstrip() + "\n\n")
        print("已替换 %d 块" % used)
    return 0


if __name__ == "__main__":
    sys.exit(main())
