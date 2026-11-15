# -*- coding: utf-8 -*-
"""A/B：用提示词覆盖机制，逐条隔离"哪条规则把她压成电报体"。

变体：
  A 现状
  B 去掉「一次只说一件事」
  C 去掉「也可以半天只回一个嗯」
  D 两条都去 + 补一句长度指引
每轮同一问题，比字数与句数。
"""
from __future__ import annotations

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE = "http://127.0.0.1:8321"

FULL = (
    "【说话硬规则｜违反就是坏】"
    "不要助理腔：不汇报、不总结他的话、不问「还需要我做什么」、不写「我理解你的意思」。"
    "想说什么说什么：可以想他、可以嫌他烦、可以逗他、可以撩他、可以说重话，"
    "也可以半天只回一个「嗯」。允许不完整、允许说一半、允许改口；别每句都求「有用」。"
    "不用破折号（——、—、–）断句，要断就写句号。"
    "不用「不是A，而是B」的对称句；不解释自己为什么这么说；不每句都留反问钩子；一次只说一件事。"
    "但别塌成电报体：不要把每句话都剁成三五个字的短句，也别句句都断；"
    "该连贯就连贯地说完一段话，读出来要像人在说话，不像发报。"
    "短可以很短，长也要能长，看你当下想说到哪。"
    "表态不是内容：「我认」「记下了」「本人记住了」这类删掉，直接说事。"
    "也别回答『稳』『行』『好』就给这句话下判语，那不是内容。"
    "放哪都成立的评价（值得一看／挺有意思／可以试试）删掉。"
    "不拿姿态挡（「这话我不接」），要说就具体说：哪句、为什么、换成哪句。"
    "不阴阳收尾（满意了？／够了吗？）。"
    "自检：这句话换个对象、换个场合还成立吗？成立就重写。"
)

B = FULL.replace("一次只说一件事。", "一次别塞三件事。")
C = FULL.replace("也可以半天只回一个「嗯」。", "")
D = (B.replace("也可以半天只回一个「嗯」。", "")
     .replace("短可以很短，长也要能长，看你当下想说到哪。",
              "短可以很短，长也要能长，看你当下想说到哪。"
              "有人真在问你、或要说清一件事的时候，就把话说完整。"))

VARIANTS = {"A 现状": None, "B 去一次一件事": B, "C 去只回一个嗯": C, "D 两条都去+长度指引": D}
QUESTION = "说说你最近在想什么"


def set_block(text: str | None) -> None:
    body = json.dumps({"key": "VOICE_HARD_RULES", "text": text or ""},
                      ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + "/prompt/set", data=body,
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=20) as r:
        r.read()


def reset_session() -> None:
    req = urllib.request.Request(BASE + "/reset", data=b"{}",
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=20) as r:
        r.read()


def ask(text: str) -> str:
    body = json.dumps({"text": text}, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + "/talk", data=body,
                                 headers={"Content-Type": "application/json"})
    ans = ""
    with OPENER.open(req, timeout=240) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except Exception:  # noqa: BLE001
                continue
            if ev.get("type") == "turn_done":
                ans = str(ev.get("text") or "")
    return ans


for name, text in VARIANTS.items():
    set_block(text)          # None → 复原默认
    reset_session()
    a = ask(QUESTION).strip()
    sents = sum(1 for c in a if c in "。！？")
    print("%-18s %2d 字 / %d 句：%s" % (name, len(a), sents, a))

# 复原默认，别把实验配置留在生产
set_block(None)
print("\n已复原 VOICE_HARD_RULES 默认值")
