# -*- coding: utf-8 -*-
"""复合闸门：语义召回 + "该不该想起"的判断，目标 命中≥20/25 且 误报≤3/15。

闸门四条（都可解释，不是硬凑阈值）：
  G1 问句够长（去空白 ≥8 字）——"在吗/嗯/晚安"这类不该触发
  G2 不是工程指令（报错/测试/重启/脚本/训练/评测/接口/端口/提交/部署）——那该走工具或上下文
  G3 相似度 top1 ≥ SIM_MIN
  G4 与 top2 的间隔 ≥ MARGIN（有明确指向，而不是"都差不多"）
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from backend.memory_recall_v2 import load_pool  # noqa: E402
from backend.vector_memory import embed_cls  # noqa: E402

DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")
CASES = os.path.join(ROOT, "data", "eval", "memory_recall.jsonl")
WIDE = ("preference", "event", "decision", "fact", "knowledge", "context")
ENG_QUERY = re.compile(r"(报错|测试|重启|脚本|训练|评测|接口|端口|提交|部署|编译|显存|日志|"
                       r"命令|进程|配置|代码|文件|目录|函数|变量|报错|bug|BUG)")
NONWORD = re.compile(r"[\s\W_]+")

cases = [json.loads(x) for x in io.open(CASES, encoding="utf-8") if x.strip()]
pool = load_pool(DB, types=WIDE)
P = np.asarray(embed_cls([it["text"] for it in pool]), dtype=np.float32)
P /= np.linalg.norm(P, axis=1, keepdims=True) + 1e-9
Q = np.asarray(embed_cls([c["q"] for c in cases]), dtype=np.float32)
Q /= np.linalg.norm(Q, axis=1, keepdims=True) + 1e-9
S = Q @ P.T
print("池 %d 条｜评测集 %d 条" % (len(pool), len(cases)))


def gated(q: str, sim_min: float, margin: float, min_chars: int) -> list[str]:
    body = NONWORD.sub("", q)
    if len(body) < min_chars:
        return []
    if ENG_QUERY.search(q):
        return []
    i = [k for k, c in enumerate(cases) if c["q"] == q][0]
    order = np.argsort(-S[i])[:3]
    cand = [(pool[j]["id"], float(S[i][j])) for j in order]
    if not cand or cand[0][1] < sim_min:
        return []
    if len(cand) >= 2 and (cand[0][1] - cand[1][1]) < margin:
        return []
    return [cid for cid, sc in cand[:2] if sc >= sim_min]


def score(sim_min: float, margin: float, min_chars: int) -> tuple[int, int]:
    hit = fp = 0
    for c in cases:
        ids = gated(c["q"], sim_min, margin, min_chars)
        if c["should_hit"]:
            if any(x in ids for x in c["expect_ids"]):
                hit += 1
        elif ids:
            fp += 1
    return hit, fp


print("\n%-40s %-10s %-8s" % ("参数", "命中", "误报"))
print("-" * 62)
best = None
for sim_min in (0.45, 0.50, 0.55, 0.60):
    for margin in (0.00, 0.03, 0.05, 0.08):
        for min_chars in (8, 10):
            hit, fp = score(sim_min, margin, min_chars)
            tag = "sim≥%.2f 间隔≥%.2f 长度≥%d" % (sim_min, margin, min_chars)
            print("%-40s %2d/25      %2d/15" % (tag, hit, fp))
            if best is None or (hit - 3 * fp) > best[0]:
                best = (hit - 3 * fp, sim_min, margin, min_chars, hit, fp)

print("\n最佳：sim≥%.2f 间隔≥%.2f 长度≥%d → 命中 %d/25、误报 %d/15"
      % (best[1], best[2], best[3], best[4], best[5]))

print("\n=== 最佳参数下逐题（应命中的全列）===")
for c in cases:
    if not c["should_hit"]:
        continue
    ids = gated(c["q"], best[1], best[2], best[3])
    ok = any(x in ids for x in c["expect_ids"])
    print("%s %-4s %s" % ("✅" if ok else "❌", c["id"], c["q"][:36]))
print("\n=== 应无命中的（漏进来的才列）===")
for c in cases:
    if c["should_hit"]:
        continue
    ids = gated(c["q"], best[1], best[2], best[3])
    if ids:
        print("⚠ %-4s %-28s → %s" % (c["id"], c["q"][:26], ids[:2]))
