# -*- coding: utf-8 -*-
"""两档闸门：有召回线索→0.45；无线索→必须极高相似(0.65+)。

理由：注入是"隐约想起"，多喂噪音比漏掉更伤；但太保守就白做了。
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

from backend.memory_recall_semantic import SemanticIndex, default_paths  # noqa: E402
from backend.vector_memory import embed_cls  # noqa: E402

CUE = re.compile(r"(记得|记住|记着|上次|之前|我说过|你说过|那[个件次]|后来|是什么|"
                 r"为什么|怎么回事|多少|谁|哪里|哪个|是不是|有没有|来着|讲过|说过|聊过)")
QUESTION = re.compile(r"[?？]|吗|呢|怎么|什么|哪个?|多少|为什么|能不能|是不是|会不会|要不要")
ENG = re.compile(r"(报错|测试|重启|脚本|训练|评测|接口|端口|提交|部署|编译|显存|日志|"
                 r"命令|进程|配置|代码|文件|目录|函数|变量|bug|BUG|git|pip|npm)")
STOP = {"在吗", "嗯", "哦", "晚安", "早", "哈哈", "哈哈哈哈", "在不在", "你说呢"}
NONWORD = re.compile(r"[\s\W_]+")

db, vec = default_paths(ROOT)
cases = [json.loads(x) for x in
         io.open(os.path.join(ROOT, "data", "eval", "memory_recall.jsonl"),
                 encoding="utf-8") if x.strip()]
idx = SemanticIndex(vec)
assert idx.load(db)

Q = np.asarray(embed_cls([c["q"] for c in cases]), dtype=np.float32)
Q /= (np.linalg.norm(Q, axis=1, keepdims=True) + 1e-9)
S = Q @ idx._matrix.T


def decide(q: str, sim: float, cue_th: float, high_th: float, min_chars: int) -> tuple:
    body = NONWORD.sub("", q)
    if body in STOP or q.strip() in STOP:
        return False, "寒暄", 0.0
    if ENG.search(q):
        return False, "工程", 0.0
    if len(body) < min_chars:
        return False, "太短", 0.0
    if CUE.search(q) or QUESTION.search(q):
        return (sim >= cue_th), ("有线索" if sim >= cue_th else "有线索但不够像"), cue_th
    return (sim >= high_th), ("无线索" if sim >= high_th else "无线索"), high_th


def run(cue_th: float, high_th: float, min_chars: int = 6, limit: int = 2):
    hit = fp = hfp = 0
    for i, c in enumerate(cases):
        sim = float(S[i].max())
        ok, _why, _th = decide(c["q"], sim, cue_th, high_th, min_chars)
        ids = []
        if ok:
            order = np.argsort(-S[i])[:limit]
            ids = [idx._ids[int(j)] for j in order if S[i][j] >= _th]
        if c["should_hit"]:
            if any(x in ids for x in c["expect_ids"]):
                hit += 1
        elif ids:
            fp += 1
            hfp += 1 if c.get("cat") == "hard" else 0
    return hit, fp, hfp


print("%-40s %-10s %-10s %s" % ("参数", "命中", "误报", "难负"))
print("-" * 72)
rows = []
for cue_th in (0.42, 0.45, 0.48):
    for high_th in (0.60, 0.65, 0.70):
        hit, fp, hfp = run(cue_th, high_th)
        rows.append((hit - 3 * fp, cue_th, high_th, hit, fp, hfp))
        print("%-40s %2d/25      %2d/20      %d/5"
              % ("线索≥%.2f 无线索≥%.2f" % (cue_th, high_th), hit, fp, hfp))

rows.sort(reverse=True)
_b, cue_th, high_th, hit, fp, hfp = rows[0]
print("\n最佳：线索≥%.2f 无线索≥%.2f → 命中 %d/25、误报 %d/20（难负 %d/5）"
      % (cue_th, high_th, hit, fp, hfp))

print("\n=== 逐条 ===")
for i, c in enumerate(cases):
    sim = float(S[i].max())
    ok, why, th = decide(c["q"], sim, cue_th, high_th, 6)
    order = np.argsort(-S[i])[:2]
    ids = [idx._ids[int(j)] for j in order if S[i][j] >= th] if ok else []
    good = (any(x in ids for x in c["expect_ids"]) if c["should_hit"] else not ids)
    print("%s %-4s %-28s %-14s sim=%.3f"
          % ("✅" if good else "❌", c["id"], c["q"][:28], why, sim))
