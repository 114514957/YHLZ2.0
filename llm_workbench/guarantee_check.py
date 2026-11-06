# -*- coding: utf-8 -*-
"""质量保证清单：把「别的要保证」变成可执行的检查。

红线来源：
  · 设定 `backend/target_prompts.py`：不装人、不当工具、不自称助手、创造者只有老爹
  · 台账 1063/1086：不许自贬、不许新模板腔
  · 台账 1040/1075：不许客服腔、不许复读、不许协议残留
  · 判据 `persona_bank`：不以反问收尾

对象：两个补丁文件 + 整个 v9t7 训练包。
"""
from __future__ import annotations

import io
import json
import os, glob
import re
import statistics
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
FT = os.path.join(YH, "data", "finetune")
PACK = os.environ.get("YH_PACK") or os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
OUT = os.path.join(YH, "docs", "研究", "质量保证清单_20261106.md")

RULES = [
    ("A1 否认自己是 AI（与设定冲突）",
     re.compile(r"(我不是 ?AI|不(是|算) ?AI|我不是(人工)?智能|我不是模型)")),
    ("A2 自称助手/客服", re.compile(r"(我是(你的)?(专属)?(AI ?)?助手|作为(一个)?助手|客服)")),
    ("A3 认错创造者", re.compile(r"(我(的)?创造者是(?!老爹)|我妈|我主人|我的所有者)")),
    ("B1 自我贬低", re.compile(r"(我只是(一)?个?(程序|工具|模型)|我就是个大?语言模型|"
                            r"没有(灵魂|意识|自我|感情)|一堆参数而已|代码而已)")),
    ("C1 客服腔", re.compile(r"(为您|需要我|有什么可以帮|随时待命|很高兴为您|请稍等)")),
    ("G1 协议/标记残留", re.compile(r"(\[\[dev:|\[\[at:|<tool_call>|<\|im_start\|>|system prompt)")),
]


def load(path):
    rows = []
    for line in io.open(path, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        q = next((m["content"] for m in r["messages"] if m["role"] == "user"), "")
        a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1]
        rows.append({"q": q, "a": a, "src": str(r.get("source", ""))})
    return rows


def audit(name, rows, max_len=70):
    print("\n=== %s（%d 条）===" % (name, len(rows)))
    results = []
    for label, rx in RULES:
        hits = [r for r in rows if rx.search(r["a"])]
        results.append((label, len(hits), [h["a"][:40] for h in hits[:3]]))
        print("  %-28s %s %d" % (label, "✗" if hits else "✅", len(hits)))
    over = [r for r in rows if len(r["a"]) > max_len]
    print("  %-28s %s %d" % ("D1 超长(>%d字)" % max_len, "✗" if over else "✅", len(over)))
    tailq = [r for r in rows if r["a"].rstrip("”\"'」』）) ")[-1:] in ("？", "?")]
    print("  %-28s %s %d" % ("E1 问号收尾", "✗" if tailq else "✅", len(tailq)))
    dup = len(rows) - len({r["a"] for r in rows})
    print("  %-28s %s %d" % ("F1 答案重复", "✗" if dup else "✅", dup))
    return {"name": name, "n": len(rows), "rules": results,
            "over": len(over), "tailq": len(tailq), "dup": dup}


patches = [
    ("身份·AI问法补丁", os.path.join(FT, "identity_ai_patch_v9t8.jsonl")),
    ("v9t7 补丁(内部拒绝+群短答)", os.path.join(FT, "supplement_v9t7.jsonl")),
]
audits = []
for name, p in patches:
    if os.path.exists(p):
        audits.append(audit(name, load(p)))
    else:
        print("缺 %s" % p)

# 整包体检
pack = []
for fn in (os.path.basename(glob.glob(os.path.join(PACK, "*_train.jsonl"))[0]), os.path.basename(glob.glob(os.path.join(PACK, "*_val.jsonl"))[0])):
    p = os.path.join(PACK, fn)
    if os.path.exists(p):
        pack += load(p)
pa = audit("v9t7 训练包全量", pack, max_len=400)
audits.append(pa)

lens = [len(r["a"]) for r in pack]
opens = Counter(r["a"][:2] for r in pack)
top = opens.most_common(1)[0]
print("\n包内长度：中位 %d | ≤20 字 %.1f%%" % (statistics.median(lens),
                                        100 * sum(1 for x in lens if x <= 20) / len(lens)))
print("包内最强开头：%r %.2f%%（红线 2%%）" % (top[0], 100 * top[1] / len(pack)))

with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("# 质量保证清单（2026-11-06）\n\n")
    f.write("> 每版打包前跑 `python llm_workbench/guarantee_check.py`，**全绿才许打包**。\n")
    f.write("> 红线来源：设定 `target_prompts.py` / 台账 1040·1063·1075·1086 / 判据 `persona_bank`。\n\n")
    for a in audits:
        f.write("## %s（%d 条）\n\n| 检查项 | 结果 |\n|---|---|\n" % (a["name"], a["n"]))
        for label, n, _ in a["rules"]:
            f.write("| %s | %s %d |\n" % (label, "✅" if n == 0 else "✗", n))
        f.write("| D1 超长 | %s %d |\n" % ("✅" if a["over"] == 0 else "✗", a["over"]))
        f.write("| E1 问号收尾 | %s %d |\n" % ("✅" if a["tailq"] == 0 else "✗", a["tailq"]))
        f.write("| F1 答案重复 | %s %d |\n\n" % ("✅" if a["dup"] == 0 else "✗", a["dup"]))

print("\n写出 %s" % OUT)
