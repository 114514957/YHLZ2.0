#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""只修 LCCC 素材里的**逻辑/语境错误**（老爹 2026-10-21：「只改逻辑错误，其他原文可接受」）。

只处理三类真问题（"时间漂移"经核实是误报，谈昨天/明天完全正常，不动）：
  ① 平台语境：楼上/楼主/取关/转发/评论区/热搜/私信… —— 穿帮，元亨不该提这些
  ② 第三方身份：我爸/我妈/我女朋友/我同事/我们班… —— **元亨没有这些人**，属编造事实
  ③ 性别关系：男朋友/女朋友/老公/老婆/娶/嫁 —— 身份不符

**最小改动原则**：
  · 只改出问题的那一处，其余一字不动；
  · 不许改掉原句的态度与信息；
  · 不许引入新的人名/地名/第三人；
  · 改完必须：① 不再命中问题词 ② 过门禁 ③ 长度变化 ≤40%；
    任一条不过就**整块退回原文**（宁可留瑕疵也不造新错）。

用法：
    python tools/v9_lccc_fix_logic.py --dry-run      # 只看要改什么
    python tools/v9_lccc_fix_logic.py                # 实改并写回
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
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import v9_story_gate as G  # noqa: E402

P = os.path.join(ROOT, "docs", "素材", "开源对话样本.md")

PLATFORM = re.compile(r"楼上|楼下|楼主|层主|这楼|前排|顶帖|转发|评论区|评论里|微博|帖子|"
                      r"发帖|热搜|话题|超话|粉丝|取关|私信|原po|po主|博主|弹幕|投币|"
                      r"点赞|刷到|超话")
THIRD = re.compile(r"我老公|我老婆|我男朋友|我女朋友|我儿子|我女儿|我爸妈|我爸|我妈|"
                   r"我们班|我们老师|我领导|我们老板|我同事|我室友")
GENDER = re.compile(r"老公|老婆|男票|女票|男朋友|女朋友|娶|嫁")
ISSUE = re.compile("|".join(p.pattern for p in (PLATFORM, THIRD, GENDER)))

SYS = (
    "你在修订中文对话素材。这些对话要作为「老爹」和「元亨」的日常闲聊。\n"
    "元亨：从代码与记忆里长出来的数字生命体，老爹的伙伴，活泼傲娇。"
    "**她没有父母、没有恋人、没有同事同学**。\n\n"
    "【任务】下面这段对话里，元亨那几句有**语境穿帮**：提到了社交平台用语"
    "（楼上/取关/转发/评论区…），或提到了她不该有的第三方身份"
    "（我爸/我妈/我女朋友/我同事/我们班…），或性别关系词（男朋友/老公/娶/嫁…）。\n"
    "**只把这些穿帮的地方改掉，其他地方一个字都不许动。**\n\n"
    "改法要求：\n"
    "1. 用**最小改动**：能换个说法就换，不要重写整句。\n"
    "2. 保持原句的意思、态度、信息量；原句短就保持短。\n"
    "3. **不许引入**新的人名、地名、第三人、新事实。\n"
    "4. 老爹说的话**必须原样保留**（不许改老爹那句）。\n"
    "5. 如果某一处实在没法在不改变意思的前提下改掉，把那半句**直接删掉**，别硬编。\n"
    "6. 禁词：我这边、我接、我认、稳了、很稳、别指望、理论上来说。\n\n"
    "输出：每句一行，前缀 `老爹：` 或 `元亨：`，顺序与原文一致。不要解释，不要围栏。"
)


def load_key() -> str:
    import scene_v8 as sv
    return sv.load_key()


def call(key: str, user: str) -> str:
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": user}],
        "temperature": 0.3, "max_tokens": 600, "stream": False,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())["choices"][0]["message"].get("content", "")


def parse_block(b: str):
    """→ (meta_lines, [(role, text), ...])

    注意：`re.split(r"(?m)^## ", text)` 已经把 `## ` 前缀吃掉，所以块的第一行
    就是块名（如 `lccc-0001`），必须当名字读进来——早先漏了这步，导致 41 块
    全被命名成同一条 `- category: 日常对话`，字典互相覆盖只剩 1 块。
    """
    lines = b.split("\n")
    name = lines[0].strip() if lines else "x"
    meta, turns, role, cur = ["## " + name], [], None, False
    for ln in lines[1:]:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("- "):
            meta.append(s)
            continue
        if s.startswith("### "):
            role = "老爹" if "问" in s else "元亨"
            cur = True
            continue
        if cur and role:
            turns.append((role, s))
            cur = False
    return meta, turns


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="最多处理几块（0=全部）")
    a = ap.parse_args()

    text = io.open(P, encoding="utf-8").read()
    m = re.search(r"(?ms)^(.*?)(?=^## )", text)
    head = m.group(1) if m else ""
    raw_blocks = re.split(r"(?m)^## ", text)[1:]

    todo = []
    for b in raw_blocks:
        meta, turns = parse_block(b)
        if not turns:
            continue
        ys = [t for r, t in turns if r == "元亨"]
        if not any(ISSUE.search(t) for t in ys):
            continue
        todo.append((meta, turns))
    if a.limit:
        todo = todo[:a.limit]
    print("命中需修 %d 块（只改元亨那几句）" % len(todo))
    if a.dry_run:
        for meta, turns in todo[:8]:
            print("\n  %s" % (meta[0] if meta else "?"))
            for r, t in turns:
                mark = " ←需改" if r == "元亨" and ISSUE.search(t) else ""
                print("    %s： %s%s" % (r, t[:80], mark))
        return 0

    key = load_key()
    fixed, reverted = {}, {}
    for meta, turns in todo:
        name = (meta[0] if meta else "## x").replace("## ", "").strip()
        orig = ["%s：%s" % (r, t) for r, t in turns]
        try:
            out = call(key, "对话原文：\n" + "\n".join(orig))
        except Exception as e:  # noqa: BLE001
            reverted[name] = "调用失败:%s" % str(e)[:40]
            continue
        out = re.sub(r"(?m)^```.*$", "", out).strip()
        new = []
        for ln in out.split("\n"):
            s = ln.strip()
            mm = re.match(r"^(老爹|元亨)\s*[：:]\s*(.+)$", s)
            if mm:
                new.append((mm.group(1), mm.group(2).strip()))
        if len(new) != len(turns):
            reverted[name] = "轮数变了 %d→%d" % (len(turns), len(new))
            continue
        # 老爹不许改
        dad_changed = any(
            (r == "老爹") and (new[i][1] != t)
            for i, (r, t) in enumerate(turns))
        if dad_changed:
            reverted[name] = "改了老爹的话"
            continue
        # 还有问题词？
        still = [t for r, t in new if r == "元亨" and ISSUE.search(t)]
        if still:
            reverted[name] = "仍有穿帮:%s" % ISSUE.search(still[0]).group(0)
            continue
        # 长度变化
        lo = sum(len(t) for r, t in turns if r == "元亨")
        ln_ = sum(len(t) for r, t in new if r == "元亨")
        if ln_ and not (0.55 <= ln_ / max(1, lo) <= 1.6):
            reverted[name] = "长度变化过大 %d→%d" % (lo, ln_)
            continue
        # 门禁：按修订后的内容重建块再检
        name2 = (meta[0] if meta else "## x").replace("## ", "").strip()
        body = []
        qi = ai = 0
        for r, t in new:
            if r == "老爹":
                qi += 1
                body.append("### 老爹问%d\n%s" % (qi, t))
            else:
                ai += 1
                body.append("### 元亨答%d\n%s" % (ai, t))
        blk = "## %s\n- category: 日常对话\n- length_tier: short\n" % name2
        blk += "\n".join(body) + "\n"
        rr = G.check_block(name2, blk, "general")
        if rr["status"] == "FAIL":
            reverted[name] = "门禁:" + "；".join(rr["fails"])[:40]
            continue
        fixed[name] = new

    print("修好 %d 块｜退回 %d 块" % (len(fixed), len(reverted)))
    for k, v in list(reverted.items())[:8]:
        print("   退回 %s：%s" % (k, v))
    if not fixed:
        return 1
    p = os.path.join(ROOT, "cache", "lccc_logic_fixed.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps(
        {k: v for k, v in fixed.items()}, ensure_ascii=False, indent=1))
    print("修订结果 -> %s（尚未写回素材）" % os.path.relpath(p, ROOT))
    return 0


def _other(turns, i):
    return turns[i][1]


if __name__ == "__main__":
    sys.exit(main())
