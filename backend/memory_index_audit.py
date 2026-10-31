"""Read-only and explicit rebuild checks for derived memory indexes.

SQLite ``l2_items`` is authoritative.  FTS5, the keyword catalog, and the
vector side table are disposable projections.  This module deliberately does
not construct a memory service or an embedding model: an audit is safe during
LLM fine-tuning and on an 8 GB GPU machine.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .target_kw_index import KeywordIndex


ACTIVE_STATUSES = ("active", "downgraded")


def _rows(db_path: Path) -> dict[str, dict[str, Any]]:
    con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, type, importance, summary, keywords, status "
            "FROM l2_items WHERE status IN ('active','downgraded')"
        ).fetchall()
        return {str(r["id"]): dict(r) for r in rows}
    finally:
        con.close()


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?",
        (name,),
    ).fetchone() is not None


def _fts_snapshot(db_path: Path) -> tuple[set[str], set[str]]:
    con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05)
    try:
        if not _table_exists(con, "l2_fts"):
            return set(), set()
        rows = con.execute("SELECT sid FROM l2_fts").fetchall()
        all_ids = [str(r[0]) for r in rows if r[0] is not None]
        return set(all_ids), {x for x in all_ids if all_ids.count(x) > 1}
    finally:
        con.close()


def _keyword_snapshot(kw_db_path: Path, source: str) -> tuple[set[str], set[str]]:
    if not Path(kw_db_path).is_file():
        return set(), set()
    con = sqlite3.connect(Path(kw_db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05)
    try:
        if not _table_exists(con, "kw_docs"):
            return set(), set()
        rows = con.execute("SELECT docid FROM kw_docs WHERE source=?", (source,)).fetchall()
        ids = [str(r[0]) for r in rows if r[0] is not None]
        return set(ids), {x for x in ids if ids.count(x) > 1}
    finally:
        con.close()


def _scope_for(db_path: Path) -> str:
    """Mirror vector_memory.l2_scope without importing numpy/torch."""
    project_root = Path(__file__).resolve().parent.parent
    default_db = project_root / "cache" / "memstore" / "memstore.db"
    try:
        if db_path.resolve() == default_db.resolve():
            return "l2"
    except Exception:
        pass
    stem = re.sub(r"[^\w\-]+", "_", db_path.stem)[:40] or "db"
    return "l2@" + stem


def _vector_snapshot(vec_db_path: Path, scope: str) -> tuple[set[str], set[str]]:
    if not Path(vec_db_path).is_file():
        return set(), set()
    con = sqlite3.connect(Path(vec_db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05)
    try:
        if not _table_exists(con, "vec"):
            return set(), set()
        rows = con.execute("SELECT id FROM vec WHERE scope=?", (scope,)).fetchall()
        ids = [str(r[0]) for r in rows if r[0] is not None]
        return set(ids), {x for x in ids if ids.count(x) > 1}
    finally:
        con.close()


def _diff(expected: set[str], actual: set[str]) -> dict[str, list[str]]:
    return {
        "missing": sorted(expected - actual),
        "stale": sorted(actual - expected),
    }


def audit(
    db_path: Path,
    *,
    kw_db_path: Path | None = None,
    vec_db_path: Path | None = None,
    scope: str | None = None,
    keyword_source: str = "l2",
) -> dict[str, Any]:
    """Compare all disposable projections with active/downgraded L2 rows.

    The function is read-only and never imports ``transformers`` or starts a
    service.  Archived/cold items are intentionally not expected in recall
    indexes; their presence is reported as stale rather than deleted.
    """
    db_path = Path(db_path)
    authoritative = _rows(db_path)
    expected = set(authoritative)
    fts_ids, fts_dupes = _fts_snapshot(db_path)
    out: dict[str, Any] = {
        "db_path": str(db_path.resolve()),
        "authoritative": len(expected),
        "expected_statuses": list(ACTIVE_STATUSES),
        "fts": {**_diff(expected, fts_ids), "duplicates": sorted(fts_dupes)},
    }
    if kw_db_path is not None:
        kw_ids, kw_dupes = _keyword_snapshot(Path(kw_db_path), keyword_source)
        out["keyword"] = {
            **_diff(expected, kw_ids),
            "duplicates": sorted(kw_dupes),
            "db_path": str(Path(kw_db_path).resolve()),
            "source": keyword_source,
        }
    if vec_db_path is not None:
        if scope is None:
            scope = _scope_for(db_path)
        vec_ids, vec_dupes = _vector_snapshot(Path(vec_db_path), scope)
        out["vector"] = {
            **_diff(expected, vec_ids),
            "duplicates": sorted(vec_dupes),
            "db_path": str(Path(vec_db_path).resolve()),
            "scope": scope,
        }
    out["missing_files"] = [str(Path(p).resolve()) for p in (kw_db_path, vec_db_path)
                            if p is not None and not Path(p).is_file()]
    out["ok"] = not out["missing_files"] and all(
        not part["missing"] and not part["stale"] and not part["duplicates"]
        for name, part in out.items()
        if name in ("fts", "keyword", "vector")
    )
    return out


def rebuild_fts(db_path: Path) -> dict[str, Any]:
    """Atomically rebuild the FTS projection from active/downgraded L2 rows."""
    db_path = Path(db_path)
    rows = _rows(db_path)
    con = sqlite3.connect(str(db_path), timeout=10)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS l2_fts USING fts5(sid, keywords, summary)")
        con.execute("DELETE FROM l2_fts")
        con.executemany(
            "INSERT INTO l2_fts(sid,keywords,summary) VALUES (?,?,?)",
            [(iid, str(r.get("keywords") or ""), str(r.get("summary") or ""))
             for iid, r in rows.items()],
        )
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()
    return audit(db_path)


def rebuild_keyword(
    db_path: Path,
    *,
    kw_db_path: Path,
    keyword_source: str = "l2",
    clear_source: bool = False,
) -> dict[str, Any]:
    """Rebuild the keyword projection.

    ``clear_source`` is explicit because the project historically shares one
    keyword DB between L2 stores.  The safe default only upserts this store;
    operators may clear the source during a planned single-store rebuild.
    """
    rows = _rows(Path(db_path))
    kw = KeywordIndex(Path(kw_db_path))
    docs = [
        {"docid": iid, "source": keyword_source, "summary": r["summary"],
         "record_title": f"L2-{r['type']}", "importance": r["importance"],
         "status": r["status"]}
        for iid, r in rows.items()
    ]
    kw.bulk_upsert_docs(docs, clear_source=keyword_source if clear_source else None)
    return audit(Path(db_path), kw_db_path=Path(kw_db_path), keyword_source=keyword_source)


def rebuild_vector(
    db_path: Path,
    *,
    vec_db_path: Path,
    allow_model: bool = False,
    scope: str | None = None,
) -> dict[str, Any]:
    """Rebuild vectors only when an operator explicitly permits model loading."""
    db_path = Path(db_path)
    vec_db_path = Path(vec_db_path)
    if scope is None:
        scope = _scope_for(db_path)
    if not allow_model:
        report = audit(db_path, vec_db_path=vec_db_path, scope=scope)
        report["vector_rebuild"] = {"attempted": False, "reason": "model_not_allowed"}
        return report
    from .vector_memory import embed
    rows = _rows(db_path)
    texts = [f"{r['summary']} {r['keywords']}".strip()[:256] for r in rows.values()]
    vectors = embed(texts)
    vec_db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(vec_db_path), timeout=10)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS vec(id TEXT NOT NULL, scope TEXT NOT NULL, vec BLOB NOT NULL, text TEXT, PRIMARY KEY(id,scope))")
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM vec WHERE scope=?", (scope,))
        con.executemany(
            "INSERT OR REPLACE INTO vec(id,scope,vec,text) VALUES (?,?,?,?)",
            [(iid, scope, v.tobytes(), texts[i]) for i, (iid, _) in enumerate(rows.items())],
        )
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()
    report = audit(db_path, vec_db_path=vec_db_path, scope=scope)
    report["vector_rebuild"] = {"attempted": True, "count": len(rows)}
    return report


def prune_vector_stale(
    db_path: Path,
    *,
    vec_db_path: Path,
    scope: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Remove only stale vector rows without loading an embedding model.

    L2 remains authoritative: rows for archived/cold/removed items are
    disposable projection residue. The default is a dry run; ``apply=True``
    performs a scoped transactional delete and never touches active L2 rows.
    """
    db_path = Path(db_path)
    vec_db_path = Path(vec_db_path)
    scope = scope or _scope_for(db_path)
    expected = set(_rows(db_path))
    actual, duplicates = _vector_snapshot(vec_db_path, scope)
    stale = sorted(actual - expected)
    result: dict[str, Any] = {
        "db_path": str(db_path.resolve()),
        "vec_db_path": str(vec_db_path.resolve()),
        "scope": scope,
        "apply": bool(apply),
        "stale_before": stale,
        "duplicates_before": sorted(duplicates),
        "deleted": 0,
        "model_loaded": False,
    }
    if apply and stale:
        con = sqlite3.connect(str(vec_db_path), timeout=10)
        try:
            con.execute("BEGIN IMMEDIATE")
            con.executemany("DELETE FROM vec WHERE scope=? AND id=?",
                            [(scope, iid) for iid in stale])
            result["deleted"] = len(stale)
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()
    after_ids, after_dupes = _vector_snapshot(vec_db_path, scope)
    result["stale_after"] = sorted(after_ids - expected)
    result["duplicates_after"] = sorted(after_dupes)
    result["ok"] = not result["stale_after"] and not result["duplicates_after"]
    return result


def dumps(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
