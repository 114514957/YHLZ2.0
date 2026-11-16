# -*- coding: utf-8 -*-
"""写风格时刻度报告 + 提交。"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DOC = os.path.join(ROOT, "docs", "风格", "风格时刻度_20261116.md")

L = """# 风格时刻度（2026-11-16）

> 老爹：「做时刻度，随时读取时间，分清因果先后。」
> 数据源：`cache/qq_bridge/lite/group_history.db` 的 `group_messages`（6240 条，
> **自带 `at` 列，100% 有时间**——我先前的"没有时间轴"是看漏了字段）。

## 一、清洗前后的对照（这就是因果）

破折号机械清洗是 **2026-11-14** 上线的，于是可以直接对照：

| 区间 | 句数 | 破折号 | 反问收尾 | 带 @ | 均长 |
|---|---|---|---|---|---|
| **清洗前（< 11-14）** | 1292 | **47.0%** | 1.3% | 53.7% | 81 字 |
| **清洗后（≥ 11-14）** | 76 | **0.0%** | 0.0% | 57.9% | 48 字 |

**结论：清洗 100% 生效（47% → 0%）**，同时句子变短（81 → 48 字）、反问归零。
先前我说"27.5% 仍在发生"是**取样窗口跨了清洗日**造成的误判。

## 二、按天（最近有发言的日子）

| 日期 | 句数 | 均长 | 破折号 | 反问 | 带@ |
|---|---|---|---|---|---|
| 10-06 | 105 | 46 | 45% | 4% | 19% |
| 10-07 | 158 | 81 | 48% | 0% | 85% |
| 10-08 | 154 | 101 | 48% | 1% | 17% |
| 10-09 | 191 | 71 | 51% | 1% | 45% |
| 10-10 | 178 | 83 | 53% | 1% | 52% |
| 10-11 | 122 | 74 | 52% | 2% | 48% |
| 10-12 | 61 | 183 | 57% | 3% | 11% |
| 10-13 | 59 | 79 | 76% | 0% | 58% |
| 10-15 | 59 | 62 | 37% | 0% | 93% |
| 10-16 | 80 | 99 | 61% | 4% | 98% |
| 10-20 | 45 | 67 | 2% | 0% | 96% |
| 11-13 | 80 | 42 | 5% | 1% | 75% |
| 11-15 | 76 | 48 | **0%** | 0% | 58% |

## 三、时刻度怎么用（以后每次改风格都这么做）

1. 改动**之前**记一笔：日期 + 改了什么（台账）
2. 改动**之后**用 `python experiments/style_trend_by_day.py` 看按天趋势
3. **只有清洗/机械规则**才能一眼看出因果（47%→0% 这类）；
   **提示词类改动**要看 152 题评测 + 至少 3 天真实群聊趋势

## 四、已知局限

- 她的发言只占群消息约 22%（1368/6240），单日样本 40–190 句，**比例波动 ±5% 属噪声**；
- `group_messages` 的 `at` 是**入库时间**（桥收到的时间），与 QQ 侧时间可能有秒级偏差；
- 私聊发言不在这个表里（需要另取 console 会话档案），所以**这张表只代表"群里的她"**。
"""
os.makedirs(os.path.dirname(DOC), exist_ok=True)
io.open(DOC, "w", encoding="utf-8").write(L)
print("已写：%s" % os.path.relpath(DOC, ROOT))

MSG = os.path.join(ROOT, "cache", "cm_clock.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "feat(style): 风格时刻度——按天统计 + 清洗前后因果对照\n\n"
    "老爹：做时刻度，随时读取时间，分清因果先后。\n\n"
    "发现：group_messages **自带 at 列且 100% 填满**（6240 条，10-06→11-15），\n"
    "我之前说「没有时间轴」是看漏了字段。\n\n"
    "按时刻对照（破折号清洗 11-14 上线）：\n"
    "  清洗前 1292 句：破折号 47.0%｜反问 1.3%｜带@ 53.7%｜均长 81\n"
    "  清洗后   76 句：破折号  0.0%｜反问 0.0%｜带@ 57.9%｜均长 48\n"
    "  → 机械清洗 100% 生效；先前「27.5% 仍在发生」是取样跨了清洗日。\n\n"
    "产物：docs/风格/风格时刻度_20261116.md、experiments/style_trend_by_day.py\n"
    "另加 tools/backfill_message_time.py（加列/回填/覆盖率检查，幂等）。\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-60:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-110:])
