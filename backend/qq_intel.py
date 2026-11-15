# -*- coding: utf-8 -*-
"""群情报卡（台账 1253）：把"87 个人"压成"十来个真正在说话的人"。

老爹的原话：**群里很多人，但实际没多少人活跃，可以做精简情报卡。**

数据源（都在 `cache/memstore/memstore.db`）：
  qq_social_people(87)  每人每群：消息数、首次/最近活跃
  qq_social_events(4716) 每条消息的摘要（用来抽话题）
  qq_social_edges(260)   @ / 回复 关系（用来算"跟元亨互动"）

两种输出：
  `group_cards()`  → 结构化（给工作台）
  `card_text()`    → 一段话 ≤300 字（给她的上下文注入）
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path

__all__ = ["group_cards", "card_text", "GROUPS", "ACTIVE_MIN_MSGS"]

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "cache" / "memstore" / "memstore.db"
ACTIVE_MIN_MSGS = 20          # 消息数 ≥ 这个才算"活跃"
TOP_N = 6
STOP = set("""的 了 是 我 你 他 她 它 们 这 那 有 没有 不 就 也 都 还 在 和 与 吧 啊 呢 吗 呀 哦 嗯
一个 什么 怎么 可以 我们 你们 他们 但是 所以 因为 然后 现在 时候 自己 知道 觉得 感觉 一下 出来
谢谢 哈哈 爸爸 妈妈 不是 这个 那个 就是 真的 可能 应该 已经 还是 感觉 确实 意思 问题 东西 时间
事情 地方 一样 一直 其实 当然 而且 或者 如果 虽然 这种 那种 这样 那样 之前 之后 今天 明天 昨天 还有 的话 看着 有点 不要 不会 需要 说的 群里 也好 之类 什么的 就是 有点 一会 不能 可能""".split())
_NONWORD = re.compile(r"[\s\W_]+")
_CN = re.compile(r"^[\u4e00-\u9fa5]{2,4}$")


def _conn():
    """打开 memstore（只读查询用）。"""
    con = sqlite3.connect(str(DB), timeout=2.0)
    con.row_factory = sqlite3.Row
    return con


def _kw(texts: list[str], k: int = 3) -> list[str]:
    """话题词：**优先 jieba 分词**（未被分词的中文 n-gram 全是"我也/我这"这类垃圾），
    jieba 不可用时退回 n-gram。只收中文、≥2 字、非停用词、频次 ≥3。"""
    cnt: Counter[str] = Counter()
    try:
        import jieba
        for t in texts:
            for w in jieba.cut(_NONWORD.sub("", str(t or ""))):
                w = w.strip()
                if not _CN.match(w) or w in STOP:
                    continue
                cnt[w] += 1
    except Exception:  # noqa: BLE001
        for t in texts:
            s = _NONWORD.sub("", str(t or ""))
            for n in (2, 3, 4):
                for i in range(len(s) - n + 1):
                    g = s[i:i + n]
                    if not _CN.match(g) or g in STOP:
                        continue
                    cnt[g] += 1
    out: list[str] = []
    for g, c in cnt.most_common(80):
        if c < 3:
            break
        if any(g in s or s in g for s in out):
            continue
        out.append(g)
        if len(out) >= k:
            break
    return out


def group_cards(*, top_n: int = TOP_N) -> list[dict]:
    """每个群一张卡：人数、活跃数、Top 成员、话题。"""
    if not DB.exists():
        return []
    con = _conn()
    try:
        people = [dict(r) for r in con.execute(
            "select * from qq_social_people")]
        events = [dict(r) for r in con.execute(
            "select group_id, sender, summary, at from qq_social_events")]
        edges = [dict(r) for r in con.execute(
            "select group_id, sender, target, kind from qq_social_edges")]
    finally:
        con.close()

    by_group: dict[str, list[dict]] = {}
    for p in people:
        by_group.setdefault(str(p["group_id"]), []).append(p)
    ev_by_group: dict[str, list[dict]] = {}
    for e in events:
        ev_by_group.setdefault(str(e["group_id"]), []).append(e)

    now = time.time()
    cards = []
    for gid, ps in by_group.items():
        ps.sort(key=lambda p: -(p.get("messages") or 0))
        total_msgs = sum(int(p.get("messages") or 0) for p in ps)
        active = [p for p in ps if int(p.get("messages") or 0) >= ACTIVE_MIN_MSGS]
        evs = ev_by_group.get(gid, [])
        sender_ev: dict[str, list[dict]] = {}
        for e in evs:
            sender_ev.setdefault(str(e["sender"]), []).append(e)
        members = []
        for p in ps[:top_n]:
            qq = str(p["qq"])
            ev = sender_ev.get(qq, [])
            recent = max((e["at"] or 0) for e in ev) if ev else (p.get("last_seen") or 0)
            talk_with_me = sum(1 for e in edges
                               if str(e["group_id"]) == gid and qq in (str(e["sender"]), str(e["target"])))
            members.append({
                "qq": qq,
                "name": str(p.get("name") or qq)[:18],
                "messages": int(p.get("messages") or 0),
                "share": round(100.0 * int(p.get("messages") or 0) / max(1, total_msgs), 1),
                "days_ago": round((now - float(recent)) / 86400.0, 1) if recent else None,
                "with_her": talk_with_me,
                "topics": _kw([e["summary"] for e in ev], 3),
            })
        cards.append({
            "group_id": gid,
            "people": len(ps),
            "active_people": len(active),
            "messages": total_msgs,
            "messages_recent_7d": sum(1 for e in evs if (e["at"] or 0) > now - 7 * 86400),
            "topics": _kw([e["summary"] for e in evs], 5),
            "members": members,
        })
    cards.sort(key=lambda c: -c["messages"])
    return cards


def card_text(group_id: str, *, max_people: int = 5) -> str:
    """一段可直接注入上下文的话（≤300 字）。没有数据返回空串。"""
    for c in group_cards(top_n=max_people):
        if c["group_id"] != str(group_id):
            continue
        tops = "；".join(
            "%s(%s条%s)" % (m["name"], m["messages"],
                            "，" + "/".join(m["topics"][:2]) if m["topics"] else "")
            for m in c["members"][:max_people])
        return ("（本群情报：%d 人，常说话的约 %d 人，共 %d 条；近 7 天 %d 条。"
                "常聊：%s。主要说话的人：%s）"
                % (c["people"], c["active_people"], c["messages"],
                   c["messages_recent_7d"], "/".join(c["topics"][:3]) or "—", tops))[:300]
    return ""


GROUPS = {"1094579571": "小寻虚拟主播交流群", "1121723665": "AI对话",
          "855372167": "AI相关工程开发交流群"}

if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cards = group_cards()
    for c in cards:
        print("=" * 72)
        print("群 %s（%s）｜%d 人 / 活跃 %d / %d 条 / 近7天 %d"
              % (c["group_id"], GROUPS.get(c["group_id"], "?"), c["people"],
                 c["active_people"], c["messages"], c["messages_recent_7d"]))
        print("  话题：%s" % "、".join(c["topics"]))
        for m in c["members"]:
            print("   · %-18s %5d 条(%4.1f%%)  %s天前  @她%d次  %s"
                  % (m["name"], m["messages"], m["share"],
                     m["days_ago"] if m["days_ago"] is not None else "?",
                     m["with_her"], "/".join(m["topics"])))
        print("\n  注入文本：%s" % json.dumps(card_text(c["group_id"]), ensure_ascii=False))
