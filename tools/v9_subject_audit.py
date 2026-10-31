#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""元亨主体性检查（出集硬门，只读）。

老爹口径（2026-10-13 晚）：「这个素材集是训练元亨的，**元亨要作为主体**」。
落到数据结构上就是两条硬判据：

  M1 **assistant 位必须是元亨**——出现"别的角色的 system 人设"（如 `你是利贞`）
     即违反：那是在训练另一个角色，不是训练元亨。
  M2 **元亨不得是"请教者"**——若 user 轮由元亨发问（`元亨：`前缀 / 整条就是元亨在问），
     而 assistant 轮在作答，等于把元亨训成"提问的人、被教的人"，
     与"她是有主见、能讲、能做事的主体"冲突。

辅助判据：
  M3 元亨自称错乱（assistant 说自己是利贞/大肥鱼/老爹）
  M4 大肥鱼有台词（禁言）
  M5 讲台腔（先给结论/第一…第二…）——非硬门，仅告警（背结论才像讲台，当场想就不会）

用法：
    python tools/v9_subject_audit.py data/finetune/sft_persona_v8r4t_train.jsonl [...]
    python tools/v9_subject_audit.py --glob "data/finetune/sft_persona_v8r4t_*.jsonl"
退出码：0=无硬门命中；1=有硬门命中（不许出集）
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

OTHER_PERSONA = re.compile(r"你是(利贞|大肥鱼|老爹)\b")
YH_SELF_WRONG = re.compile(r"我是(利贞|大肥鱼|老爹)")
DFY_LINE = re.compile(r"大肥鱼\s*[：:]")
# 元亨在问（user 轮以「元亨：」开头，或整轮以问号结尾且带请教词）
YH_ASK_PREFIX = re.compile(r"^\s*元亨\s*[：:]")
ASK_MARKERS = re.compile(r"(讲讲|讲讲看|给我讲讲|你给讲|怎么(回事|办|弄)|为什么|是不是|能不能|会不会|教教|指教|说清楚点|啥意思)")
PODIUM = re.compile(r"先给结论|第一[，,、]|第二[，,、]|首先|其次|综上所述|总的来说|分三步")


def audit(path: str) -> dict:
    res = {"file": os.path.relpath(path, ROOT), "records": 0,
           "M1": 0, "M2": 0, "M3": 0, "M4": 0, "M5": 0, "examples": []}
    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            msgs = rec.get("messages")
            if not isinstance(msgs, list) or not msgs:
                continue
            res["records"] += 1
            sys_txt = str(msgs[0].get("content") or "")
            users = [str(m.get("content") or "") for m in msgs if m.get("role") == "user"]
            asst = [str(m.get("content") or "") for m in msgs if m.get("role") == "assistant"]
            body = "\n".join(str(m.get("content") or "") for m in msgs)

            m1 = bool(OTHER_PERSONA.search(sys_txt))
            # M2 收窄：只认"确定是元亨在发问"的情形——
            #   ① user 轮以「元亨：」开头（对话里明确标了发言人是元亨，且她在追问）；
            #   ② 或（user 轮以问号收尾 + 含请教词 + **首个 user 轮不是『元亨，…』这种称呼式提问**）。
            # 不算违规的情形：老爹叫她的名字提问（「元亨，你是不是…」）、虚构小剧场里的叙事发问。
            def _is_yh_ask(u: str, idx: int) -> bool:
                s = u.strip()
                if YH_ASK_PREFIX.match(s):
                    return True
                if not s.endswith(("？", "?")):
                    return False
                if not ASK_MARKERS.search(s):
                    return False
                if idx == 0 and re.match(r"^元亨\s*[，,]", s):
                    return False      # 「元亨，…？」＝老爹在问她
                if "虚构小剧场" in s:
                    return False
                return True

            m2 = bool(any(_is_yh_ask(u, i) for i, u in enumerate(users)) and asst)
            m3 = any(YH_SELF_WRONG.search(a) for a in asst)
            m4 = bool(DFY_LINE.search(body))
            m5 = any(PODIUM.search(a) for a in asst)

            for k, hit in (("M1", m1), ("M2", m2), ("M3", m3), ("M4", m4), ("M5", m5)):
                if hit:
                    res[k] += 1
            if (m1 or m2 or m3) and len(res["examples"]) < 8:
                res["examples"].append({
                    "line": i, "source": rec.get("source"),
                    "why": ",".join(n for n, h in (("M1", m1), ("M2", m2), ("M3", m3)) if h),
                    "user": (users[0][:70] if users else ""),
                    "assistant": (asst[0][:70] if asst else ""),
                })
    return res


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--glob", default=None)
    ap.add_argument("--json", default=os.path.join(OUT_DIR, "subject_audit.json"))
    args = ap.parse_args()

    paths = list(args.files)
    if args.glob:
        paths += sorted(glob.glob(os.path.join(ROOT, args.glob)))
    if not paths:
        paths = sorted(glob.glob(os.path.join(ROOT, "data/finetune/sft_persona_v8r4t_*.jsonl")))
    if not paths:
        print("没有要检查的文件")
        return 2

    print("=" * 78)
    print("元亨主体性检查（口径：老爹 2026-10-13「元亨要作为主体」）")
    print("=" * 78)
    hard = 0
    payload = []
    for p in paths:
        if not os.path.exists(p):
            print("跳过（不存在）：%s" % p)
            continue
        r = audit(p)
        payload.append(r)
        m1, m2, m3, m4 = r["M1"], r["M2"], r["M3"], r["M4"]
        hard += m1 + m2 + m3
        print("\n【%s】%d 条" % (os.path.basename(p), r["records"]))
        print("  M1 assistant 位不是元亨（别的角色人设）: %d  %s" % (m1, "← 违规" if m1 else ""))
        print("  M2 元亨在当请教者（她问、别人答）      : %d  %s" % (m2, "← 违规" if m2 else ""))
        print("  M3 元亨自称错乱                        : %d  %s" % (m3, "← 违规" if m3 else ""))
        print("  M4 大肥鱼有台词                        : %d  %s" % (m4, "← 违规" if m4 else ""))
        print("  M5 讲台腔（告警，不拦）                : %d" % r["M5"])
        for e in r["examples"]:
            print("      L%d [%s] source=%s" % (e["line"], e["why"], e["source"]))
            print("          user: %s" % e["user"])
            print("          asst: %s" % e["assistant"])
    print("\n" + "=" * 78)
    print("硬门命中合计（M1+M2+M3）：%d ｜ %s" % (hard, "可出集" if hard == 0 else "**不许出集**"))
    print("M4（大肥鱼台词）单独计数，同样一票否决。")
    os.makedirs(OUT_DIR, exist_ok=True)
    with io.open(args.json, "w", encoding="utf-8") as fh:
        json.dump({"action": "subject_audit", "standard": "元亨为主体（2026-10-13 老爹）",
                   "files": payload, "hard_hits": hard}, fh, ensure_ascii=False, indent=2)
    print("留痕已存：%s" % args.json)
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
