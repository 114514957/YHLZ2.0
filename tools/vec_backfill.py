"""向量侧表维护 + FTS5↔embvec 一致性校验（台账 0226 / 0499）。

三种模式：
  python tools/vec_backfill.py --check        # 只读巡检：查漂移，不写盘（漂移则退出码 1）
  python tools/vec_backfill.py                # 补齐缺向量的 L2 条目（写）
  python tools/vec_backfill.py --query 想养成好习惯   # 顺便看一眼语义召回效果

表单口径（--check）：
  - 条目侧：非 archive 且有 summary 的 L2 条目是否都有向量（缺 → 语义召不到）
  - 索引侧：l2_items ↔ l2_fts 双向孤儿（FTS5 与事实表不一致 → 召回漏/假命中）
  - 向量侧：孤儿向量（条目已不在库/已 archive，白占空间）与维度损坏
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT))


def _items_and_fts(con: sqlite3.Connection) -> tuple[list[tuple], set, set]:
    items = con.execute(
        "SELECT id, keywords, summary, status FROM l2_items").fetchall()
    item_ids = {r[0] for r in items}
    try:
        fts_ids = {r[0] for r in con.execute("SELECT sid FROM l2_fts")}
    except Exception:
        fts_ids = set()
    return items, item_ids, fts_ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default=None)
    ap.add_argument("--check", action="store_true",
                    help="只读一致性巡检（不写盘；有漂移则退出码 1）")
    ap.add_argument("--prune", action="store_true",
                    help="清掉本库 scope 里**条目已不存在**的孤儿向量（显式才执行）")
    ap.add_argument("--sample", type=int, default=5, help="样例打印条数")
    a = ap.parse_args()

    from backend.vector_memory import DIM, MEMORY_DB, _conn, l2_scope

    if not MEMORY_DB.exists():
        print(f"记忆库不存在：{MEMORY_DB}")
        return 1
    con = sqlite3.connect(str(MEMORY_DB))
    try:
        items, item_ids, fts_ids = _items_and_fts(con)
    finally:
        con.close()

    scope = l2_scope(MEMORY_DB)  # 默认库 = "l2"
    vc = _conn()
    try:
        vec_rows = vc.execute(
            "SELECT id, vec FROM vec WHERE scope=?", (scope,)).fetchall()
        scopes = [r[0] for r in vc.execute(
            "SELECT DISTINCT scope FROM vec").fetchall()]
    finally:
        vc.close()
    have = {r[0] for r in vec_rows}
    dim_bad = sum(1 for _, b in vec_rows if len(b or b"") != DIM * 4)

    active = [r for r in items if r[2] and r[3] != "archive"]
    missing_vec = [r[0] for r in active if r[0] not in have]
    orphan_vec = sorted(have - item_ids)
    # Only recallable rows belong in FTS5; archive rows are excluded on purpose,
    # so comparing against *all* items produced a permanent false "drift" of 295.
    recallable = {r[0] for r in active}
    fts_missing = sorted(recallable - fts_ids)    # 参与召回的条目没进 FTS5
    fts_orphan = sorted(fts_ids - item_ids)       # FTS5 有、条目没了

    if a.check:
        drift = (len(missing_vec) + len(orphan_vec) + len(fts_missing)
                 + len(fts_orphan) + dim_bad)
        print("=== 一致性巡检（只读）===")
        print(f"记忆库 {MEMORY_DB}")
        print(f"L2 条目 {len(items)}（参与召回 {len(active)}）；"
              f"FTS5 行 {len(fts_ids)}；向量 {len(vec_rows)}（scope={scope}）")
        print(f"  缺向量 {len(missing_vec)}"
              f"{'  例: ' + ','.join(missing_vec[:a.sample]) if missing_vec else ''}")
        print(f"  孤儿向量 {len(orphan_vec)}"
              f"{'  例: ' + ','.join(orphan_vec[:a.sample]) if orphan_vec else ''}")
        print(f"  维度损坏 {dim_bad}")
        print(f"  FTS5 缺行 {len(fts_missing)}"
              f"{'  例: ' + ','.join(fts_missing[:a.sample]) if fts_missing else ''}")
        print(f"  FTS5 孤儿 {len(fts_orphan)}"
              f"{'  例: ' + ','.join(fts_orphan[:a.sample]) if fts_orphan else ''}")
        if len(scopes) > 1:
            print(f"  其它 scope（其它库的向量）：{sorted(set(scopes) - {scope})}")
        print("结论：" + ("一致" if drift == 0 else
                        f"发现 {drift} 处漂移 → 跑 `--backfill` 补齐（本巡检不改数据）"))
        return 0 if drift == 0 else 1

    # 补齐（写）：只补"参与召回但没向量"的条目
    todo = [r for r in active if r[0] not in have]
    if todo:
        from backend.vector_memory import embed

        texts = [f"{r[2]} {r[1]}".strip()[:256] for r in todo]
        vs = embed(texts)
        vc = _conn()
        try:
            for r, v in zip(todo, vs):
                vc.execute(
                    "INSERT OR REPLACE INTO vec(id,scope,vec) VALUES(?,?,?)",
                    (r[0], scope, v.tobytes()))
            vc.commit()
        finally:
            vc.close()
    print(f"vec {scope}: 参与召回 {len(active)} 条，新增 {len(todo)}"
          f"（已有 {len(have)}）", flush=True)

    if a.prune and orphan_vec:
        vc = _conn()
        try:
            vc.executemany("DELETE FROM vec WHERE id=? AND scope=?",
                           [(i, scope) for i in orphan_vec])
            vc.commit()
        finally:
            vc.close()
        print(f"已清理孤儿向量 {len(orphan_vec)} 条（条目已不在库里）", flush=True)

    if a.query:
        from backend.vector_memory import semantic_l2

        print(f"\n语义查询：{a.query}")
        for it in semantic_l2(a.query, top=6, db_path=MEMORY_DB):
            print(f"  [{it['score']}|{it['importance']}|{it['type']}|{it['date']}] "
                  f"{it['summary'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())