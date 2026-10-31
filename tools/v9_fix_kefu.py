#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""清客服腔：只改说法不改内容。用于 对话样本/记忆样本/承认不确定/安全拒绝。

老爹 2026-10-20 定：**客服腔全去**；报告腔留着（已降 WARN）。
目标词：我这边 / 我接 / 我认 / 稳了 / 别指望 / 为您 / 建议您 / 请问 / 我可以帮…

用法：
    python tools/v9_fix_kefu.py --file 对话样本.md --count 40
    python tools/v9_fix_kefu.py --file 记忆样本_v2.md --count 20
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

BAD = re.compile(
    r"(?<![站在到靠偏冲])我这边"
    r"|我接(?![着受近纳连地下过手脚不管])"
    r"|我认(?![输得识为可领真错命认不])"
    r"|(?<![靠站扶压撑握搁])稳了"
    r"|别指望|很稳"
    r"|为您|建议您|请问|祝您|我可以帮|还有什么(?:需要|可以)|还需要什么"
)
GOOD_HEAD = re.compile(r"^###\s*(老爹问|利贞问|元亨答)(\d+)\s*$", re.M)
BARE_HEAD = re.compile(r"^###\s*(老爹|利贞|元亨)\s*$", re.M)

SYS = (
    "你在修订「元亨」项目的中文对话素材。只输出 Markdown 对话块，不解释。\n"
    "【任务】把这些块里的**客服腔**去掉。内容、事实、结论、情绪一律不动，只换说法。\n"
    "【必须干掉的】\n"
    "1. 「我这边」——客服式自指。改成「我」或直接省主语："
    "「我这边没这条数据」→「我没这条数据」。\n"
    "2. 「别指望…」——命令腔。改成「不会…」「别想着…」。\n"
    "3. 「稳了」「很稳」——网络口头禅。改成「妥了」「稳当」「靠谱」。\n"
    "4. 「我认」「我接」——客服式承接。按语境改成「认了」「接受」「接手」「认输」。\n"
    "5. 「为您／建议您／请问／我可以帮／还有什么需要」——敬语客服话术，全部去掉，直说。\n"
    "【不许动的】\n"
    "- 技术内容、数字、结论、谁对谁错，全部保持。\n"
    "- **报告腔可以留**（已完成／任务完成／处理完成 是工作汇报，老爹允许）。\n"
    "- 元亨口吻不变：活泼、傲娇、爱损人；自称在 我／咱／本小姐／老娘 之间切换。\n"
    "- 禁止括号动作、旁白、Markdown、列表行、助手腔。\n"
    "【格式】保留块头元数据行；块之间用一行 `=====` 分隔；每块以 `## ` 开头；"
    "轮次标题原样保留（### 老爹问N 或 ### 老爹 这类格式不要改）。\n"
)


def load_key() -> str:
    import scene_v8 as sv
    return sv.load_key()


def ds_call(key: str, user: str, max_tokens: int = 7000) -> str:
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": user}],
        "temperature": 0.5, "max_tokens": max_tokens, "stream": False,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"].get("content", "")


def validate(block: str, bare: bool) -> str:
    if not block.startswith("## "):
        return "块头不是 ## "
    m = BAD.search(block)
    if m:
        return "仍有: %s" % m.group(0)
    if bare:
        if not BARE_HEAD.search(block):
            return "轮次标题丢了"
    else:
        heads = GOOD_HEAD.findall(block)
        if len(heads) < 2:
            return "有效轮次不足 2"
    return ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--batch", type=int, default=3)
    a = ap.parse_args()

    p = os.path.join(MAT, a.file)
    text = io.open(p, encoding="utf-8", errors="replace").read()
    head, *parts = re.split(r"(?m)^##\s+", text)
    bad_blocks, bare = [], False
    for b in parts:
        blk = "## " + b.rstrip() + "\n"
        if str(G_meta(blk).get("negative", "")).lower() == "true":
            continue
        if BAD.search(blk):
            bad_blocks.append(blk)
            if BARE_HEAD.search(blk) and not GOOD_HEAD.search(blk):
                bare = True
    print("%s ｜含客服腔块 %d / 总 %d" % (a.file, len(bad_blocks), len(parts)))
    sel = bad_blocks[a.start:a.start + a.count]
    key = load_key()
    outs, failed = [], []
    t0 = time.time()
    for i in range(0, len(sel), a.batch):
        chunk = sel[i:i + a.batch]
        user = ("请逐块去掉客服腔，输出同样数量，用 `=====` 分隔。\n\n"
                "===== 原始块 =====\n" % ()) + "\n===== 原始块 =====\n".join(chunk)
        try:
            resp = ds_call(key, user)
        except Exception as exc:  # noqa: BLE001
            print("  [%d] API 失败: %s" % (i, exc))
            continue
        got = [x.strip() for x in re.split(r"(?m)^=+$", resp) if x.strip()]
        ok = 0
        for b in got:
            why = validate(b, bare)
            if why:
                failed.append((b.split("\n", 1)[0][:26], why))
            else:
                outs.append(b)
                ok += 1
        print("  [%d/%d] 返回 %d 通过 %d" % (i + len(chunk), len(sel), len(got), ok))
    print("\n通过 %d 失败 %d（%.0fs）" % (len(outs), len(failed), time.time() - t0))
    for f in failed[:6]:
        print("   失败 %s: %s" % f)
    if outs:
        os.makedirs(OUT_DIR, exist_ok=True)
        tag = os.path.splitext(a.file)[0]
        path = os.path.join(OUT_DIR, "客服腔_%s_%d-%d_%s.md"
                            % (tag, a.start, a.start + len(sel), time.strftime("%H%M%S")))
        io.open(path, "w", encoding="utf-8").write("\n\n".join(outs) + "\n")
        print("已写 ->", os.path.relpath(path, ROOT))
    return 0


def G_meta(blk: str) -> dict:
    import v9_story_gate as G
    return G.parse_meta(blk)


if __name__ == "__main__":
    sys.exit(main())
