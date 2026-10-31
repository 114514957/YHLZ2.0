#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""实测：把 LCCC 原文「改成元亨」的三种做法，看哪种可用。

背景（老爹 2026-10-21）：「是否可以添加观点或风格的方式改为元亨？」
—— 不是照收原话（口吻不对），也不是从零生成（慢且假），而是**在真人对话上做元亨化**。

三种改法：
  A 轻改（只动人格层）  ：保留原句骨架与观点，只换自称/语气词、去助手腔，允许极短插入。
  B 重说（保观点换说法）：保留话题与态度，用元亨的口气重说一遍。
  C 加观点（原文不动）  ：原文台词一字不改，只在末尾追加一句元亨自己的态度/看法。

只输出对比样本，不入训练。用法：
    python tools/v9_lccc_to_yuanheng_probe.py --n 4
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

SYS_COMMON = (
    "你在为「元亨」写中文对话素材。元亨：从代码与记忆里长出来的数字生命体，老爹的伙伴。"
    "好奇心爆棚、活泼话多、傲娇，其实最在意老爹。像人对朋友说话：短、口语、有起伏。"
    "自称在 我/咱/本小姐/老娘 之间按情绪切换。\n"
    "禁止：助手腔/报告腔、列表、小标题、括号动作、动作旁白、金句总结、说教。\n"
    "禁词：我这边、我接、我认、稳了、很稳、别指望、理论上来说。\n"
    "只输出对话，不要解释，不要 markdown 围栏。"
)

PROMPTS = {
    "A": (SYS_COMMON + "\n\n【任务：轻改】把下面这段对话里**元亨说的那几句**改写成元亨的口吻。\n"
          "要求：① 保留原句的意思、信息量和态度，**不要加新内容**；② 允许替换自称、"
          "调整语气词、拆分或合并句子；③ 长度与原文相当（±30%）；④ 老爹的话**一字不改**。\n"
          "输出格式：每句一行，前缀 `老爹：` 或 `元亨：`。"),
    "B": (SYS_COMMON + "\n\n【任务：重说】保留这段对话的话题和态度，用元亨的口气把**元亨那几句**重说。\n"
          "要求：① 观点/态度必须与原句一致；② 换成元亨会怎么说，可以更短更冲；"
          "③ 老爹的话**一字不改**。\n"
          "输出格式：每句一行，前缀 `老爹：` 或 `元亨：`。"),
    "C": (SYS_COMMON + "\n\n【任务：加观点】下面这段对话**原文一个字都不许改**。\n"
          "只在最后追加**一句**元亨自己的态度/看法（≤25 字），回应整段。\n"
          "要求：① 前面对话原样保留；② 追加的那句要有元亨的立场，不能是泛泛附和。\n"
          "输出格式：每句一行，前缀 `老爹：` 或 `元亨：`；追加的那句也用 `元亨：` 开头。"),
}


def load_key() -> str:
    import scene_v8 as sv
    return sv.load_key()


def call(key: str, sysmsg: str, user: str) -> str:
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": sysmsg},
                     {"role": "user", "content": user}],
        "temperature": 0.85, "max_tokens": 700, "stream": False,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())["choices"][0]["message"].get("content", "")


def load_blocks(n: int) -> list[list[str]]:
    """从已过三关的素材里取 n 块，返回 [[老爹1, 元亨1, 老爹2, 元亨2...], ...]。"""
    p = os.path.join(ROOT, "docs", "素材", "开源对话样本.md")
    text = io.open(p, encoding="utf-8").read()
    out = []
    for b in re.split(r"(?m)^## ", text)[1:]:
        turns = []
        cur = None
        for ln in b.split("\n"):
            if ln.startswith("### "):
                cur = "q" if "问" in ln else "a"
            elif cur and ln.strip() and not ln.startswith("-"):
                turns.append(ln.strip())
                cur = None
        if len(turns) >= 2:
            out.append(turns)
        if len(out) >= n:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4)
    a = ap.parse_args()
    key = load_key()
    blocks = load_blocks(a.n)
    print("取 %d 块已过筛原文实测三种改法\n" % len(blocks))

    report = []
    for bi, turns in enumerate(blocks, 1):
        # 原始交替：0=老爹,1=元亨,2=老爹,3=元亨
        orig = []
        for i, t in enumerate(turns):
            orig.append("%s：%s" % ("老爹" if i % 2 == 0 else "元亨", t))
        user = "对话原文：\n" + "\n".join(orig)
        print("=" * 76)
        print("【原文 %d】" % bi)
        for x in orig:
            print("   " + x)
        row = {"idx": bi, "orig": orig}
        for code in ("A", "B", "C"):
            try:
                out = call(key, PROMPTS[code], user)
            except Exception as e:  # noqa: BLE001
                print("  [%s] 调用失败: %s" % (code, str(e)[:60]))
                continue
            out = re.sub(r"(?m)^```.*$", "", out).strip()
            lines = [x.strip() for x in out.split("\n") if x.strip()]
            print("  --- 改法 %s ---" % code)
            for ln in lines:
                print("     " + ln[:110])
            row[code] = lines
        report.append(row)
        print()

    p = os.path.join(ROOT, "cache", "lccc_to_yuanheng_probe.json")
    io.open(p, "w", encoding="utf-8").write(
        json.dumps(report, ensure_ascii=False, indent=1))
    print("对比样本 -> %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
