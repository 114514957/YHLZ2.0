# -*- coding: utf-8 -*-
"""加"召回线索"闸门后再测：闲聊没有回忆意图，不该触发记忆注入。

线索 = 明确在问过去/求证/指代某件事的说法：
  记得/记住/上次/之前/我说过/你说过/那[个件次]/后来/是什么/为什么/怎么回事/
  多少/谁/哪里/哪个/是不是/有没有/来着
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

CUE = re.compile(r"(记得|记住|记着|上次|之前|我说过|你说过|那[个件次]|后来|"
                 r"是什么|为什么|怎么回事|怎么回|多少|谁|哪里|哪个|是不是|"
                 r"有没有|来着|讲过|说过|聊过|哪窟|哪本书)")
ENG = re.compile(r"(报错|测试|重启|脚本|训练|评测|接口|端口|提交|部署|编译|显存|日志|"
                 r"命令|进程|配置|代码|文件|目录|函数|变量|bug|BUG|git|pip|npm)")
STOP = {"在吗", "嗯", "哦", "晚安", "早", "哈哈", "哈哈哈哈", "在不在", "你说呢"}
NONWORD = re.compile(r"[\s\W_]+")

db, vec = default_paths(ROOT)
cases = [json.loads(x) for x in
         io.open(os.path.join(ROOT, "data", "eval", "memory_recall.jsonl"),
                 encoding="utf-8") if x.strip()]
idx = SemanticIndex(vec)
assert idx.load(db), "索引没载入"

from backend.vector_memory import embed_cls  # noqa: E402

Q = np.asarray(embed_cls([c["q"] for c in cases]), dtype=np.float32)
Q /= (np.linalg.norm(Q, axis=1, keepdims=True) + 1e-9)
S = Q @ idx._matrix.T


def gate(q: str, sim_min: float, min_chars: int) -> tuple[bool, str]:
    body = NONWORD.sub("", q)
    if body in STOP or q.strip() in STOP:
        return False, "寒暄"
    if ENG.search(q):
        return False, "工程"
    if len(body) < min_chars:
        return False, "太短"
    if not CUE.search(q):
        return False, "无线索"
    return True, "ok"


def run(sim_min: float, min_chars: int, limit: int = 2) -> tuple[int, int, int]:
    hit = fp = hard_fp = 0
    for i, c in enumerate(cases):
        ok, why = gate(c["q"], sim_min, min_chars)
        ids = []
        if ok:
            order = np.argsort(-S[i])[:limit]
            ids = [idx._ids[int(j)] for j in order if S[i][j] >= sim_min]
        if c["should_hit"]:
            if any(x in ids for x in c["expect_ids"]):
                hit += 1
        elif ids:
            fp += 1
            if c.get("cat") == "hard":
                hard_fp += 1
    return hit, fp, hard_fp


print("%-34s %-12s %-10s %s" % ("参数", "命中", "误报", "难负样本误报"))
print("-" * 70)
best = None
for sim_min in (0.42, 0.45, 0.48, 0.52):
    for min_chars in (6, 8):
        hit, fp, hfp = run(sim_min, min_chars)
        print("%-34s %2d/25        %2d/20      %d/5"
              % ("sim≥%.2f 长度≥%d + 线索闸门" % (sim_min, min_chars), hit, fp, hfp))
        if best is None or (hit - 3 * fp) > best[0]:
            best = (hit - 3 * fp, sim_min, min_chars, hit, fp, hfp)

print("\n最佳：sim≥%.2f 长度≥%d → 命中 %d/25、误报 %d/20（难负 %d/5）"
      % (best[1], best[2], best[3], best[4], best[5]))

print("\n=== 逐条（最佳参数）===")
for i, c in enumerate(cases):
    ok, why = gate(c["q"], best[1], best[2])
    ids = []
    if ok:
        order = np.argsort(-S[i])[:2]
        ids = [idx._ids[int(j)] for j in order if S[i][j] >= best[1]]
    good = (any(x in ids for x in c["expect_ids"]) if c["should_hit"] else not ids)
    print("%s %-4s %-30s %s" % ("✅" if good else "❌", c["id"], c["q"][:30],
                                (why if not ok else "top=%.3f" % S[i].max())))
