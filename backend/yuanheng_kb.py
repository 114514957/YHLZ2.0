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
    updated REAL NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    quality INTEGER NOT NULL DEFAULT 0
);
"""

_COLUMN_ADD = [
    ("uses", "INTEGER NOT NULL DEFAULT 0"),
    ("quality", "INTEGER NOT NULL DEFAULT 0"),
]
_lock = threading.RLock()


def _migrate(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(kb_items)").fetchall()}
    for name, decl in _COLUMN_ADD:
        if name not in cols:
            con.execute(f"ALTER TABLE kb_items ADD COLUMN {name} {decl}")


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(str(DEFAULT_KB_DB))
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _ensure_fts(con: sqlite3.Connection) -> None:
    """kb_fts must be a real FTS5 table (trigram tokenizer for Chinese).
    A legacy PLAIN table makes bm25() throw and silently degrades every query
    to LIKE (ledger 0302) — drop it and rebuild from kb_items."""
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE name='kb_fts'").fetchone()
    if row and row[0] and "using fts5" in str(row[0]).lower():
        return
    con.execute("DROP TABLE IF EXISTS kb_fts")
    try:
        con.execute("CREATE VIRTUAL TABLE kb_fts USING fts5("
                    "sid UNINDEXED, summary, category, tokenize='trigram')")
    except sqlite3.OperationalError:
        con.execute("CREATE VIRTUAL TABLE kb_fts USING fts5("
                    "sid UNINDEXED, summary, category)")
    con.execute("INSERT INTO kb_fts(sid, summary, category) "
                "SELECT id, summary, category FROM kb_items")


def _init() -> None:
    DEFAULT_KB_DB.parent.mkdir(parents=True, exist_ok=True)
    with _lock, _db() as con:
        con.executescript(_SCHEMA)
        _migrate(con)
        _ensure_fts(con)
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
        con.execute("DELETE FROM kb_fts WHERE sid=?", (iid,))
        con.execute(
            "INSERT INTO kb_fts(sid,summary,category) VALUES(?,?,?)",
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
            # word-wise AND fallback (space-separated tokens), escaped
            tokens = [w for w in re.split(r"[\s,，。.!！?？:：]+", q) if w]
            if not tokens:
                tokens = [q]

            def _esc(w: str) -> str:
                return (str(w).replace("\\", "\\\\")
                        .replace("%", "\\%").replace("_", "\\_"))

            conds = " AND ".join(["summary LIKE ? ESCAPE '\\'"] * len(tokens))
            args = [f"%{_esc(w)}%" for w in tokens] + [int(limit)]
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


def kb_inject(text: str, k: int = 3, public: bool = False,
              max_chars: int = 480) -> str:
    """Build a compact, relevance-gated "related knowledge" block for the
    prompt (ledger 0302). Public/group channels only get a safe subset
    (tech/method/resource/skill, no self-reflection/personal sources)."""
    q = str(text or "").strip()
    if len(q) < 4:
        return ""
    rows = kb_query(q, limit=max(2, int(k) * 2))
    if not rows:
        return ""
    safe_cats = {"tech", "method", "resource", "skill"}
    private_src = ("自主", "用户对话", "self", "对话反馈", "对话")
    out: list[str] = []
    used = 0
    for it in rows:
        if public:
            if it.get("category") not in safe_cats:
                continue
            if any(x in str(it.get("source", "")) for x in private_src):
                continue
        line = "· " + str(it.get("summary", ""))[:120]
        if used + len(line) > int(max_chars):
            break
        out.append(line)
        used += len(line)
        try:
            kb_note_hit(it.get("id", ""))
        except Exception:
            pass
        if len(out) >= int(k):
            break
    if not out:
        return ""
    return ("（你积累过的相关知识，仅供你参考；相关就用、不相关就忽略，"
            "**不要罗列**）：\n" + "\n".join(out))


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


def kb_note_hit(item_id: str) -> None:
    """B2 (ledger 0193): count a real use of a KB item (skills)."""
    _init()
    with _lock, _db() as con:
        con.execute("UPDATE kb_items SET uses=uses+1, updated=? WHERE id=?",
                    (time.time(), item_id))
        con.commit()


def kb_feedback(item_id: str, good: bool) -> str:
    """B3 (ledger 0193): owner feedback on a skill/item. good=True rewards,
    good=False flags the item for review (quality may go negative)."""
    _init()
    delta = 1 if good else -1
    with _lock, _db() as con:
        row = con.execute("SELECT id, summary FROM kb_items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return f"条目不存在：{item_id}"
        con.execute("UPDATE kb_items SET quality=quality+?, updated=? WHERE id=?",
                    (delta, time.time(), item_id))
        con.commit()
    return f"已记录{'正向' if good else '负向'}反馈（quality{'+' if good else ''}{delta}）→ {row[1][:30]}"


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


def kb_cleanup() -> dict:
    """Archive (never delete) test-fixture rows and unprovenanced legacy rows
    so they leave the active pool (ledger 0302). Reversible via status."""
    _init()
    with _lock, _db() as con:
        fx = con.execute(
            "UPDATE kb_items SET status='archive', updated=? "
            "WHERE status='active' AND source LIKE 'qq:g1:t%'",
            (time.time(),)).rowcount
        up = con.execute(
            "UPDATE kb_items SET status='archive', updated=? "
            "WHERE status='active' AND source LIKE 'qq:g:t0:%'",
            (time.time(),)).rowcount
        con.commit()
    return {"fixtures_archived": fx, "unprovenanced_archived": up}


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
