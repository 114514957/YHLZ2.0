"""Yuanheng KB: standalone knowledge store for objectively useful knowledge.

Boundary (user decision, ledger 0179):
- KB (this file)  = what Yuanheng LEARNED that is useful: tech points, methods,
  world knowledge. Written by capture pipeline (QQ) and by Yuanheng itself.
- Memory (memstore) = who Yuanheng is / experience / relations with the owner.
Separate stores on purpose so consolidation never melts knowledge into persona.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KB_DB = _PROJECT_ROOT / "data" / "yuanheng_kb.db"

VALID_CATEGORIES = {"tech", "method", "idea", "fact", "skill", "resource"}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_items (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kb_fts (
    sid TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    category TEXT NOT NULL
);
"""
_lock = threading.RLock()


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(str(DEFAULT_KB_DB))
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _init() -> None:
    DEFAULT_KB_DB.parent.mkdir(parents=True, exist_ok=True)
    with _lock, _db() as con:
        con.executescript(_SCHEMA)
        con.commit()


def _norm(text: str) -> str:
    return re.sub(r"[\s\u3000,，。.!！?？:：;；、\-\[\]\(\)]+", "", str(text or ""))


def kb_add(summary: str, category: str = "tech", source: str = "",
           detail: str = "", created_at: float = 0.0) -> str:
    """Add one knowledge item (dedup on normalized summary)."""
    _init()
    text = str(summary or "").strip()
    cat = str(category or "tech").strip()[:12]
    if cat not in VALID_CATEGORIES:
        cat = "tech"
    if len(text) < 8 or len(text) > 400:
        return "要点需在 8-400 字之间"
    norm = _norm(text)
    stamp = float(created_at or time.time())
    with _lock, _db() as con:
        row = con.execute(
            "SELECT id, summary FROM kb_items WHERE status='active'"
        ).fetchall()
        for iid, s in row:
            if _norm(s) == norm:
                con.execute("UPDATE kb_items SET updated=? WHERE id=?",
                            (time.time(), iid))
                return f"重复条目已存在（{iid}），刷新时间"
        from difflib import SequenceMatcher

        for iid, s in row:
            if SequenceMatcher(None, _norm(s), norm).ratio() >= 0.85:
                return f"近似条目已存在（{iid}），未重复添加"
        iid = "kb_" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]
        now = time.time()
        con.execute(
            "INSERT INTO kb_items(id,category,summary,detail,source,status,created,updated)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (iid, cat, text[:400], str(detail or "")[:2000],
             str(source or "")[:120], "active", stamp, now),
        )
        con.execute(
            "INSERT OR REPLACE INTO kb_fts(sid,summary,category) VALUES(?,?,?)",
            (iid, text[:400], cat),
        )
        con.commit()
    return f"已入库：{iid} [{cat}]"


def kb_query(query: str, limit: int = 6, category: str = "") -> list[dict]:
    """FTS5-ranked query (fallback LIKE), newest first on ties."""
    _init()
    q = str(query or "").strip()
    if not q:
        return []
    limit = max(1, min(int(limit or 6), 30))
    with _lock, _db() as con:
        try:
            hits = con.execute(
                "SELECT sid, bm25(kb_fts) AS score FROM kb_fts "
                "WHERE kb_fts MATCH ? ORDER BY score LIMIT ?",
                ("\"" + q.replace('"', "") + "\"", int(limit) * 3),
            ).fetchall()
            ids = [h[0] for h in hits]
        except Exception:
            ids = []
        if not ids:
            # word-wise AND fallback (space-separated tokens)
            tokens = [w for w in re.split(r"[\s,，。.!！?？:：]+", q) if w]
            if not tokens:
                tokens = [q]
            conds = " AND ".join(["summary LIKE ?"] * len(tokens))
            args = [f"%{w}%" for w in tokens] + [int(limit)]
            rows = con.execute(
                f"SELECT id FROM kb_items WHERE status='active' "
                f"AND {conds} ORDER BY created DESC LIMIT ?",
                args,
            ).fetchall()
            ids = [r[0] for r in rows]
        out = []
        for iid in ids[:limit]:
            r = con.execute(
                "SELECT id,category,summary,detail,source,created FROM kb_items "
                "WHERE id=? AND status='active'", (iid,),
            ).fetchone()
            if r is None:
                continue
            out.append({
                "id": r[0], "category": r[1], "summary": r[2],
                "detail": r[3] or "", "source": r[4], "created": r[5],
            })
    return out


def kb_list(category: str = "", limit: int = 50) -> list[dict]:
    """List active items (optionally by category), newest first."""
    _init()
    limit = max(1, min(int(limit or 50), 200))
    with _lock, _db() as con:
        if category:
            rows = con.execute(
                "SELECT id,category,summary,detail,source,created FROM kb_items "
                "WHERE status='active' AND category=? ORDER BY created DESC LIMIT ?",
                (str(category)[:12], int(limit)),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id,category,summary,detail,source,created FROM kb_items "
                "WHERE status='active' ORDER BY created DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
    return [{"id": r[0], "category": r[1], "summary": r[2], "detail": r[3] or "",
             "source": r[4], "created": r[5]} for r in rows]


def kb_stats() -> dict:
    _init()
    with _lock, _db() as con:
        total = con.execute(
            "SELECT COUNT(*) FROM kb_items WHERE status='active'").fetchone()[0]
        cats = con.execute(
            "SELECT category, COUNT(*) FROM kb_items WHERE status='active' "
            "GROUP BY category").fetchall()
    return {"items": total, "by_category": {c: n for c, n in cats},
            "db": str(DEFAULT_KB_DB)}


def kb_migrate_from_l2() -> int:
    """One-shot: import existing L2 type=knowledge items into the KB and
    archive them in L2 (knowledge leaves the persona memory pool)."""
    import sqlite3 as _s

    from backend.target_memory import DEFAULT_DB, TargetMemoryService

    con = _s.connect(str(DEFAULT_DB))
    rows = con.execute(
        "SELECT id, summary, evidence_ref, created_at FROM l2_items "
        "WHERE type='knowledge' AND status IN ('active','downgraded')"
    ).fetchall()
    con.close()
    n = 0
    import re as _re

    for iid, summary, ev, created in rows:
        m = _re.match(r"\[QQ(\w+)\] (.*)", summary)
        cat = m.group(1).lower() if m else "tech"
        if cat not in VALID_CATEGORIES:
            cat = "tech"
        body = m.group(2) if m else summary
        res = kb_add(body, category=cat,
                     source=ev or f"migrate:{iid}",
                     created_at=float(created or 0))
        if res.startswith("已入库"):
            n += 1
    # archive knowledge in L2 (memory pool keeps only persona/experience)
    svc = TargetMemoryService()
    con = _s.connect(str(DEFAULT_DB))
    con.execute("UPDATE l2_items SET status='archive' WHERE type='knowledge'")
    con.commit()
    con.close()
    return n
