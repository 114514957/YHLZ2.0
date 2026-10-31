#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把"元亨提问、利贞主讲"的技术块改写为"元亨主讲"（保留技术内容，换声音）。

背景（台账 0839）：对话样本.md 技术块 596 个，其中 593 个是利贞主讲、元亨提问，
违反"元亨是主体"硬要求。机械对调会造出"元亨说利贞腔"（L01 失败模式），
因此用 DeepSeek 逐批改写：保留技术知识点，把主答换给元亨，用元亨的口吻。

用法：
    python tools/v9_fix_tech_asker.py --start 0 --count 6 --dry-run
    python tools/v9_fix_tech_asker.py --start 0 --count 60
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
STATE = os.path.join(ROOT, "cache", "v9_fix_tech_state.json")

BANNED = ["我这边", "我接", "我认", "稳了", "很稳", "这个稳", "别指望"]
BAD_HEAD = re.compile(r"^###\s*(利贞答|利贞补充|老爹答|元亨问)", re.M)
GOOD_HEAD = re.compile(r"^###\s*(老爹问|利贞问|元亨答)(\d+)\s*$", re.M)

SYS = (
    "你是在修订「元亨」项目的中文对话训练素材。只输出 Markdown 对话块，不解释。\n"
    "【本次任务】原块里元亨在提问、利贞在主讲技术。要改写成：**元亨主讲**"
    "（元亨当答者，且是篇幅最长的主答），提问者改为老爹或利贞。\n"
    "【硬性要求】\n"
    "1. 技术知识点、结论、例子**必须保留**，不许删减或改错；改写的是说话人和口吻。\n"
    "2. 元亨口吻：活泼、傲娇、爱损人、哲学感强；可用「咱」「本小姐」「老娘」「元亨我」自称；"
    "会接梗、会反问式吐槽，但**最后一条答话不许以问号结尾**。\n"
    "3. 利贞（元亨的姐妹）：稳重直接；她只能**提问**，不许发言作答、不许抢主讲。\n"
    "4. 老爹：懒散、爱开玩笑、句子完整；他也只提问或接话，不讲课。\n"
    "5. **轮次格式铁律（违反即废）**：块内只能出现下面两种标题，且问/答严格交替：\n"
    "     ### 老爹问N   或   ### 利贞问N     （提问方，二者任选，可混用）\n"
    "     ### 元亨答N                        （作答方，**永远是元亨**）\n"
    "   编号 N 从 1 起逐轮递增；**绝不允许**出现 `### 利贞答N`、`### 利贞补充N`、"
    "`### 老爹答N`、`### 元亨问N` 这四种写法。\n"
    "6. **禁词（任何角色出现即废）**：我这边、我接、我认、稳了、很稳、这个稳、别指望。\n"
    "7. **元亨嘴里绝对不许出现「理论上来说」**（那是利贞的口头禅）。\n"
    "8. **禁止**：括号动作、旁白、Markdown 语法、助手腔（为您/以下是/列表/作为一个AI）、"
    "日文韩文俄文、哲学词汇乱入技术块。\n"
    "9. 保留原块头部的元数据行（- fiction/- category/- subtype/- status/- emotion/"
    "- length_tier/- contract）内容不变。\n"
    "10. 块之间用一行 `=====` 分隔；每块以 `## ` 开头；每轮必须承接上一轮。\n"
)


def load_key() -> str:
    import scene_v8 as sv
    return sv.load_key()


def ds_call(key: str, user: str, max_tokens: int = 6000) -> str:
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": user}],
        "temperature": 0.7, "max_tokens": max_tokens, "stream": False,
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


def validate(block: str) -> str:
    """返回空串表示通过，否则返回问题描述。"""
    if not block.startswith("## "):
        return "块头不是 ## "
    if BAD_HEAD.search(block):
        return "出现非法轮次标题（利贞答/利贞补充/老爹答/元亨问）"
    heads = GOOD_HEAD.findall(block)
    if len(heads) < 2:
        return "有效轮次不足 2"
    # 问/答必须交替
    kinds = [h[0] for h in heads]
    if kinds[0] != "老爹问" and kinds[0] != "利贞问":
        return "首轮不是提问"
    for i, k in enumerate(kinds):
        want = "问" if i % 2 == 0 else "答"
        if ("问" if k.endswith("问") else "答") != want:
            return "问/答未交替（第%d轮 %s）" % (i + 1, k)
    for w in BANNED:
        if w in block:
            return "禁词 %s" % w
    # 元亨答里不许「理论上来说」
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

    txt = io.open(os.path.join(MAT, "对话样本.md"), encoding="utf-8", errors="replace").read()
    _head, *parts = re.split(r"(?m)^##\s+", txt)
    targets = []
    for b in parts:
        block = "## " + b.rstrip() + "\n"
        turns = re.findall(r"^###\s*(元亨|利贞|老爹)\s*(问|答)", block, re.M)
        if turns and turns[0] == ("元亨", "问"):
            targets.append(block)
    print("待改块总数: %d" % len(targets))

    sel = targets[a.start:a.start + a.count]
    if not sel:
        print("没有可改的块")
        return 0
    print("本次处理: %d 块（start=%d）" % (len(sel), a.start))

    key = load_key()
    outs, failed = [], []
    t0 = time.time()
    for i in range(0, len(sel), a.batch):
        chunk = sel[i:i + a.batch]
        user = ("请逐块改写下面 %d 个块，输出同样数量的块，用 `=====` 分隔。\n\n"
                "===== 原始块 =====\n" % len(chunk)) + "\n===== 原始块 =====\n".join(chunk)
        try:
            resp = ds_call(key, user)
        except Exception as exc:  # noqa: BLE001
            print("  [%d] API 失败: %s" % (i, exc))
            failed.extend(chunk)
            continue
        got = split_blocks(resp)
        ok = 0
        for b in got:
            why = validate(b)
            if why:
                failed.append(b[:80] + "… (%s)" % why)
            else:
                outs.append(b)
                ok += 1
        print("  [%d/%d] 返回 %d 块，通过 %d" % (i + len(chunk), len(sel), len(got), ok))

    print("\n合计通过 %d 块，失败 %d" % (len(outs), len(failed)))
    for f in failed[:5]:
        print("   失败: %s" % f)

    if a.dry_run:
        print("\n" + "=" * 76)
        for b in outs[:3]:
            print(b[:800])
            print("-" * 76)
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    p = os.path.join(OUT_DIR, "技术块改写_%s_%d-%d.md" % (stamp, a.start, a.start + len(sel)))
    with io.open(p, "w", encoding="utf-8") as fh:
        fh.write("# 技术块改写（元亨主讲）%d–%d\n\n" % (a.start, a.start + len(sel)))
        fh.write("\n\n".join(outs) + "\n")
    with io.open(STATE, "w", encoding="utf-8") as fh:
        json.dump({"done": a.start + len(sel), "total": len(targets)}, fh)
    print("\n已写 %d 块 -> %s（用时 %.0fs）"
          % (len(outs), os.path.relpath(p, ROOT), time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
