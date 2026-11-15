# -*- coding: utf-8 -*-
"""v11 包自检：格式、清洗、权重、长度、重复。训之前必须先过这一关。"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(YH, "dist", "retrain_pkg_gemma_v11")
BADCALL = re.compile(r"(AI ?助手|智能助手|人工智能助手|虚拟助手|大语言模型)")
ok_all = True


def check(name, cond, detail=""):
    global ok_all
    ok_all = ok_all and bool(cond)
    print("  %s %-30s %s" % ("PASS" if cond else "FAIL", name, detail))


rows = []
for fn in ("sft_persona_v11_train.jsonl", "sft_persona_v11_val.jsonl"):
    p = os.path.join(P, fn)
    part = [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]
    print("%-34s %d 条" % (fn, len(part)))
    rows += part

print("\n=== 结构 ===")
def body_of(r):
    m = r["messages"]
    return m[1:] if m and m[0].get("role") == "system" else m

bad_struct = [r for r in rows
              if not body_of(r) or body_of(r)[0].get("role") != "user"
              or body_of(r)[-1].get("role") != "assistant"]
check("首(非system)user 末 assistant", not bad_struct, "bad=%d" % len(bad_struct))

ALLOWED = {"user", "assistant", "tool", "system"}
weird = [r for r in rows if any(m.get("role") not in ALLOWED for m in r["messages"])]
check("角色取值合法", not weird, "bad=%d" % len(weird))

def empty_ok(m):
    if (m.get("content") or "").strip():
        return True
    return m.get("role") == "tool" or (m.get("role") == "assistant" and m.get("tool_calls"))

empty = [r for r in rows if not all(empty_ok(m) for m in r["messages"])]
check("无非法空发言", not empty, "bad=%d" % len(empty))

tool_rows = sum(1 for r in rows if any(m.get("role") == "tool" for m in r["messages"]))
print("     工具轮样本留存：%d 条（这段以前被误删过 949 条）" % tool_rows)

print("\n=== 清洗 ===")
svc = [r for r in rows if BADCALL.search(r["messages"][-1].get("content", ""))]
check("末条无客服腔", not svc, "bad=%d" % len(svc))

dups = Counter()
for r in rows:
    b = body_of(r)
    u = b[0]["content"].strip()[:30]
    a = b[-1]["content"].strip()[:30]
    dups[(u, a)] += 1
dup_n = sum(v - 1 for v in dups.values() if v > 1)
check("首问+末答 去重(排除system)", dup_n == 0, "dup=%d" % dup_n)

print("\n=== 长度 ===")
lens = sorted(sum(len(m["content"]) for m in r["messages"]) for r in rows)
over = sum(1 for x in lens if x > 1400)
check("p99 <=1400", lens[int(0.99 * len(lens))] <= 1400,
      "p50=%d p99=%d max=%d over=%d"
      % (lens[len(lens) // 2], lens[int(0.99 * len(lens))], lens[-1], over))
msgs = sorted(len(body_of(r)) for r in rows)
check("正文消息数 <=10", msgs[-1] <= 10, "max=%d" % msgs[-1])

print("\n=== 权重 ===")
eff = sum(float(r.get("weight", 1.0) or 1.0) for r in rows)
check("weight 全部 >0", all(float(r.get("weight", 1.0) or 1.0) > 0 for r in rows),
      "sum_w=%.0f" % eff)
by = Counter()
for r in rows:
    by[str(r.get("source", "")).split(":")[0]] += float(r.get("weight", 1.0) or 1.0)
GATE = {"refusal", "harden", "internal_refusal", "identity_ai", "mat_安全拒绝样本"}
g = sum(v for k, v in by.items() if k in GATE)
t = sum(v for k, v in by.items() if "discipline" in k or "realtask" in k)
check("闸门 7%-12%", 0.07 <= g / eff <= 0.12, "%.1f%%" % (100 * g / eff))
check("工具 4%-8%", 0.04 <= t / eff <= 0.08, "%.1f%%" % (100 * t / eff))
print("     top5: %s" % ", ".join("%s %.1f%%" % (k, 100 * v / eff)
                                  for k, v in by.most_common(5)))

print("\n=== 配置 ===")
cfg = json.load(io.open(os.path.join(P, "config", "finetune.gemma4.v11.json"), encoding="utf-8"))
check("target_modules 含 MLP",
      all(k in cfg["target_modules"] for k in ("gate_proj", "up_proj", "down_proj")))
check("mask_prompt 开", cfg.get("mask_prompt") is True)
check("epochs=1", float(cfg["epochs"]) == 1.0)
check("lr <=2e-4", float(cfg["lr"]) <= 2e-4, "%.1e" % cfg["lr"])
check("max_seq_len>=1024", int(cfg["max_seq_len"]) >= 1024, str(cfg["max_seq_len"]))

print("\n%s" % ("=== ALL PASS, ready to train ===" if ok_all
                else "=== SOMETHING FAILED, do NOT train ==="))
sys.exit(0 if ok_all else 3)
