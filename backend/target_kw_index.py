"""Lightweight keyword index (mini inverted catalog) for ledger + memory.

User decision (ledger 0148): with only a few thousand documents, a full-text
engine is overkill; build a slim keyword index instead.  Zero new deps:
SQLite tables ``kw_index(term, docid, tf)`` + ``kw_docs(docid, ...)`` with a
plain index on ``term``.  Terms = latin words + latin digits + CJK bigrams/
trigrams (no jieba; deterministic and dependency-free).  Scoring = simplified
BM25: idf * tf, just enough for ranking among a few thousand docs.
"""

from __future__ import annotations

import math
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = _PROJECT_ROOT / "cache" / "search" / "kw_index.db"

_LATIN = re.compile(r"[a-zA-Z0-9]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> dict[str, int]:
    """Return {term: count}; CJK runs become bigrams+trigrams, latin words raw."""
    text = str(text or "").lower()
    terms: dict[str, int] = {}
    for m in _LATIN.finditer(text):
        tok = m.group(0)
        terms[tok] = terms.get(tok, 0) + 1
    for run in _CJK_RUN.finditer(text):
        s = run.group(0)
        n = len(s)
        for i in range(n):
            if i + 2 <= n:
                t = s[i : i + 2]
                terms[t] = terms.get(t, 0) + 1
            if i + 3 <= n:
                t = s[i : i + 3]
                terms[t] = terms.get(t, 0) + 1
    return terms


def split_strong_weak(query: str) -> tuple[list[str], list[str]]:
    """Strong terms (latin words + CJK 3-grams; 2-char runs promoted) vs weak
    (CJK 2-grams) — used so a stray bigram cannot alone recall a doc."""
    text = str(query or "").lower()
    strong: list[str] = []
    weak: list[str] = []
    for m in _LATIN.finditer(text):
        strong.append(m.group(0))
    for run in _CJK_RUN.finditer(text):
        s = run.group(0)
        n = len(s)
        if n <= 2:
            strong.append(s)
            continue
        for i in range(n):
            if i + 3 <= n:
                strong.append(s[i : i + 3])
            if i + 2 <= n:
                weak.append(s[i : i + 2])
    return strong, weak


class KeywordIndex:
    """Mini inverted index on SQLite; thread-safe; rebuildable (cache dir)."""

    def __init__(self, db_path: Path = DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path))
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    def _use(self, fn: Callable[[sqlite3.Connection], object]) -> object:
        with self._lock:
            con = self._conn()
            try:
                return fn(con)
            finally:
                con.close()

    def _init_schema(self) -> None:

        def _create(con: sqlite3.Connection) -> None:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS kw_docs (
                  docid TEXT PRIMARY KEY,
                  source TEXT NOT NULL,
                  summary TEXT NOT NULL,
                  record_title TEXT NOT NULL DEFAULT '',
                  importance INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL DEFAULT 'active',
                  updated_at REAL NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS kw_index (
                  term TEXT NOT NULL,
                  docid TEXT NOT NULL,
                  tf INTEGER NOT NULL,
                  PRIMARY KEY (term, docid)
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_kw_term ON kw_index(term)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_kw_docext ON kw_docs(source, status)")
            con.commit()

        self._use(_create)

    # ---------- write ----------
    def upsert_doc(
        self,
        *,
        docid: str,
        source: str,
        summary: str,
        record_title: str = "",
        importance: int = 0,
        status: str = "active",
    ) -> None:
        def _write(con: sqlite3.Connection) -> None:
            con.execute("DELETE FROM kw_index WHERE docid=?", (docid,))
            con.execute(
                """
                INSERT OR REPLACE INTO kw_docs(docid,source,summary,record_title,importance,status,updated_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (docid, source, str(summary), str(record_title), int(importance),
                 str(status), time.time()),
            )
            terms = tokenize(str(summary) + " " + str(record_title))
            con.executemany(
                "INSERT OR REPLACE INTO kw_index(term,docid,tf) VALUES (?,?,?)",
                [(t, docid, c) for t, c in terms.items()],
            )
            con.commit()

        self._use(_write)

    def clear_source(self, source: str) -> int:
        """Remove every doc of a source (used before authoritative rebuild)."""

        def _clear(con: sqlite3.Connection) -> int:
            ids = [r[0] for r in con.execute(
                "SELECT docid FROM kw_docs WHERE source=?", (source,)).fetchall()]
            con.executemany("DELETE FROM kw_index WHERE docid=?", [(i,) for i in ids])
            cur = con.execute("DELETE FROM kw_docs WHERE source=?", (source,))
            con.commit()
            return cur.rowcount

        return self._use(_clear)

    def delete_doc(self, docid: str) -> None:
        def _delete(con: sqlite3.Connection) -> None:
            con.execute("DELETE FROM kw_index WHERE docid=?", (docid,))
            con.execute("DELETE FROM kw_docs WHERE docid=?", (docid,))
            con.commit()

        self._use(_delete)

    # ---------- query ----------
    def query(
        self,
        query: str,
        limit: int = 5,
        *,
        source: Optional[str] = None,
        min_score: float = 0.0,
    ) -> list[dict]:
        """BM25-ish: idf = log(1 + N/df); score = idf * tf summed over matched terms.

        Recall gate (ledger 0149 fix): candidates must cover >= half of the
        query's STRONG terms (latin + 3-grams); a lone 2-gram cannot recall.
        """
        all_terms = tokenize(query)
        strong, weak = split_strong_weak(query)
        if not strong and not weak:
            return []
        strong_req = max(1, math.ceil(len(set(strong)) / 2)) if strong else 0
        terms = all_terms
        if not terms:
            return []

        def _search(con: sqlite3.Connection) -> list[dict]:
            n = con.execute("SELECT COUNT(*) FROM kw_docs").fetchone()[0]
            join_sql = (
                "SELECT kw_index.term, kw_index.docid, kw_index.tf "
                "FROM kw_index JOIN kw_docs ON kw_docs.docid = kw_index.docid "
                "WHERE kw_index.term IN (" + ",".join("?" * len(terms)) + ")"
            )
            params: list[object] = list(terms)
            if source is not None:
                join_sql += " AND kw_docs.source=?"
                params.append(source)
            join_sql += " AND kw_docs.status IN ('active','downgraded')"
            rows = con.execute(join_sql, tuple(params)).fetchall()
            if not rows:
                return []
            df_map: dict[str, int] = {}
            for term, _docid, _tf in rows:
                df_map[term] = df_map.get(term, 0) + 1
            term_idf: dict[str, float] = {
                t: math.log(1.0 + n / max(df, 1)) for t, df in df_map.items()
            }
            strong_hits: dict[str, set[str]] = {t: set() for t in set(strong)}
            scores: dict[str, float] = {}
            for term, docid, tf in rows:
                scores[docid] = scores.get(docid, 0.0) + float(tf) * term_idf[term]
                if term in strong_hits:
                    strong_hits[term].add(docid)
            recency: dict[str, float] = {}
            for docid in scores:
                m = re.match(r"^ledger:(\d+):", docid)
                recency[docid] = 0.25 * (int(m.group(1)) / 2000.0) if m else 0.0
            candidates: list[str] = []
            for docid in scores:
                covered = sum(1 for t in set(strong) if docid in strong_hits[t])
                if strong_req and covered < strong_req:
                    continue
                candidates.append(docid)
            order = sorted(
                candidates,
                key=lambda d: scores[d] + recency.get(d, 0.0),
                reverse=True,
            )
            results: list[dict] = []
            n_strong = len(set(strong))
            top_score = max((scores[d] + recency.get(d, 0.0) for d in order), default=0.0)
            for docid in order[: int(limit)]:
                if scores[docid] < min_score:
                    continue
                row = con.execute(
                    "SELECT source, summary, record_title, importance, status FROM kw_docs WHERE docid=?",
                    (docid,),
                ).fetchone()
                if row is None:
                    continue
                covered = sum(1 for t in set(strong) if docid in strong_hits[t])
                total = scores[docid] + recency.get(docid, 0.0)
                cov_part = (covered / n_strong) if n_strong else 1.0
                rel_part = (total / top_score) if top_score > 0 else 0.0
                confidence = round(min(0.99, 0.7 * cov_part + 0.3 * rel_part), 2)
                results.append(
                    {
                        "docid": docid,
                        "source": row[0],
                        "summary": row[1],
                        "record_title": row[2],
                        "importance": int(row[3]),
                        "status": row[4],
                        "score": round(scores[docid], 4),
                        "confidence": confidence,
                    }
                )
                if len(results) >= int(limit):
                    break
            return results

        return self._use(_search)

    def count(self) -> int:
        def _count(con: sqlite3.Connection) -> int:
            return int(con.execute("SELECT COUNT(*) FROM kw_docs").fetchone()[0])

        return self._use(_count)

    def health(self) -> dict:
        def _health(con: sqlite3.Connection) -> dict:
            docs = con.execute("SELECT COUNT(*) FROM kw_docs").fetchone()[0]
            terms = con.execute("SELECT COUNT(*) FROM kw_index").fetchone()[0]
            return {"provider": "keyword-index-v1", "docs": int(docs), "terms": int(terms)}

        return self._use(_health)
