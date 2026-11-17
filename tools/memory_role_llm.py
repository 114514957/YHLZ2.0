# -*- coding: utf-8 -*-
"""用模型给 unknown 记忆分类（第 1 件）。

为什么要模型：`memory_roles.classify()` 是关键词规则，467 条（43%）落在"规则未覆盖"。
这些条目现在**不进注入**（安全），但也白白浪费——里面可能有他/她真正重要的记忆。

分类口径（与 memory_roles 一致）：
  her          她自己说过的、有内容的原话
  owner        关于老爹的稳定事实/偏好/约定
  engineering  工程/开发/调试流水账（不该进人格注入）
  other        群友的话、闲聊碎片、无信息

做法：每批 8 条，要求模型只回 JSON；逐条校验后写库。带 `--dry` 只跑一批看质量。

用法：
    python tools\\memory_role_llm.py --dry      # 跑一批看效果（不改库）
    python tools\\memory_role_llm.py --apply    # 全量分类写库
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

DB = os.path.join(ROOT, "cache", "memstore", "memstore.db")
LABELS = ("her", "owner", "engineering", "other")

SYS = ("你是记忆分类器。给你若干条记忆摘要，判断每条属于哪一类，"
       "只输出 JSON，不要解释。类别：\n"
       "her=元亨自己说过的、有内容的原话；\n"
       "owner=关于老爹的稳定事实/偏好/约定/经历；\n"
       "engineering=工程开发调试流水账（代码/端口/评测/部署等）；\n"
       "other=群友闲聊、碎片、无信息量。\n"
       '输出格式：{"items":[{"id":"...","label":"her|owner|engineering|other"}]}')


def load_unknown(limit: int = 0) -> list[dict]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    q = ("select id, summary, source from l2_items "
         "where (role is null or role='' or role='unknown') and status='active' "
         "order by importance desc, created_at desc")
    if limit:
        q += " limit %d" % limit
    rows = [dict(r) for r in con.execute(q)]
    con.close()
    return rows


def classify_batch(items: list[dict]) -> dict[str, str]:
    from backend.llm_router import chat

    payload = [{"id": d["id"], "text": str(d["summary"])[:180],
                "src": str(d["source"])[:30]} for d in items]
    msgs = [{"role": "system", "content": SYS},
            {"role": "user", "content": json.dumps({"items": payload},
                                                   ensure_ascii=False)}]
    # llm_router.chat 返回 {"content": ..., ...}
    out = chat(msgs, temperature=0.0, max_tokens=800, channel="role_classify")
    txt = ""
    try:
        txt = str(out["choices"][0]["message"]["content"] or "")
    except Exception:  # noqa: BLE001
        txt = str((out or {}).get("content") or "")
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        d = json.loads(txt[i:j + 1])
    except Exception:  # noqa: BLE001
        return {}
    res = {}
    for it in d.get("items") or []:
        iid = str(it.get("id") or "")
        lab = str(it.get("label") or "").strip().lower()
        if iid and lab in LABELS:
            res[iid] = lab
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rows = load_unknown(0 if a.apply else a.batch)
    print("待分类 %d 条" % len(rows))
    if not rows:
        return 0

    done: dict[str, str] = {}
    t0 = time.time()
    for i in range(0, len(rows), a.batch):
        chunk = rows[i:i + a.batch]
        try:
            got = classify_batch(chunk)
        except Exception as e:  # noqa: BLE001
            print("  批次 %d 失败：%s" % (i // a.batch + 1, type(e).__name__))
            continue
        done.update(got)
        if a.dry or not a.apply:
            for d in chunk:
                print("  %-9s %s" % (done.get(d["id"], "?"),
                                     str(d["summary"])[:70]))

    print("\n共判出 %d/%d 条｜用时 %.1fs" % (len(done), len(rows), time.time() - t0))
    from collections import Counter
    print("分布：", dict(Counter(done.values())))

    if a.dry or not a.apply:
        print("\n（试跑；加 --apply 写库）")
        return 0

    con = sqlite3.connect(DB)
    con.executemany("update l2_items set role=? where id=?",
                    [(v, k) for k, v in done.items()])
    con.commit()
    dist = {r[0]: r[1] for r in con.execute(
        "select role, count(*) from l2_items group by role")}
    con.close()
    print("写库完成，当前分布：", dist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
