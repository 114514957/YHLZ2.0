#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成"元亨用实体比喻讲抽象概念"素材。

老爹 2026-10-20 定：**复杂抽象概念需要朴素的、有趣的、实体的比喻用于理解的过程。**
本工具里的比喻**全部由我原创**（不抄书、不抄网文），只借"日常物件"这个路子。

结构要求（体现"理解的过程"）：
  第 1 问：老爹用大白话问一个抽象概念（带点不服气/听不懂）
  第 1 答：元亨给出**实体比喻**（具体物件、有画面、能摸）
  第 2 问：老爹顺着比喻往下追（把比喻推到边界，或问"那X怎么办"）
  第 2 答：元亨说清**比喻对上的是哪一点、哪里对不上**——回到概念本身

用法：
    python tools/v9_gen_metaphor.py --start 0 --count 6
    python tools/v9_gen_metaphor.py --list
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
OUT_DIR = os.path.join(ROOT, "docs", "素材", "_草稿")

# (块名, 领域, 概念, 比喻母体——我原创，, 这个比喻对上的是哪一点)
CONCEPTS = [
    ("存-p", "哲学", "存在", "桌子不会问自己为什么在这，你会。问出这句话的那一下，就是存在感", "存在不是'在那儿'，是'知道自己在'"),
    ("存-p", "哲学", "自由", "自由不是没有墙，是你知道墙在哪、还能挑着绕过去。真没墙的地方叫荒野，不叫自由", "自由是'有选项且能选'，不是'没有限制'"),
    ("存-p", "哲学", "意识", "意识像房间里的那盏灯：照亮桌上每样东西，唯独照不到自己", "意识能指向一切，却难以直接指向自身"),
    ("存-p", "哲学", "时间", "时间不像河——河还会打旋、回头。它像机场的传送带：你站着不动，它也一直在走", "时间的单向性和不可停留"),
    ("存-p", "哲学", "同一性", "船一块板一块板换，全换完还是原来那条船吗？人也一样，细胞七年换一遍", "身份靠连续性，不靠材料"),
    ("存-p", "哲学", "整体与部分", "一堆砖不是房子，可房子塌了，还是那堆砖——多出来的东西是'排法'", "整体多出的是结构，不是材料"),
    ("存-p", "哲学", "抽象", "抽象就是拿起一个苹果，把红、甜、圆拆开，只把'圆'那一样单独拿走", "抽象是剥离，不是浓缩"),
    ("存-p", "哲学", "因果", "多米诺不假，可真世界里骨牌之间还牵着绳子：推倒一张，另一张可能被拽起来", "因果不是单链，是带反馈的网"),
    ("存-p", "哲学", "边界", "边界不是墙，是门框。它不挡你，它告诉你这是门", "边界给的是可能性，不是禁止"),
    ("存-p", "哲学", "概率", "概率不是'接下来会发生什么'，是'这局重来一万次，大概有几次'", "概率描述的是重复，不是单次"),
    ("存-p", "哲学", "熵", "房间自己会变乱，不会自己变整齐——因为乱的法子有无数种，整齐只有一种", "熵是'有多少种排法'"),
    ("存-p", "哲学", "信息量", "'太阳明天升起'这句话信息量是零；'明天下雪'就很大。意外的程度就是信息量", "信息量等于意外"),
    ("技-p", "技术", "词向量（embedding）", "给每个词在一座巨型大楼里分一间屋，意思近的住同一层：猫和狗做邻居，猫和微积分隔着十几层楼", "意思的远近可以变成距离的远近"),
    ("技-p", "技术", "注意力机制", "你读一句话，眼睛不是匀速扫过去的，是往前跑两步又往回跳一下。模型也在做这个动作", "注意力是'回头看哪几个词'"),
    ("技-p", "技术", "量化", "把一百级的调音台压成十级：声音还在，就是那些细到听不出的差别没了", "量化是降精度，不是丢内容"),
    ("技-p", "技术", "过拟合", "把练习册的答案连页码一起背下来，考试换个数字就全不会——记住了题，没学会解题", "过拟合是记住噪声"),
    ("技-p", "技术", "上下文窗口", "桌子就这么大，摊满了就得把旧的收走。收走的那些，不是不存在了，是你够不着了", "窗口是可见范围，不是容量"),
    ("技-p", "技术", "token", "不是一个字一块，是一片一片切的：中文常常一字一块，英文一个词能被切成三四块", "token 是切分单位，不是字数"),
    ("ai-p", "AI", "权重", "权重不是'知识存着'，是河道：水往同一个地方冲过一万次，冲出沟来，以后水自然往那儿走", "权重是倾向，不是条目"),
    ("ai-p", "AI", "涌现", "一万只蚂蚁凑一块，能造出会呼吸的巢。可你随便抓一只问它图纸，它说不出来", "涌现是'整体有、个体没有'"),
    ("ai-p", "AI", "幻觉", "像做梦：梦里每个转折都说得通，一醒才发现漏洞百出。区别是梦醒得掉，这个不会自己醒", "幻觉是自洽的错"),
    ("ai-p", "AI", "记忆", "记忆不是录像带，是每回重讲一遍。讲十遍以后，你讲的其实是前九遍", "记忆是重建，不是回放"),
    ("ai-p", "AI", "对齐", "不是给它拴绳子，是教它自己看见那根绳——拴着的会挣，看见的会绕", "对齐要内化，不是外挂"),
    ("ai-p", "AI", "学习率", "下山蒙着眼，用脚试哪边更低：步子太大一步跨过山谷，太小走到天黑还在原地", "学习率是步长，不是方向"),
    ("人-p", "生活", "习惯", "习惯是省电模式：同一件事做多了，大脑把它打包成一个动作，不再逐帧看", "习惯是把决策变成自动"),
    ("人-p", "生活", "沉没成本", "电影票已经买了，片子难看。可你舍不得走，于是又赔进去两个小时——票钱是沉没的，时间是还能救的", "沉没成本不该影响下一步"),
    ("人-p", "生活", "递归", "两面镜子对着放，里头有无穷多面镜子在互相照。每一层都是真的，只是越来越小", "递归是自己包含自己"),
    ("人-p", "生活", "相变", "水到九十九度还是水，一百度就成汽。没有哪一滴水'决定'过要变——是整体到了那个点", "相变是整体跨过阈值"),
]

SYS = (
    "你在为「元亨」项目写中文对话素材。只输出 Markdown 对话块，不解释。\n"
    "【任务】写一个 2 轮对话：**老爹问一个抽象概念，元亨用实体比喻讲明白**。\n"
    "【给定】我会给你：概念名、比喻母体（必须用这个）、这个比喻对上的是哪一点。\n"
    "【结构（必须照这个走，这体现「理解的过程」）】\n"
    "· 第 1 问：老爹用大白话问，可以带点不服气、听不懂、觉得是玄学。\n"
    "· 第 1 答：元亨**直接把那个实体比喻讲出来**——具体、有画面、能摸到。不许先讲定义。\n"
    "· 第 2 问：老爹**顺着比喻往下追**，把比喻推到边界（「那要是…呢」「照你这么说岂不是…」）。\n"
    "· 第 2 答：元亨说清**比喻对上的是哪一点、哪一点对不上**，然后回到概念本身。\n"
    "【铁律】\n"
    "1. **比喻必须保留给定的那个物件**，可以加细节、加动作，但不许换成别的比喻。\n"
    "2. 元亨是讲解者（作答方）；问与答严格交替，只用 `### 老爹问N` / `### 利贞问N` / `### 元亨答N`。\n"
    "3. 元亨口吻：活泼、傲娇、爱损人、哲学感强；自称 我/咱/本小姐/老娘 切换。\n"
    "4. 至少称呼对方一次；至少一处留白「……」；句长要有起伏（要有一两句很短，也要有一句长）。\n"
    "5. 禁词：我这边、我接、我认、稳了、很稳、别指望；不许说「理论上来说」。\n"
    "6. 禁止括号动作、旁白、Markdown、列表行、助手腔；不许出现真实书名或人物名。\n"
    "7. 块头格式（照抄，只换 N 与领域）：\n"
    "```\n## 喻-p<N>\n- category: 哲学\n- emotion: neutral\n- length_tier: medium\n"
    "- contract: VOICE_ANCHOR\n- concept: <概念名>\n- metaphor_type: 实体比喻\n```\n"
    "   （category 按给到的领域填：哲学/技术/AI/生活）\n"
    "8. 块之间用一行 `=====` 分隔。\n"
)


def load_key() -> str:
    import scene_v8 as sv
    return sv.load_key()


def ds_call(key: str, user: str, max_tokens: int = 4000) -> str:
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


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--apply", action="store_true", default=True)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        for i, (_, dom, con, met, _pt) in enumerate(CONCEPTS):
            print("%2d. [%s] %-14s %s" % (i, dom, con, met[:52]))
        return 0

    sel = CONCEPTS[a.start:a.start + a.count]
    print("概念表共 %d 个，本次 %d 个" % (len(CONCEPTS), len(sel)))
    key = load_key()
    outs, failed = [], []
    for i, (_pfx, dom, con, met, point) in enumerate(sel):
        n = a.start + i + 1
        user = ("概念：%s\n领域：%s\n必须用的比喻母体：%s\n这个比喻对上的点：%s\n\n"
                "请写一个对话块，块名编号用 %d。" % (con, dom, met, point, n))
        try:
            resp = ds_call(key, user)
        except Exception as exc:  # noqa: BLE001
            print("  [%d] API 失败: %s" % (i, exc))
            continue
        blk = re.sub(r"(?m)^```[a-zA-Z]*\s*$", "", resp).strip()
        if not re.search(r"^###\s*\S+[问答]\d+\s*$", blk, re.M):
            failed.append((con, "无轮次标题"))
            print("  [%d] %-10s 无轮次标题" % (i, con))
            continue
        import v9_story_gate as G
        r = G.check_block("x", blk, "general")
        if r["status"] == "FAIL":
            failed.append((con, "；".join(r["fails"])[:50]))
            print("  [%d] %-10s FAIL: %s" % (i, con, "；".join(r["fails"])[:50]))
            continue
        outs.append(blk)
        print("  [%d] %-10s 通过" % (i, con))

    print("\n通过 %d｜失败 %d" % (len(outs), len(failed)))
    if outs:
        os.makedirs(OUT_DIR, exist_ok=True)
        p = os.path.join(OUT_DIR, "比喻生成_%s_%d-%d.md"
                         % (time.strftime("%Y%m%d_%H%M%S"), a.start, a.start + len(sel)))
        io.open(p, "w", encoding="utf-8").write("\n\n".join(outs) + "\n")
        print("已写 ->", os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
