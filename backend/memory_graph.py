# -*- coding: utf-8 -*-
"""记忆星图数据层（台账 1259·工作站第二片之三）。

老爹要「全部记忆」都要在星图里（1230）。这里出节点与边：
  节点 = l2_items（active），大小按 importance，颜色按 type，role 用形状区分
  边   = 共享关键词（每个节点跟最相近的 2 个连）；也把 qq_social_edges 的
         「谁常跟谁说话」并进来（有的话）

为了浏览器能跑，节点上限默认 400（当前总量 239，全部放得下）。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "cache" / "memstore" / "memstore.db"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_NONWORD = re.compile(r"[\s\W_]+")

__all__ = ["graph"]

TYPE_COLOR = {
    "preference": "#f39c12", "event": "#3498db", "fact": "#2ecc71",
    "knowledge": "#9b59b6", "context": "#95a5a6", "decision": "#e74c3c",
}
ROLE_SHAPE = {"her": "circle", "owner": "square", "engineering": "triangle",
              "unknown": "diamond"}


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB), timeout=2.0)
    con.row_factory = sqlite3.Row
    return con


def graph(limit: int = 400, min_importance: int = 0) -> dict:
    if not DB.exists():
        return {"nodes": [], "links": [], "stats": {}}
    con = _conn()
    try:
        rows = [dict(r) for r in con.execute(
            "select id,type,importance,summary,source,status,keywords from l2_items "
            "where status='active' order by importance desc, created_at desc limit ?",
            (limit,))]
    finally:
        con.close()
    try:
        from backend.memory_roles import classify
    except Exception:  # noqa: BLE001
        def classify(item):  # type: ignore
            return "unknown", ""

    nodes = []
    for r in rows:
        if int(r.get("importance") or 0) < min_importance:
            continue
        role, _ = classify(r)
        txt = " ".join(str(r.get("summary") or "").split())
        kws = [k.strip() for k in re.split(r"[,，、;；|/\s]+",
                                           str(r.get("keywords") or "")) if len(k.strip()) >= 2]
        nodes.append({"id": r["id"], "label": txt[:40], "text": txt[:400],
                      "type": str(r.get("type") or ""),
                      "role": role,
                      "imp": int(r.get("importance") or 0),
                      "color": TYPE_COLOR.get(str(r.get("type") or ""), "#7f8c8d"),
                      "shape": ROLE_SHAPE.get(role, "circle"),
                      "kw": kws[:6]})

    # 边：共享关键词（每节点最多连 2 条最强）；没有关键词的退化为文本 2-gram
    grams: dict[str, set[str]] = {}
    for n in nodes:
        s = _NONWORD.sub("", n["text"])
        grams[n["id"]] = {s[k:k + 2] for k in range(max(0, len(s) - 1))}

    links: dict[tuple[str, str], dict] = {}
    for a in nodes:
        best: list[tuple[int, dict]] = []
        for b in nodes:
            if b["id"] == a["id"]:
                continue
            shared = set(a["kw"]) & set(b["kw"])
            if shared:
                best.append((len(shared) * 2, b))
                continue
            common = len(grams[a["id"]] & grams[b["id"]])
            if common >= 6:
                best.append((common // 3, b))
        best.sort(key=lambda x: -x[0])
        for score, b in best[:2]:
            key = tuple(sorted([a["id"], b["id"]]))
            if key not in links:
                links[key] = {"source": key[0], "target": key[1], "w": score}

    types = {}
    roles = {}
    for n in nodes:
        types[n["type"]] = types.get(n["type"], 0) + 1
        roles[n["role"]] = roles.get(n["role"], 0) + 1
    return {"nodes": nodes, "links": list(links.values()),
            "stats": {"nodes": len(nodes), "links": len(links),
                      "types": types, "roles": roles,
                      "colors": TYPE_COLOR, "shapes": ROLE_SHAPE}}


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    g = graph()
    print(json.dumps(g["stats"], ensure_ascii=False, indent=1))
    print("边示例：", g["links"][:3])
    print("节点示例：", [{k: n[k] for k in ("id", "type", "role", "imp", "kw")}
                     for n in g["nodes"][:3]])
    print("JSON 大小：%.0f KB" % (len(json.dumps(g, ensure_ascii=False)) / 1024))
