# -*- coding: utf-8 -*-
"""群聊学习作业（台账 1262）：把群里的「人和话题」沉淀成可查的知识。

老爹定调：**群聊才是学习的关键**。

产出（每条都带来源，可追溯、可复核）：
  1. **人物画像**：每个常说话的人 → 主要话题、发言量、@她次数、最近活跃
     → 存进知识库 `category="群人物"`（按群+人去重覆盖）
  2. **群话题**：近 7/30 天的高频话题 → `category="群话题"`
  3. **群观察**：人数/活跃比/停摆判断 → `category="群观察"`

为什么不直接塞进她的个人记忆（L2）：
  · 个人记忆是"她和老爹的事"；群里的数据是**外部世界的观察**，混进去会污染人格
    （今天审计过：L2 里已有约 70% 是工程流水账）。
  · 知识库有 category + source，可以按场景取用（群里用，私聊不一定用）。

用法：
    python tools/group_learn.py            # 干跑，打印将写入的内容
    python tools/group_learn.py --apply    # 真写知识库（同一条会覆盖更新）
"""
from __future__ import annotations

import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

from backend import qq_intel as QI  # noqa: E402

GROUPS = QI.GROUPS


def build() -> list[dict]:
    """把情报卡转成知识条目（人物/话题/观察）。"""
    out = []
    for c in QI.group_cards():
        gid = c["group_id"]
        gname = GROUPS.get(gid, gid)
        # 群观察
        alive = "活跃" if c["messages_recent_7d"] >= 30 else (
            "半停摆" if c["messages_recent_7d"] >= 5 else "基本停摆")
        out.append({
            "category": "群观察",
            "summary": "[群观察] %s(%s)：%d 人，常说话约 %d 人，共 %d 条；近7天 %d 条（%s）"
                       % (gname, gid, c["people"], c["active_people"],
                          c["messages"], c["messages_recent_7d"], alive),
            "detail": "话题：" + "/".join(c["topics"]),
            "source": "qq_intel:%s" % gid,
        })
        # 群话题
        if c["topics"]:
            out.append({
                "category": "群话题",
                "summary": "[群话题] %s 最近常聊：%s" % (gname, "、".join(c["topics"][:5])),
                "detail": "共 %d 条消息，近7天 %d 条" % (c["messages"], c["messages_recent_7d"]),
                "source": "qq_intel:%s" % gid,
            })
        # 人物画像
        for m in c["members"][:6]:
            if m["messages"] < 20:
                continue
            out.append({
                "category": "群人物",
                "summary": "[%s] %s：%d 条，@她 %d 次；常聊 %s"
                           % (gname, m["name"], m["messages"], m["with_her"],
                              "/".join(m["topics"][:3]) or "—"),
                "detail": "QQ %s｜最近活跃 %s 天前｜占群 %s%%"
                          % (m["qq"], m["days_ago"], m["share"]),
                "source": "qq_intel:%s:%s" % (gid, m["qq"]),
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    items = build()
    from collections import Counter

    print("将写入 %d 条：%s" % (len(items), dict(Counter(i["category"] for i in items))))
    for i in items[:6]:
        print("  [%s] %s" % (i["category"], i["summary"][:90]))
    if not a.apply:
        print("\n（干跑；加 --apply 写知识库）")
        return 0
    from backend.yuanheng_kb import kb_add

    ok = 0
    for i in items:
        try:
            kb_add(i["summary"], category=i["category"],
                   source=i["source"], detail=i["detail"])
            ok += 1
        except Exception as ex:  # noqa: BLE001
            print("  ! 写入失败 %s: %s" % (i["summary"][:30], type(ex).__name__))
    print("写入完成：%d/%d" % (ok, len(items)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
