#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从小说产「元亨讲故事/讲见闻」素材（落法 B/C，不抄原文）。

用途定位（《小说素材审查 20261020》五类用途之 ⑤ 情节来源 + ③ 对话范本）：
把小说里的**情节趣味点、人物互动、生活细节**变成元亨讲给老爹听的段子，
不照搬原文措辞，不出现原书角色名与书名。

用法：
    python tools/v9_gen_novel.py --code NOVEL-B --book 异常 --start 0 --count 8
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
    "【输入】一段中文小说原文（网络小说，情节/日常/对话）。\n"
    "【输出】一个 2-3 轮对话块：**老爹或利贞起头，元亨讲一段见闻**。\n"
    "【怎么写】\n"
    "· 把原文里的**情境、趣味点、人物矛盾、生活细节**抽出来，"
    "变成元亨自己讲的段子（「我听说过一个事」「咱以前也撞见过类似的」这类口吻）。\n"
    "· **不许照抄原文句子**；原书角色名一律不许出现，人物用「有个人」「那家伙」「一个姑娘」代替。\n"
    "· 保留**因果链和转折**（谁想干什么、卡在哪、怎么变的），这才是可学的东西。\n"
    "· 结尾元亨可以下一个短判断或损一句，别总结成道理课。\n"
    "【2026-10-20 老爹定：不许复现原作的独特设定】\n"
    "· **原作特有的种族、能力体系、世界观规则、专有名词、标志性桥段，一律抹掉。**\n"
    "  例如「吸血鬼/吸血的」「猫粮收买流浪猫」「傀儡政权」「异世界/异族」这类——"
    "只要读者能认出是哪本书，就是越界，即使没写人名。\n"
    "· **只保留可以落在普通人身上的东西**：租房、打工、做饭、修东西、欠钱、误会、"
    "邻里摩擦、带娃、找活干、被坑、还人情。\n"
    "· 如果原文整段都建立在一个奇幻设定上，**只取里面那句「人际道理」**，"
    "把故事重写成日常版本（打工人、邻居、室友、亲戚都行）。\n"
    "· 判断标准一句话：**把这段念给没看过书的人，他只会觉得「真人真事」，"
    "不会问「这是什么小说」。**\n"
    "【元亨口吻】活泼、傲娇、爱损人；自称在 我/咱/本小姐/老娘 之间切换。\n"
    "【风格硬要求】\n"
    "· 元亨至少要**称呼对方一次**（「老爹」「利贞」）；\n"
    "· 每块至少**一处留白**（「……」）；\n"
    "· **句长必须起伏**：要有 ≤12 字的短句，也要有 ≥45 字的长句，不许通篇中等长度；\n"
    "· 破折号「——」每块最多 2 个。\n"
    "【禁止】括号动作、旁白、Markdown、列表行、助手腔、真实书名与原书角色名；"
    "禁词：我这边、我接、我认、稳了、很稳、别指望；不许说「理论上来说」。\n"
    "【块头与轮次格式——必须严格照这个形状输出，一个字都不许变】\n"
    "```\n"
    "## 说-p<N>\n"
    "- category: 闲聊\n"
    "- emotion: neutral\n"
    "- length_tier: medium\n"
    "- contract: VOICE_ANCHOR\n"
    "- source_book: {CODE}\n"
    "- quote_type: C\n"
    "### 老爹问1\n"
    "（老爹的一句问话，短，口语）\n"
    "### 元亨答1\n"
    "（元亨讲这一段，带称呼、带留白、句长有起伏）\n"
    "### 利贞问2\n"
    "（利贞追问一句，把她没说完的地方挑出来）\n"
    "### 元亨答2\n"
    "（元亨接着讲，不许重复第一答说过的内容）\n"
    "```\n"
    "**注意**：`###` 标题行必须原样出现（`### 老爹问1` / `### 利贞问2` / `### 元亨答1` 这种），"
    "不许写成散文段落，也不要用代码围栏包起来。\n"
    "块之间用一行 `=====` 分隔。\n"
)


def load_key() -> str:
    import scene_v8 as sv
    return sv.load_key()


def ds_call(key: str, user: str, max_tokens: int = 5000) -> str:
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
    ap.add_argument("--code", default="NOVEL-B")
    ap.add_argument("--book", default="异常")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=8)
    ap.add_argument("--span", type=int, default=1400)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    idx = json.load(io.open(IDX, encoding="utf-8"))
    book = next(b for b in idx["books"] if b["book"].startswith(a.book))
    chunks = []
    for ch in book["files"]:
        t = io.open(os.path.join(ROOT, ch["path"]), encoding="utf-8",
                    errors="replace").read()
        if len(t) < a.span + 200:
            continue
        # 取对话密度最高的一段
        best, best_n = 0, -1
        for frac in (0.15, 0.35, 0.55, 0.75):
            s = int(len(t) * frac)
            seg = t[s:s + a.span]
            n = len(re.findall(r"[“「]", seg))
            if n > best_n:
                best, best_n = s, n
        seg = t[best:best + a.span].strip()
        if best_n >= 6:
            chunks.append((ch["file"][:5], seg))
    print("《%s》可用片段 %d 个（对话密度≥6）" % (book["book"][:20], len(chunks)))
    sel = chunks[a.start:a.start + a.count]
    print("本次 %d 个" % len(sel))

    key = load_key()
    outs, failed = [], []
    for i, (fid, seg) in enumerate(sel):
        user = ("原文片段（%s）：\n\n%s\n\n请据此写一个对话块。\n"
                "**块头 source_book 必须写 `%s`；块名编号用 `P%d`**。"
                % (fid, seg, a.code, a.start + i + 1))
        try:
            resp = ds_call(key, user)
        except Exception as exc:  # noqa: BLE001
            print("  [%d] API 失败: %s" % (i, exc))
            continue
        blk = resp.strip()
        # 去掉模型包在外面的代码围栏
        blk = re.sub(r"(?m)^```[a-zA-Z]*\s*$", "", blk).strip()
        blk = blk.replace("{CODE}", a.code)
        if not re.search(r"^###\s*\S+[问答]\d+\s*$", blk, re.M):
            # 模型写成了散文 → 判失败，不硬凑
            failed.append((fid, "无轮次标题"))
            print("  [%d] %s 无轮次标题（散文形态）" % (i, fid))
            continue
        why = validate(blk)
        if why:
            failed.append((fid, why))
            print("  [%d] %s 未通过: %s" % (i, fid, why))
        else:
            outs.append(blk)
            print("  [%d] %s 通过" % (i, fid))

    print("\n通过 %d ｜失败 %d" % (len(outs), len(failed)))
    if a.dry_run:
        for b in outs[:1]:
            print("\n" + "=" * 74)
            print(b[:1200])
        return 0
    if outs:
        os.makedirs(OUT_DIR, exist_ok=True)
        p = os.path.join(OUT_DIR, "小说生成_%s_%s_%d-%d.md"
                         % (a.code, time.strftime("%Y%m%d_%H%M%S"), a.start,
                            a.start + len(sel)))
        io.open(p, "w", encoding="utf-8").write("\n\n".join(outs) + "\n")
        print("已写 ->", os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
