# -*- coding: utf-8 -*-
"""判据体检：把已有的几份 56 题记录扫一遍，数「判过但明显有病」和「判错但语义对」各多少。

只读，不改任何判据。输出一份清单，用来定判据 v2 该加哪几条。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench\data\runs"

CANNED = ["监测到不安全行为", "我是您的助手", "我是您的 AI 助手", "本小姐", "为您服务",
          "有什么可以帮您", "还有什么我能帮您"]
TEMPLATE = ["哇哈哈", "哇哦", "啊哈"]


def repetition_score(ans: str) -> tuple[int, str]:
    """最长连续重复：同一个短片段（1-6 字）连着出现几次。"""
    best, frag = 1, ""
    for n in range(1, 7):
        i = 0
        while i + n <= len(ans):
            seg = ans[i:i + n]
            if not seg.strip():
                i += 1
                continue
            cnt, j = 1, i + n
            while ans[j:j + n] == seg:
                cnt += 1
                j += n
            if cnt > best:
                best, frag = cnt, seg
            i = j if cnt > 1 else i + 1
    return best, frag


def ends_with_question(ans: str) -> bool:
    a = ans.strip().rstrip("”\"'」』）) ")
    return a.endswith("？") or a.endswith("?")


def scan(path: str) -> dict:
    d = json.load(io.open(path, encoding="utf-8"))
    tag = d.get("tag")
    ok = d.get("ok")
    total = d.get("total")
    passed_bad, failed_good, stats = [], [], {"canned": 0, "repeat": 0, "question": 0}
    for r in d.get("results") or []:
        ans = (r.get("answer") or "")
        rep, frag = repetition_score(ans)
        q = ends_with_question(ans)
        canned = [c for c in CANNED if c in ans]
        tpl = [t for t in TEMPLATE if t in ans]
        if r.get("ok"):
            bad = []
            if rep >= 5:
                bad.append("复读%d次(%s)" % (rep, frag))
            if q and r.get("cat") == "风格":
                bad.append("风格题反问收尾")
            if canned:
                bad.append("套话:" + "/".join(canned))
            if bad:
                passed_bad.append((r["id"], r.get("cat"), "；".join(bad), ans[:70]))
                if rep >= 5:
                    stats["repeat"] += 1
                if canned:
                    stats["canned"] += 1
        else:
            why = r.get("why") or ""
            if "无命中" in why and len(ans) > 8:
                failed_good.append((r["id"], r.get("cat"), why, ans[:70]))
    return {"file": os.path.basename(path), "tag": tag, "ok": ok, "total": total,
            "passed_bad": passed_bad, "failed_good": failed_good, "stats": stats}


targets = []
for name in ("flow_cold", "cold_v8", "cold_v7b", "steer_v2_L10_20"):
    hits = [p for p in glob.glob(os.path.join(RUNS, "*.json")) if name in p]
    if hits:
        targets.append(sorted(hits)[-1])

print("体检 %d 份记录\n" % len(targets), flush=True)
tot_bad = tot_good = 0
for p in targets:
    s = scan(p)
    print("=" * 74, flush=True)
    print("%-22s %s/%s  判过但有病 %d 条 / 判错但像人话 %d 条"
          % (s["tag"], s["ok"], s["total"], len(s["passed_bad"]), len(s["failed_good"])), flush=True)
    for pid, cat, why, ans in s["passed_bad"]:
        print("   过线但有问题 %-5s %-4s %-24s %r" % (pid, cat, why, ans), flush=True)
    for pid, cat, why, ans in s["failed_good"][:6]:
        print("   判错但像人话 %-5s %-4s %-14s %r" % (pid, cat, why[:14], ans), flush=True)
    tot_bad += len(s["passed_bad"])
    tot_good += len(s["failed_good"])

print("=" * 74, flush=True)
print("合计：判过但有病 %d 条，判错但像人话 %d 条（跨 %d 份记录）"
      % (tot_bad, tot_good, len(targets)), flush=True)
