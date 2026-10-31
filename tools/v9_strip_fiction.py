#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""剥离虚构外壳：把哲学素材里的"故事载体"去掉，只留观点本身。

老爹 2026-10-20 定：**小说里的故事完全虚构，很严重；只要对话能力和思想。**
所以：神话情节、书目比喻、"有个人…"这类虚构载体一律删掉，
      思想家说了什么（观点/论证/归属）必须保留。

用法：
    python tools/v9_strip_fiction.py --apply
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
sys.stdout.reconfigure(encoding="utf-8")

STORY = re.compile(
    r"有一个人|有个人|有个姑娘|有个房东|有个家伙|某个人|从前有|"
    r"索尔|奥丁|芙瑞雅|洛奇|诸神|雷神|巨人|锤子|瓦尔哈拉|北欧|"
    r"白兔|魔术师|兔毛|帽子|"
    r"据说|相传|传说|故事里|书里说|有个故事|后来他|后来她|结果他|结果她"
)

SYS = (
    "你在修订「元亨」项目的中文对话素材。只输出 Markdown 对话块，不解释。\n"
    "【要修的病】这些块用**虚构故事**（神话情节、小说比喻、「有个人……」）当载体讲道理。\n"
    "**虚构情节会污染元亨的真实性，必须剥掉。**\n"
    "【怎么修】\n"
    "· 把故事载体**整段删掉**：不许出现神话人物、神兽、「有个人/有个姑娘」、"
    "「据说/相传/故事里」这类转述标记。\n"
    "· **只留思想本身**：这是谁的观点、他主张什么、凭什么、错在哪、"
    "元亨自己站哪一边——这些必须保留且更清楚。\n"
    "· 元亨可以直接讲观点：「柏拉图认为……本小姐不买账，因为……」这样。\n"
    "· **不许换成另一个虚构故事**（别说「我认识一个人」）。要举例子就举**现实里的东西**："
    "上学、上班、考试、租房、买东西、看病、排队、亲戚。\n"
    "【铁律】\n"
    "· 概念名与哲学家归属必须保真；观点强度不许弱化。\n"
    "· 元亨是讲解者（作答方），老爹/利贞是提问方；问与答严格交替。\n"
    "· 元亨口吻：活泼、傲娇、哲学感强；自称 我/咱/本小姐/老娘 切换。\n"
    "· 至少称呼对方一次；至少一处留白「……」；句长要有起伏。\n"
    "· 禁词：我这边、我接、我认、稳了、很稳、别指望；不许说「理论上来说」。\n"
    "· 禁止括号动作、旁白、Markdown、列表行。\n"
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(ROOT, "docs", "素材", "哲学观点样本.md"))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    import v9_story_gate as G
    raw = io.open(a.file, encoding="utf-8", errors="replace").read()
    head, *parts = re.split(r"(?m)^##\s+", raw)
    bad = []
    for b in parts:
        blk = "## " + b.rstrip() + "\n"
        if STORY.search(blk):
            bad.append(blk)
    print("含虚构载体 %d 块: %s" % (len(bad), [x.split("\n", 1)[0][3:][:10] for x in bad]))

    key = load_key()
    out, failed = [], []
    for i in range(0, len(bad), 2):
        chunk = bad[i:i + 2]
        user = ("请逐块剥掉虚构故事、只留哲学观点，输出同样数量，用 `=====` 分隔。\n\n"
                + "\n===== 原始块 =====\n".join(chunk))
        try:
            resp = ds_call(key, user)
        except Exception as exc:  # noqa: BLE001
            print("  [%d] API 失败: %s" % (i, exc))
            continue
        got = [x.strip() for x in re.split(r"(?m)^=+$", resp) if x.strip()]
        for b in got:
            r = G.check_block("x", b, "general")
            if STORY.search(b):
                failed.append((b.split("\n", 1)[0][:20], "仍有虚构载体"))
            elif r["status"] == "FAIL":
                failed.append((b.split("\n", 1)[0][:20], "；".join(r["fails"])[:50]))
            else:
                out.append(b)
        print("  [%d/%d] 返回 %d｜累计通过 %d" % (i + len(chunk), len(bad), len(got), len(out)))

    print("\n通过 %d｜失败 %d" % (len(out), len(failed)))
    for f in failed[:5]:
        print("   失败 %s: %s" % f)
    if a.apply and out:
        # 按块名替换
        m = {}
        for b in out:
            m[b.split("\n", 1)[0][3:].strip()] = b
        nb = []
        used = 0
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
        print("已替换 %d 块 -> %s" % (used, os.path.relpath(a.file, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
