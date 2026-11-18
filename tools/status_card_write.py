# -*- coding: utf-8 -*-
"""生成工作台「运行态」卡的静态 JSON（assets/status_card.json）。

为什么不走 /api：本轮实测 daemon 侧 `_ui_route` 对 `/api/*` 不生效，
请求统一被代理到 8090（FastAPI）后 404。与其在这条路上继续耗，
不如把聚合结果写成静态文件——工作台与 assets/webui/index.html 同源，直接 fetch 即可。
文件由哨兵流程每分钟/每小时刷新（见 chain_sentinel 的收尾调用）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(ROOT, "assets", "webui", "status_card.json")


def kg() -> dict | None:
    db = os.path.join(ROOT, "cache", "kg", "kg_v2.db")
    if not os.path.exists(db):
        return None
    c = sqlite3.connect(db, timeout=3)
    try:
        q = lambda s: c.execute(s).fetchone()[0]  # noqa: E731
        return {"docs": q("select count(*) from docs"),
                "entities": q("select count(*) from entities"),
                "relations": q("select count(*) from relations"),
                "episodes": q("select count(*) from episodes"),
                "profiles": q("select count(*) from profiles"),
                "with_emb": q("select count(*) from docs where emb is not null")}
    finally:
        c.close()


def jload(rel: str) -> dict | None:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def build() -> dict:
    return {"ok": True, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "kg": kg(),
            "recall": jload(os.path.join("cache", "eval", "recall_last.json")),
            "sentinel": jload(os.path.join("cache", "sustain", "sentinel.json"))}


def main() -> int:
    d = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print("written:", OUT)
    print("kg:", d["kg"])
    print("recall:", (d.get("recall") or {}).get("precision"),
          (d.get("recall") or {}).get("recall"))
    print("sentinel problems:", (d.get("sentinel") or {}).get("problems"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
