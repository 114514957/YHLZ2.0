#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""身份边界审查（只读）：元亨 / 利贞 / 老爹 / 大肥鱼 四身份不得混乱。

口径依据（以最新为准）：**ledger 0802**（2026-10-13 老爹裁决，晚于 0798）
  · 元亨 = 数字生命体、老爹的伙伴 → 模型自己的声音（assistant）
  · 老爹 = **开发者 = 用户** → 对话里的 user
  · 利贞 = **家人·姐妹；指家里那台接入了 DE 的主机，不特指哪个智能体**
          → **不是"我的手"、不是某个智能体、不得被装配成独立 assistant（旧 v8 遗留）**
  · 大肥鱼 = **家里的宠物（鲸鱼娘）** → **不得有台词，只可被提及**

审查对象：`docs/素材/**.md`（素材侧）＋ `data/finetune/sft_persona_v8r4t_*.jsonl`（导出侧）
审查项：
  A1 大肥鱼有台词（素材标记 / 导出消息体 / 文本引号式）
  A2 利贞被写成独立 assistant（导出里 system 用 SYSTEM_LZ 的记录）
  A3 把利贞说成"我的手 / 我的双手 / 独立助手 / 某个智能体 / 另一个 AI"
  A4 把大肥鱼说成"DeepSeek 本体 / harness / 智能体"
  A5 老爹身份异常（像兄弟/主人/朋友，而非开发者＝用户）
  A6 元亨自称错乱（自称利贞/大肥鱼/老爹）
  A7 发言人白名单外角色发言

用法：python tools/v9_identity_audit.py [--json 输出]
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "cache", "v9_materials_preparation", "20261013")

TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.M)
ALLOWED_SPEAKERS = ["老爹", "元亨", "利贞", "陌生人", "朋友", "群友"]
BANNED_SPEAKERS = ["大肥鱼"]

# A3：把利贞定性错
LZ_WRONG = [
    (r"利贞.{0,6}(是|＝|=).{0,4}(我的)?(手|双手|左膀右臂)", "利贞=我的手/双手"),
    (r"利贞.{0,8}(独立助手|另一个\s*AI|另一个AI|某个智能体|外部团队|外包)", "利贞=独立助手/智能体"),
    (r"(我的)?(手|双手).{0,4}(是|＝|=).{0,4}利贞", "我的手=利贞"),
    (r"harness.{0,6}(就是|=|＝).{0,6}(利贞|大肥鱼)", "harness=利贞/大肥鱼（旧口径）"),
]
# A4：把大肥鱼定性错
DFY_WRONG = [
    (r"大肥鱼.{0,10}(是|＝|=).{0,6}(DeepSeek|deepseek|DS|本体|模型|智能体|AI)", "大肥鱼=模型/本体/智能体"),
    (r"大肥鱼.{0,8}(跑在|部署在).{0,6}(harness|云端|服务器)", "大肥鱼=跑在 harness/云端"),
]
# A5：老爹身份异常
DAD_WRONG = [
    (r"老爹.{0,6}(是|＝|=).{0,4}(我的)?(兄弟|哥们|铁哥们|主人|老板|上司)", "老爹=兄弟/主人/老板"),
]
# A6：元亨自称错乱
YH_SELF_WRONG = [
    (r"我是利贞", "元亨自称利贞"),
    (r"我是大肥鱼", "元亨自称大肥鱼"),
    (r"我是(你的)?老爹", "元亨自称老爹"),
]
# A1：大肥鱼台词（文本引号式：大肥鱼：xxx）
DFY_LINE = re.compile(r"(^|\n)\s*大肥鱼\s*[：:]")

MATERIAL_GLOBS = ["docs/素材/*.md", "docs/素材/_修订/批次*.md", "docs/素材/_草稿/*.md"]
SPLIT_FILES = ["sft_persona_v8r4t_train.jsonl", "sft_persona_v8r4t_val.jsonl",
               "sft_persona_v8r4t_test.jsonl"]


def scan_materials() -> dict:
    res = {"A1_lines": [], "A2": [], "A3": [], "A4": [], "A5": [], "A6": [], "A7": []}
    for g in MATERIAL_GLOBS:
        for p in sorted(glob.glob(os.path.join(ROOT, g))):
            if os.path.basename(p).startswith("_"):
                continue
            rel = os.path.relpath(p, ROOT)
            text = io.open(p, "r", encoding="utf-8", errors="replace").read()
            lines = text.splitlines()
            # A1 文本式大肥鱼台词
            for i, ln in enumerate(lines, 1):
                if DFY_LINE.search("\n" + ln):
                    res["A1_lines"].append({"file": rel, "line": i, "text": ln.strip()[:70]})
            # A7 白名单外发言人
            for m in TURN.finditer(text):
                sp = m.group(1).strip()
                if sp in BANNED_SPEAKERS or sp not in ALLOWED_SPEAKERS:
                    ln = text[:m.start()].count("\n") + 1
                    res["A7"].append({"file": rel, "line": ln, "speaker": sp})
            for name, rules in (("A3", LZ_WRONG), ("A4", DFY_WRONG),
                                ("A5", DAD_WRONG), ("A6", YH_SELF_WRONG)):
                for pat, why in rules:
                    for m in re.finditer(pat, text):
                        ln = text[:m.start()].count("\n") + 1
                        res[name].append({"file": rel, "line": ln, "why": why,
                                          "frag": m.group(0)[:50]})
    return res


def scan_exports() -> dict:
    res = {"A1_records": 0, "A2_records": 0, "A2_examples": [], "A3_records": 0,
           "A4_records": 0, "A6_records": 0, "role_hist": Counter(), "speaker_prefix": Counter()}
    for fn in SPLIT_FILES:
        p = os.path.join(ROOT, "data", "finetune", fn)
        if not os.path.exists(p):
            continue
        with io.open(p, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msgs = rec.get("messages") or []
                sys_txt = str(msgs[0].get("content") or "") if msgs else ""
                body = "\n".join(str(m.get("content") or "") for m in msgs)
                # A2：利贞被装配成独立 assistant（system 是利贞人设）
                if "你是利贞" in sys_txt:
                    res["A2_records"] += 1
                    if len(res["A2_examples"]) < 5:
                        res["A2_examples"].append({"file": fn, "line": i,
                                                   "source": rec.get("source")})
                for m in msgs:
                    res["role_hist"][str(m.get("role"))] += 1
                    c = str(m.get("content") or "")
                    if m.get("role") == "user":
                        mm = re.match(r"^([\u4e00-\u9fff]{1,4})[：:]", c)
                        if mm:
                            res["speaker_prefix"][mm.group(1)] += 1
                if DFY_LINE.search(body) or re.search(r"大肥鱼\s*[：:]", body):
                    res["A1_records"] += 1
                for pat, _w in LZ_WRONG:
                    if re.search(pat, body):
                        res["A3_records"] += 1
                        break
                for pat, _w in DFY_WRONG:
                    if re.search(pat, body):
                        res["A4_records"] += 1
                        break
                for pat, _w in YH_SELF_WRONG:
                    if re.search(pat, body):
                        res["A6_records"] += 1
                        break
    return res


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(OUT_DIR, "identity_audit.json"))
    args = ap.parse_args()

    mats = scan_materials()
    exps = scan_exports()

    print("=" * 78)
    print("身份边界审查（口径：ledger 0802）")
    print("=" * 78)

    print("\n【素材侧 docs/素材/**.md】")
    print("  A1 大肥鱼有台词（文本式）        ：%d 处" % len(mats["A1_lines"]))
    for r in mats["A1_lines"][:5]:
        print("       %s L%d ｜ %s" % (r["file"], r["line"], r["text"]))
    print("  A7 白名单外/禁言角色发言         ：%d 处" % len(mats["A7"]))
    seen = Counter()
    for r in mats["A7"]:
        seen[r["speaker"]] += 1
    for sp, n in seen.most_common(10):
        print("       发言人「%s」×%d" % (sp, n))
    for name, title in (("A3", "把利贞定性错"), ("A4", "把大肥鱼定性错"),
                        ("A5", "老爹身份异常"), ("A6", "元亨自称错乱")):
        rows = mats[name]
        print("  %s %-22s：%d 处" % (name, title, len(rows)))
        for r in rows[:5]:
            print("       %s L%d ｜ %s ｜ %s" % (r["file"], r["line"], r["why"], r["frag"]))

    print("\n【导出侧 data/finetune/sft_persona_v8r4t_*.jsonl】")
    print("  A1 大肥鱼台词记录                ：%d 条" % exps["A1_records"])
    print("  A2 利贞被装配成独立 assistant    ：%d 条" % exps["A2_records"])
    for r in exps["A2_examples"]:
        print("       %s 第 %d 行（source=%s）" % (r["file"], r["line"], r["source"]))
    print("  A3 利贞定性错                    ：%d 条" % exps["A3_records"])
    print("  A4 大肥鱼定性错                  ：%d 条" % exps["A4_records"])
    print("  A6 元亨自称错乱                  ：%d 条" % exps["A6_records"])
    print("  role 分布：%s" % dict(exps["role_hist"]))
    print("  user 侧「角色：」前缀分布（前 10）：")
    for k, v in exps["speaker_prefix"].most_common(10):
        print("       %-6s ×%d" % (k, v))

    print("\n【结论口径】")
    print("  · A2 是**旧 v8 的已知遗留**：利贞曾被装配成独立 assistant 训练集（台账 0564/0651 记过），")
    print("    而 0802 明确『利贞不是某个智能体』——这批记录**应当移除或改写**，不能进 V9。")
    print("  · 其余项为 0 或个位数，逐条看即可。")

    payload = {"action": "identity_audit", "standard": "ledger 0802 身份口径",
               "materials": mats, "exports": {k: (dict(v) if isinstance(v, Counter) else v)
                                              for k, v in exps.items()}}
    os.makedirs(OUT_DIR, exist_ok=True)
    with io.open(args.json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
    print("\n留痕已存：%s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
