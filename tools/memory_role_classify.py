# -*- coding: utf-8 -*-
"""阶段 1.5 第 1 步：给 1022 条记忆分层（her / owner / engineering）。

**只读，不改库**。输出分类明细到 `cache/memory_role_report.json` + 屏显统计。
分层规则（可解释、可复现）：

  her        她自己的：带 `元亨:` 前缀的群聊原话；她自己说过的；成长/日记类来源
  owner      老爹相关的：source 含 老爹/owner/qq_private；或内容里明确是老爹的偏好/要求/事实
  engineering 工程流水账：含台账回显、记录编号、验收/探针/链路/重构/接口/端口/部署/测试证据、
             或"用户决策/用户问题"这类工作流回显
  其它        都不像 → 判为 unknown（先不注入，等人工或二次规则）
"""
from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")
OUT = os.path.join(ROOT, "cache", "memory_role_report.json")

ENG_STRONG = re.compile(
    r"(台账|记录 ?\d{3,4}|用户决策|用户要求|本轮依据|验收|探针|冻结|链路|重构|部署|接口|端口|"
    r"测试证据|只动目标|Provider|架构|数据库|脚本|编译|显存|LoRA|数据集|评测|回归|"
    r"计划表|会话档案|工作流|开发经验|opencode|利贞|简报|待处理|基线|批次|批处理|"
    r"设计结论|模块化|Session Kernel|WebUI|Health Supervisor|判定清单|收敛|"
    r"仍需用户确认|未决事项|下一步依据|能力模块|审计|PR |提交)")
ENG_MED = re.compile(r"(配置|日志|模型|训练|GPU|CPU|服务|进程|版本|字段|接口|调用|api|API|"
                     r"阈值|指标|场景|扬声器|耳机|认证)")

# 她自己的：只在**群聊原话**里认（`元亨:` 前缀），agent 来源**不算**（那是开发日志）
HER_TALK = re.compile(r"元亨[:：]")
HER_TALK_LEN = 8
# 开发日志来源：直接归 engineering
DEV_SRC = re.compile(r"(agent|opencode|利贞)")
OWNER_SRC = re.compile(r"(老爹|owner|qq_private)")
OWNER_TXT = re.compile(r"(老爹|你爹|爸|主人)")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    "select id,type,importance,summary,source,evidence_ref,created_at,status from l2_items")]
con.close()


def classify(r: dict) -> tuple[str, str]:
    t = str(r["summary"] or "")
    src = str(r["source"] or "")
    # 0) 开发日志来源 → 工程（2026-11-15 修：上一版把 agent 判成 her，错）
    if DEV_SRC.search(src):
        return "engineering", "开发日志来源(%s)" % src[:16]
    # 1) 她自己说的：群聊原话且像话（不是单字/符号）
    if HER_TALK.search(t) and len(HER_TALK.sub("", t).strip()) >= HER_TALK_LEN:
        return "her", "群聊原话"
    eng_s = len(ENG_STRONG.findall(t))
    eng_m = len(ENG_MED.findall(t))
    # 2) 工程流水账
    if eng_s >= 1:
        return "engineering", "工程强特征×%d" % eng_s
    if eng_m >= 3:
        return "engineering", "工程中特征×%d" % eng_m
    # 3) 老爹相关（且不是工程）
    if OWNER_SRC.search(src) or OWNER_TXT.search(t):
        return "owner", "来源/内容含老爹"
    if eng_m >= 1:
        return "unknown", "弱工程特征×%d（待人工）" % eng_m
    return "unknown", "规则未覆盖"


rep = defaultdict(list)
for r in rows:
    role, why = classify(r)
    rep[role].append({"id": r["id"], "type": r["type"], "imp": r["importance"],
                      "src": r["source"], "why": why, "text": str(r["summary"])[:120]})

print("=== 分层结果（1022 条，只读）===")
for role in ("her", "owner", "engineering", "unknown"):
    v = rep.get(role, [])
    print("  %-12s %4d 条（%.1f%%）" % (role, len(v), 100 * len(v) / len(rows)))

print("\n=== 各层样例 ===")
for role in ("her", "owner", "engineering", "unknown"):
    print("\n-- %s --" % role)
    for it in rep.get(role, [])[:4]:
        print("   [%s|imp=%s|%s] %s" % (it["type"], it["imp"], it["why"], it["text"][:80]))

print("\n=== 与「是否会被注入」的对照 ===")
# contextual_recall 只注入 preference/event/decision 且 importance>=4
INJECT_TYPES = ("preference", "event", "decision")
injectable = Counter()
for role, items in rep.items():
    for it in items:
        if it["type"] in INJECT_TYPES and (it["imp"] or 0) >= 4:
            injectable[role] += 1
print("  满足现有注入条件（type∈pref/event/decision 且 imp≥4）的：%s" % dict(injectable))
print("  其中 engineering 的占比：%.1f%%"
      % (100 * injectable["engineering"] / max(1, sum(injectable.values()))))

io.open(OUT, "w", encoding="utf-8").write(
    json.dumps({k: v for k, v in rep.items()}, ensure_ascii=False, indent=1))
print("\n明细：%s" % os.path.relpath(OUT, ROOT))
print("（未改库；下一步拿这份表给老爹看）")
