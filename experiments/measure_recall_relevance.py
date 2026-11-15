# -*- coding: utf-8 -*-
"""分开量：真用户发言 vs 合成上下文块；并判断命中是否"相关"。

相关判据（宽）：问句与命中摘要共享至少 2 个不同的 3-gram，或共享至少 2 个汉字词。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)
from backend.target_memory import TargetMemoryService  # noqa: E402

svc = TargetMemoryService(db_path=os.path.join(ROOT, "cache", "memstore", "memstore.db"))
FAKE = re.compile(r"^\[(群聊最近记录|群上下文摘要)|仅供理解|不要逐条回应")


def grams(s: str, n: int = 3) -> set[str]:
    s = re.sub(r"[\s\W_]+", "", s)
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


real, fake = [], []
for p in glob.glob(os.path.join(ROOT, "cache", "qq_daily", "*.jsonl")):
    for ln in io.open(p, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        if r.get("role") != "user":
            continue
        t = str(r.get("text") or "").strip()
        if len(t) < 6:
            continue
        (fake if FAKE.search(t) else real).append(t)

print("真用户发言 %d 条｜合成上下文块 %d 条" % (len(real), len(fake)))


def run(name: str, turns: list[str]) -> None:
    hit = rel = junk = 0
    junk_samples = []
    for t in turns:
        try:
            got = svc.contextual_recall(t, limit=3)
        except Exception:  # noqa: BLE001
            continue
        if not got:
            continue
        hit += 1
        best = got[0]
        a, b = grams(t), grams(str(best.get("summary") or ""))
        # 去掉过于通用的中文片段（问句里的"什么""怎么"等）
        stop = {"什么", "怎么", "为什", "么样", "是不", "不是", "可以", "现在", "今天"}
        shared = (a & b) - stop
        if len(shared) >= 2:
            rel += 1
        else:
            junk += 1
            if len(junk_samples) < 3:
                junk_samples.append((t[:50], str(best.get("summary"))[:70]))
    print("\n=== %s ===" % name)
    n = len(turns) or 1
    print("   命中 %d/%d = %.1f%%" % (hit, len(turns), 100 * hit / n))
    if hit:
        print("   其中看着相关 %d（%.0f%%）｜明显无关 %d（%.0f%%）"
              % (rel, 100 * rel / hit, junk, 100 * junk / hit))
    for q, h in junk_samples:
        print("      无关例：问「%s」→ 命中「%s」" % (q, h))


run("真用户发言", real)
run("合成上下文块", fake)
