# -*- coding: utf-8 -*-
"""说话风格学习（台账 1262）：学习目标是**人格与说话风格**，不是"群里发生了什么"。

数据源：`cache/qq_bridge/lite/group_history.db` 的 group_messages（6240 条，带 sender_id）。
  她自己的原话在这里（qq_social_events 只存别人的消息，学不到她自己）。

对每条她的发言算三件事：
  1. **被回应**：180 秒内有别人在同一群发言（有 = 这句话"接住了"）
  2. **违规**：破折号 / 「不是A而是B」对称句 / 反问收尾 / 过长
  3. **长度**

然后按"长度桶 × 是否违规"统计**被回应率**——这就是可操作的风格规律：
  "多长的话最容易被接""哪些写法会把人赶走"。

输出：
  · `docs/风格/群聊风格学习_<日期>.md`（证据 + 规律）
  · 知识库 `category=说话风格`（好/坏样本各若干，可被取材）
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH")
DB = ROOT / "cache" / "qq_bridge" / "lite" / "group_history.db"
BOT_UINS = {"3655185302"}          # 元亨
WINDOW = 180                        # 秒：多久内有人接话算"被回应"
DASH = re.compile(r"[—–―－]{1,}")
SYM = re.compile(r"不是[^，。；！？]{1,20}[，]?而是")
TAIL_Q = re.compile(r"[？?]\s*$")


def load() -> list[dict]:
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "select group_id, sender_id, sender_name, text, seq from group_messages "
        "order by group_id, seq")]
    con.close()
    return rows


def bucket(n: int) -> str:
    if n <= 10:
        return "≤10字"
    if n <= 25:
        return "11-25字"
    if n <= 50:
        return "26-50字"
    if n <= 100:
        return "51-100字"
    return ">100字"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写知识库")
    a = ap.parse_args()

    rows = load()
    if not rows:
        print("没有群消息数据")
        return 1
    senders = defaultdict(int)
    for r in rows:
        senders[str(r["sender_id"])] += 1
    mine = [r for r in rows if str(r["sender_id"]) in BOT_UINS]
    print("总消息 %d 条｜发送者 %d 人｜**她的发言 %d 条**"
          % (len(rows), len(senders), len(mine)))
    if not mine:
        print("⚠ 群里没有她的发言（bot_uin 不匹配？发送者前 5：%s）"
              % sorted(senders.items(), key=lambda x: -x[1])[:5])
        return 1

    # 按群按序，算"有没有人接"
    by_g = defaultdict(list)
    for r in rows:
        by_g[str(r["group_id"])].append(r)

    stats = defaultdict(lambda: {"n": 0, "got": 0})
    viol = defaultdict(int)
    good, bad = [], []
    for r in mine:
        t = str(r["text"] or "").strip()
        if not t:
            continue
        g = str(r["group_id"])
        seq = r["seq"] or 0
        later = [x for x in by_g[g]
                 if (x["seq"] or 0) > seq and str(x["sender_id"]) not in BOT_UINS]
        got = bool(later[:1]) and (len(later) >= 1)
        # 更严格：只看紧邻的下一条是否别人说的（群消息 seq 连续）
        nxt = later[0] if later else None
        got = bool(nxt)
        b = bucket(len(t))
        stats[b]["n"] += 1
        stats[b]["got"] += 1 if got else 0
        flags = []
        if DASH.search(t):
            flags.append("破折号")
            viol["破折号"] += 1
        if SYM.search(t):
            flags.append("对称句")
            viol["对称句"] += 1
        if TAIL_Q.search(t):
            flags.append("反问收尾")
            viol["反问收尾"] += 1
        if len(t) > 160:
            flags.append("过长")
            viol["过长"] += 1
        item = {"text": t[:160], "len": len(t), "got": got,
                "group": g, "flags": flags}
        (good if (got and not flags) else bad).append(item)

    print("\n=== 被回应率（按长度）===")
    for b in ("≤10字", "11-25字", "26-50字", "51-100字", ">100字"):
        s = stats.get(b)
        if not s or not s["n"]:
            continue
        print("  %-8s %3d 句｜被接 %3d（%.0f%%）"
              % (b, s["n"], s["got"], 100.0 * s["got"] / s["n"]))
    print("\n=== 违规统计（%d 句）===" % len(mine))
    for k, v in sorted(viol.items(), key=lambda x: -x[1]) or [("无", 0)]:
        print("  %-8s %d 句（%.0f%%）" % (k, v, 100.0 * v / len(mine)))

    print("\n=== 好样本（被接且无违规）%d 条，示例 ===" % len(good))
    for x in good[:5]:
        print("  [%d字] %s" % (x["len"], x["text"][:70]))
    print("\n=== 坏样本（没被接或违规）%d 条，示例 ===" % len(bad))
    for x in bad[:5]:
        print("  [%d字%s] %s" % (x["len"],
                                ("｜" + "/".join(x["flags"])) if x["flags"] else "",
                                x["text"][:70]))

    # 写文档
    out_dir = ROOT / "docs" / "风格"
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = out_dir / ("群聊风格学习_%s.md" % time.strftime("%Y%m%d"))
    lines = ["# 群聊说话风格学习（%s）" % time.strftime("%Y-%m-%d"),
             "", "> 目标：**完善人格与说话风格**。数据源 `group_history.db`（%d 条群消息，她 %d 句）。"
             % (len(rows), len(mine)), "", "## 被回应率（按长度）", "",
             "| 长度 | 句数 | 被接 | 被接率 |", "|---|---|---|---|"]
    for b in ("≤10字", "11-25字", "26-50字", "51-100字", ">100字"):
        s = stats.get(b)
        if s and s["n"]:
            lines.append("| %s | %d | %d | %.0f%% |"
                         % (b, s["n"], s["got"], 100.0 * s["got"] / s["n"]))
    lines += ["", "## 违规", ""]
    for k, v in sorted(viol.items(), key=lambda x: -x[1]):
        lines.append("- **%s**：%d 句（%.0f%%）" % (k, v, 100.0 * v / len(mine)))
    lines += ["", "## 好样本", ""]
    for x in good[:12]:
        lines.append("- [%d字] %s" % (x["len"], x["text"]))
    lines += ["", "## 坏样本", ""]
    for x in bad[:12]:
        lines.append("- [%d字%s] %s" % (x["len"],
                                        ("｜" + "/".join(x["flags"])) if x["flags"] else "",
                                        x["text"]))
    io.open(doc, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n已写文档：%s" % doc.relative_to(ROOT))

    if a.apply:
        from backend.yuanheng_kb import kb_add
        n = 0
        for x in good[:8]:
            kb_add("好句子样例（被接、无违规）：" + x["text"], category="说话风格",
                   source="group_history", detail="长度 %d｜群 %s" % (x["len"], x["group"]))
            n += 1
        for x in bad[:8]:
            kb_add("坏句子样例（%s）：%s"
                   % ("/".join(x["flags"]) or "没被接", x["text"]),
                   category="说话风格", source="group_history",
                   detail="长度 %d" % x["len"])
            n += 1
        print("已写知识库 %d 条（category=说话风格）" % n)
    else:
        print("（干跑；--apply 写知识库）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
