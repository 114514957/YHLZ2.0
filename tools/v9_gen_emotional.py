#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用从开源对白学到的**机制**，产元亨自己的「情绪承接」素材。

【学的是什么（机制，不是台词）】来源 `catbohe/TreeHoleEcho`（Apache-2.0）实测：
  · 回话中位 **27 字**、p95 40 字、**0% 超过 60 字**
  · **只复述对方的处境与感受**，不解释、不建议（给建议仅 2%）、不追问（仅 1%）、不总结
  · 12 类情绪：焦虑/无力感/职场压抑/孤独/委屈/挫败/迷茫/自我否定/愤怒/羞耻/亲情冲突/同辈压力

【不学什么】`newcjh/Arya` 100% 带 `*动作旁白*`、99% 分块叙述 → 反面教材，明文禁止。

【元亨怎么化】不照 TreeHoleEcho 的"温暖倾听者"口吻（那是客服/咨询师感），改成元亨：
  傲娇外壳 + 真在意；比 27 字更短更直；可以损第三方但**不损老爹**；
  不灌鸡汤、不列建议、不追问三连；关心落在"我在/我听着/别硬扛"这类短句上。

用法：
    python tools/v9_gen_emotional.py --start 0 --count 12
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
os.chdir(ROOT)
OUT_DIR = os.path.join(ROOT, "docs", "素材", "_草稿")

# (编号, 情绪, 老爹的处境——全部原创，取自老爹的真实生活面)
SCENES = [
    ("职场被甩锅", "方案是主管改的，出了事全记我头上，我一句都没辩解"),
    ("无回报加班", "加班到十一点改完的东西，转手被别人署名发全部门了"),
    ("绩效被否", "绩效谈话说我主动性不够，我出来在楼道站了半天"),
    ("反复刷消息", "群里说要重新调整架构，没人吭声，我把那条消息刷了三遍"),
    ("会议挤满", "一天被拉进三个会，正事全堆到晚上，地铁上靠着门不想动"),
    ("被人背后说", "有人跟别人讲我活儿都是抢来的，我至今没找到是谁"),
    ("撑不住", "我最近总觉得提不起劲，什么都想往后拖"),
    ("做砸了", "这个项目我搞砸了，责任在我，我不想找理由"),
    ("被当透明", "开会时我提了三次，没人接，最后别人重复了一遍就被采纳了"),
    ("亲人施压", "家里又打电话来问什么时候定下来，我不想聊这个"),
    ("同辈对比", "同龄人一个个都升了，我还在这儿原地打转"),
    ("身体扛不住", "连着几天睡不好，白天脑子像蒙了层布"),
    ("被辜负", "我帮了他那么多回，这次我开口，他装没看见"),
    ("怕做错", "每件事我都要检查五遍才敢交，还是怕出错"),
    ("说不清", "我也说不上哪里不对，就是整个人闷着"),
    ("被误解", "我说的是这个意思，他非理解成另一个，还到处讲"),
    ("失去", "养了很久的东西没了，我知道它不是人，可就是难受"),
    ("孤独", "晚上回到家，静得能听见自己心跳"),
    ("羞耻", "当众被指出错了，我当时只想找个地缝"),
    ("愤怒", "我真的想拍桌子，可我一句都没说"),
    ("迷茫", "不知道该往哪走，做什么都像在拖时间"),
    ("无力", "我试了很多办法，一件都没推动"),
    ("委屈", "我明明按他说的做了，最后又是我的问题"),
    ("旧事复发", "以为早过去了，今天一句话又全回来了"),
]

SYS = (
    "你在为「元亨」项目写中文对话素材。只输出 Markdown 对话块，不解释。\n"
    "【任务】写 2 轮：老爹说一件烦心事，元亨做**情绪承接**。\n"
    "【铁律：承接的机制（从开源对白学来的，必须遵守）】\n"
    "1. **元亨每轮回答不超过 30 字**，越短越好；两轮加起来不超过 60 字。\n"
    "2. **只接对方的处境和感受**，不解释原因、不给建议、不列步骤、不总结道理。\n"
    "3. **不许追问**（不要问「然后呢」「你怎么想的」），最多在第一轮末尾留一句极短的确认。\n"
    "4. **不许复述老爹整段话**——挑一个点接住就行。\n"
    "5. 不许写成咨询师/客服口吻（禁止「我理解你的感受」「你已经做得很好了」这类套话）。\n"
    "【元亨的口吻】\n"
    "- 傲娇外壳 + 真的在意。可以损**第三方**（那个主管、那个人），但**绝不损老爹**。\n"
    "- 关心落在极短的实处：「我在。」「我听着。」「别硬扛。」「骂吧。」「这不是你的错。」\n"
    "- 自称在 我/咱/本小姐/老娘 之间按情绪切换；老爹心烦时少用「本小姐」摆架子。\n"
    "【禁止】括号动作、舞台旁白（不许出现 *…* 或（…））、Markdown、列表、助手腔；\n"
    "禁词：我这边、我接、我认、稳了、很稳、别指望；不许说「理论上来说」。\n"
    "【块头与轮次格式——必须原样照这个形状，不许写成「老爹：」「元亨：」这种紧凑行】\n"
    "```\n"
    "## 承-p<N>\n"
    "- category: 情绪承接\n"
    "- emotion: <情绪>\n"
    "- length_tier: short\n"
    "- contract: VOICE_ANCHOR\n"
    "### 老爹问1\n"
    "（老爹说烦心事的原话）\n"
    "### 元亨答1\n"
    "（元亨第一句，≤30 字）\n"
    "### 老爹问2\n"
    "（老爹补充一句，更贴近具体感受）\n"
    "### 元亨答2\n"
    "（元亨第二句，≤30 字，不复述第一句说过的）\n"
    "```\n"
    "**`###` 标题行必须原样出现**（`### 老爹问1` / `### 元亨答1` / `### 老爹问2` / `### 元亨答2`）。\n"
    "不要用代码围栏包起来。块之间用一行 `=====` 分隔。\n"
)


def load_key() -> str:
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import scene_v8 as sv
    return sv.load_key()


def ds_call(key: str, user: str, max_tokens: int = 1200) -> str:
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
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())["choices"][0]["message"].get("content", "")


def convert_compact(blk: str) -> str:
    """兜底：把「老爹：…／元亨：…」的紧凑写法转成标准轮次标题。

    2026-10-20 实测：模型经常无视示例，写成紧凑行。内容其实可用，
    这里只在**格式**上转换，不动一个字。
    """
    lines = blk.split("\n")
    out, ask_i, ans_i = [], 0, 0
    for ln in lines:
        s = ln.strip()
        m = re.match(r"^(老爹|利贞|元亨)\s*[：:]\s*(.+)$", s)
        if m and not s.startswith("#"):
            who, text = m.group(1), m.group(2).strip()
            if who == "元亨":
                ans_i += 1
                out.append("### 元亨答%d" % ans_i)
            else:
                ask_i += 1
                out.append("### %s问%d" % (who, ask_i))
            out.append(text)
        else:
            out.append(ln)
    return "\n".join(out)


def validate(blk: str) -> str:
    if not blk.startswith("## "):
        return "块头不对"
    if not re.search(r"^###\s*元亨答\d+\s*$", blk, re.M):
        return "没有元亨答"
    if re.search(r"\*[^*\n]{2,}\*|（[^）\n]{1,12}）", blk):
        return "有动作旁白/括号"
    ans = re.findall(r"^###\s*元亨答\d+\s*\n(.+?)(?=\n###|\Z)", blk, re.M | re.S)
    for a in ans:
        a = a.strip()
        if len(a) > 34:
            return "回答过长 %d 字（承接应 ≤30）" % len(a)
        if re.search(r"建议|不如|可以试试|你应该|我理解你|你已经很棒", a):
            return "有建议/咨询师套话"
    if sum(len(a.strip()) for a in ans) > 70:
        return "两轮合计过长"
    import v9_story_gate as G
    r = G.check_block("x", blk, "general")
    if r["status"] == "FAIL":
        return "；".join(r["fails"])[:60]
    return ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=12)
    a = ap.parse_args()

    sel = SCENES[a.start:a.start + a.count]
    print("情景表共 %d 个，本次 %d 个" % (len(SCENES), len(sel)))
    key = load_key()
    outs, failed = [], []
    for i, (emo, scene) in enumerate(sel):
        n = a.start + i + 1
        user = ("情绪：%s\n老爹说的烦心事（原话，尽量直接用）：%s\n\n"
                "请写一个 2 轮的情绪承接对话块，块名编号用 %d。\n"
                "提醒：元亨每轮 ≤30 字，只承接不建议不追问不复述全文。"
                % (emo, scene, n))
        try:
            resp = ds_call(key, user)
        except Exception as exc:  # noqa: BLE001
            print("  [%d] API 失败: %s" % (i, exc))
            continue
        blk = re.sub(r"(?m)^```[a-zA-Z]*\s*$", "", resp).strip()
        if not re.search(r"^###\s*\S+[问答]\d+\s*$", blk, re.M):
            blk = convert_compact(blk)
        why = validate(blk)
        if why:
            failed.append((emo, why))
            print("  [%d] %-10s ❌ %s" % (i, emo, why))
        else:
            outs.append(blk)
            print("  [%d] %-10s ✅" % (i, emo))

    print("\n通过 %d｜失败 %d" % (len(outs), len(failed)))
    for e in failed[:5]:
        print("   %s: %s" % e)
    if outs:
        os.makedirs(OUT_DIR, exist_ok=True)
        p = os.path.join(OUT_DIR, "情绪承接_%s_%d-%d.md"
                         % (time.strftime("%Y%m%d_%H%M%S"), a.start, a.start + len(sel)))
        io.open(p, "w", encoding="utf-8").write("\n\n".join(outs) + "\n")
        print("已写 ->", os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
