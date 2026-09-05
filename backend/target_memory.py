"""Target memory service (batch-1 ledger spec 0116-0120).

Implements the agreed baseline with hard invariants:
- L1 transient: 3-5 turn window + early-turn Summary Compression (non-blocking
  summary produced by a local/cloud LLM in the background; window keeps 5 turns).
- L2 mid-term: structured items in SQLite + rebuildable FTS5 index; 云=候选生成
  (importance initial + segment summary), 本地=裁决 (accept/downgrade/cold/
  archive); importance thresholds 8/4 for summary tiers; state machine only
  marks (active/降权/cold/archive) — never deletes.
- L3: persona draft (read-only five-dim from golden memory files) + ledger
  (project experience) interlink via evidence_ref.
- recall() is a tool-type query (FTS5/BM25 -> RRF-ish ordering) that the reasoner
  may call; it never auto-injects into every turn.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = _PROJECT_ROOT / "cache" / "memstore" / "memstore.db"
GOLDEN_MEMORY = _PROJECT_ROOT / "memory"

SYSTEM_TEMPLATE = "先进始于计算，元亨开拓未来"
L1_WINDOW_TURNS = 5
L2_HIGH_IMPORTANCE = 8
L2_MID_IMPORTANCE = 4

_WORD = re.compile(r"\w+")


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _normalize(text: str) -> str:
    return re.sub(r"[\s\u3000,，。.!！?？:：;；、\-]+", "", str(text or ""))


@dataclass(slots=True)
class L2Item:
    id: str
    tier: str
    type: str
    importance: int
    summary: str
    content_hash: str
    keywords: str
    status: str = "active"
    evidence_ref: str = ""
    created_at: float = 0.0
    version: int = 1
    obsolete_of: str = ""
    access_count: int = 0
    last_accessed: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tier": self.tier,
            "type": self.type,
            "importance": self.importance,
            "summary": self.summary,
            "content_hash": self.content_hash,
            "keywords": self.keywords,
            "status": self.status,
            "evidence_ref": self.evidence_ref,
            "created_at": self.created_at,
            "version": self.version,
            "obsolete_of": self.obsolete_of,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
        }


class TargetMemoryService:
    """One service instance per composition; owns L1/L2/L3 state."""

    def __init__(
        self,
        *,
        db_path: Path = DEFAULT_DB,
        window_turns: int = L1_WINDOW_TURNS,
        kw_index: Any = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.window_turns = int(window_turns)
        self._kw = kw_index
        self._lock = threading.RLock()
        self._turns: list[dict[str, str]] = []
        self._summary: str = ""
        self._summary_pending = False
        self._summary_version = 0
        self._pending_dropped: list[dict[str, str]] = []
        self._extractor: Any = None  # cloud candidate generator (Hybrid, local-first)
        self._judge: Any = None  # local judge (importance/adjudication)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ---------- storage ----------
    def _init_db(self) -> None:
        with self._lock:
            con = sqlite3.connect(str(self.db_path))
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS l2_items (
                  id TEXT PRIMARY KEY,
                  tier TEXT NOT NULL,
                  type TEXT NOT NULL,
                  importance INTEGER NOT NULL,
                  summary TEXT NOT NULL,
                  content_hash TEXT NOT NULL,
                  keywords TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'active',
                  evidence_ref TEXT NOT NULL DEFAULT '',
                  created_at REAL NOT NULL,
                  version INTEGER NOT NULL DEFAULT 1,
                  obsolete_of TEXT NOT NULL DEFAULT '',
                  access_count INTEGER NOT NULL DEFAULT 0,
                  last_accessed REAL NOT NULL DEFAULT 0,
                  belief REAL NOT NULL DEFAULT 0.5,
                  evidence_count INTEGER NOT NULL DEFAULT 0,
                  belief_updated REAL NOT NULL DEFAULT 0
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_l2_status ON l2_items(status)")
            con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS l2_fts USING fts5(sid, keywords, summary)")
            cols = {r[1] for r in con.execute("PRAGMA table_info(l2_items)").fetchall()}
            for name, decl in (
                ("belief", "REAL NOT NULL DEFAULT 0.5"),
                ("evidence_count", "INTEGER NOT NULL DEFAULT 0"),
                ("belief_updated", "REAL NOT NULL DEFAULT 0"),
            ):
                if name not in cols:
                    con.execute(f"ALTER TABLE l2_items ADD COLUMN {name} {decl}")
            con.commit()
            con.close()

    def set_llm_hooks(self, extractor: Any = None, judge: Any = None) -> None:
        """extractor=cloud-candidate generator; judge=local adjudicator."""
        self._extractor = extractor
        self._judge = judge

    # ---------- L1 transient ----------
    def append_turn(self, *, role: str, text: str) -> None:
        with self._lock:
            self._turns.append({"role": role, "text": str(text)})
            if len(self._turns) > self.window_turns:
                dropped = self._turns[: len(self._turns) - self.window_turns]
                self._turns = self._turns[-self.window_turns:]
                if dropped:
                    self._pending_dropped = list(dropped)
                    self._summary_pending = True

    async def process_summary(self) -> None:
        """Run the pending Summary Compression (non-blocking by caller)."""
        extractor = self._extractor
        with self._lock:
            dropped = self._pending_dropped or []
        if not dropped:
            return
        if extractor is None or not callable(getattr(extractor, "compress", None)):
            with self._lock:
                self._pending_dropped = []
                self._summary_pending = False
            return
        try:
            raw = extractor.compress(dropped)
            if inspect.isawaitable(raw):
                raw = await raw
            summary_text, version = raw
            with self._lock:
                self._summary = str(summary_text or "")
                self._summary_pending = False
                self._summary_version = int(version or 0)
        except Exception:
            with self._lock:
                self._summary_pending = False
        finally:
            with self._lock:
                self._pending_dropped = []

    def context_block(self) -> str:
        with self._lock:
            lines = []
            if self._summary:
                lines.append(f"[近期摘要] {self._summary}")
            for turn in self._turns:
                prefix = "用户" if turn["role"] == "user" else "元亨"
                lines.append(f"{prefix}: {turn['text'][:2000]}")
            return "\n".join(lines)

    # ---------- L2 mid-term ----------
    def submit_turn_candidates(self, *, text: str, transcript: str, evidence_ref: str = "", source: str = "turn") -> list[L2Item]:
        """Compatibility stub: use ``submit_candidates`` (async) instead."""
        raise RuntimeError("use await service.submit_candidates(...)")

    async def submit_candidates(self, *, text: str, transcript: str, evidence_ref: str = "", source: str = "turn") -> list[L2Item]:
        """Cloud-generate candidate items (importance initial + tiered summary).

        The local judge must run afterwards (``adjudicate``) to confirm
        importance/status; cloud never finalizes.
        """
        extractor = self._extractor
        items: list[L2Item] = []
        if extractor is None or not callable(getattr(extractor, "candidates", None)):
            return items
        context = {"text": str(text), "transcript": str(transcript)[:4000], "source": source}
        try:
            raw = extractor.candidates(context)
            if inspect.isawaitable(raw):
                raw = await raw
        except Exception:
            return items
        for cand in raw or []:
            importance = int(cand.get("importance", 3) or 3)
            summary = str(cand.get("summary", "") or "")
            type_ = str(cand.get("type", "fact") or "fact")
            tier = str(cand.get("tier", "L2") or "L2")
            if not summary:
                continue
            items.append(
                L2Item(
                    id="mem_" + _fingerprint(json.dumps([evidence_ref, summary[:80]], ensure_ascii=False))[:12],
                    tier=tier,
                    type=type_,
                    importance=importance,
                    summary=summary,
                    content_hash=_fingerprint(summary),
                    keywords=str(cand.get("keywords", "") or "")[:400],
                    evidence_ref=str(evidence_ref),
                    created_at=time.time(),
                    access_count=0,
                )
            )
        return items
        for cand in raw or []:
            importance = int(cand.get("importance", 3) or 3)
            summary = str(cand.get("summary", "") or "")
            type_ = str(cand.get("type", "fact") or "fact")
            tier = str(cand.get("tier", "L2") or "L2")
            if not summary:
                continue
            items.append(
                L2Item(
                    id="mem_" + _fingerprint(json.dumps([evidence_ref, summary[:80]], ensure_ascii=False))[:12],
                    tier=tier,
                    type=type_,
                    importance=importance,
                    summary=summary,
                    content_hash=_fingerprint(summary),
                    keywords=str(cand.get("keywords", "") or "")[:400],
                    evidence_ref=str(evidence_ref),
                    created_at=time.time(),
                    access_count=0,
                )
            )
        return items

    def adjudicate(self, items: list[L2Item], *, local_only: bool = True) -> list[L2Item]:
        """Compatibility stub: use ``adjudicate_async``."""
        raise RuntimeError("use await service.adjudicate_async(...)")

    async def adjudicate_async(self, items: list[L2Item], *, local_only: bool = True) -> list[L2Item]:
        """Local adjudication: confirm importance/status/status transitions."""
        judge = self._judge
        with self._lock:
            con = sqlite3.connect(str(self.db_path))
            for item in items:
                if judge is not None and callable(getattr(judge, "adjudicate", None)):
                    try:
                        verdict = judge.adjudicate(item.to_dict())
                        if inspect.isawaitable(verdict):
                            verdict = await verdict
                        item.importance = int(verdict.get("importance", item.importance))
                        item.status = str(verdict.get("status", item.status) or item.status)
                    except Exception:
                        pass
                if item.importance <= L2_MID_IMPORTANCE and item.status == "active":
                    item.status = "downgraded"
                con.execute(
                    """
                    INSERT INTO l2_items
                    (id,tier,type,importance,summary,content_hash,keywords,status,evidence_ref,created_at,version,obsolete_of,access_count,last_accessed,belief,evidence_count,belief_updated)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      tier=excluded.tier, type=excluded.type,
                      importance=excluded.importance, summary=excluded.summary,
                      content_hash=excluded.content_hash, keywords=excluded.keywords,
                      status=excluded.status, evidence_ref=excluded.evidence_ref,
                      version=excluded.version, obsolete_of=excluded.obsolete_of
                    """,
                    (
                        item.id, item.tier, item.type, item.importance, item.summary,
                        item.content_hash, item.keywords, item.status, item.evidence_ref,
                        item.created_at, item.version, item.obsolete_of, 0, 0.0,
                        0.5, 0, time.time(),
                    ),
                )
                con.execute("INSERT OR REPLACE INTO l2_fts(sid, keywords, summary) VALUES (?,?,?)",
                            (item.id, item.keywords, item.summary))
            con.commit()
            con.close()
        self._sync_kw(items)
        return items

    def _sync_kw(self, items: list[L2Item]) -> None:
        """Mirror written L2 items into the keyword index (best-effort)."""
        if not items:
            return
        try:
            from backend.target_kw_index import KeywordIndex

            kw = self._kw if self._kw is not None else KeywordIndex()
            for item in items:
                kw.upsert_doc(
                    docid=item.id,
                    source="l2",
                    summary=item.summary,
                    record_title=f"L2-{item.type}",
                    importance=item.importance,
                    status=item.status,
                )
        except Exception:
            return

    # ---------- belief (bayes-style confidence, M2 ledger 0152) ----------
    BELIEF_LAMBDA_DAY = 1.0 / 45.0
    BELIEF_DOWNGRADE_HINT = 0.22

    @staticmethod
    def belief_step(belief: float, evidence: float, decay_days: float = 0.0,
                    lambda_day: float = BELIEF_LAMBDA_DAY) -> float:
        """Logistic-ish belief update: decay then evidence step, clamped (0,1)."""
        import math as _m

        b = min(0.99, max(0.01, float(belief)))
        if decay_days > 0:
            b *= _m.exp(-lambda_day * decay_days)
        e = max(-1.0, min(1.0, float(evidence)))
        b += b * (1.0 - b) * e
        return min(0.99, max(0.01, b))

    def observe_hit(self, item_id: str, strength: float = 0.3) -> Optional[float]:
        """Positive evidence (recall usage / corroboration). strength ~ confidence."""
        return self._belief_apply(item_id, +max(0.05, min(1.0, float(strength))))

    def observe_contradiction(self, item_id: str) -> Optional[float]:
        """Negative evidence (user disagreement / contradiction)."""
        return self._belief_apply(item_id, -0.5)

    def apply_belief_decay(self, now: Optional[float] = None) -> int:
        """Time-decay all items; returns count updated (never deletes)."""
        now = float(now or time.time())
        con = sqlite3.connect(str(self.db_path))
        rows = con.execute(
            "SELECT id, belief, belief_updated FROM l2_items WHERE belief_updated > 0"
        ).fetchall()
        n = 0
        for iid, b, updated in rows:
            days = max(0.0, (now - float(updated)) / 86400.0)
            if days <= 0:
                continue
            nb = self.belief_step(float(b), 0.0, decay_days=days)
            con.execute(
                "UPDATE l2_items SET belief=?, belief_updated=? WHERE id=?",
                (nb, now, iid),
            )
            n += 1
        con.commit()
        con.close()
        return n

    def _belief_apply(self, item_id: str, evidence: float) -> Optional[float]:
        con = sqlite3.connect(str(self.db_path))
        row = con.execute(
            "SELECT belief, belief_updated FROM l2_items WHERE id=?", (item_id,)
        ).fetchone()
        if row is None:
            con.close()
            return None
        now = time.time()
        b, updated = float(row[0]), float(row[1] or now)
        days = max(0.0, (now - updated) / 86400.0)
        nb = self.belief_step(b, evidence, decay_days=days)
        con.execute(
            "UPDATE l2_items SET belief=?, evidence_count=evidence_count+1, "
            "belief_updated=?, last_accessed=? WHERE id=?",
            (nb, now, now, item_id),
        )
        con.commit()
        con.close()
        return nb

    def apply_belief_downgrades(self, hint: float = BELIEF_DOWNGRADE_HINT) -> int:
        """Auto-suggest: active items whose belief fell below the hint (repeated
        contradiction + decay) are marked ``downgraded`` (never deleted).
        Returns the number downgraded."""
        con = sqlite3.connect(str(self.db_path))
        rows = con.execute(
            "SELECT id FROM l2_items WHERE status='active' AND belief < ?",
            (float(hint),),
        ).fetchall()
        for (iid,) in rows:
            con.execute(
                "UPDATE l2_items SET status='downgraded' WHERE id=?", (iid,)
            )
        con.commit()
        n = len(rows)
        con.close()
        if rows:
            try:
                from backend.target_kw_index import KeywordIndex

                kw = self._kw if self._kw is not None else KeywordIndex()
                con2 = sqlite3.connect(str(kw.db_path))
                con2.executemany(
                    "UPDATE kw_docs SET status='downgraded' WHERE docid=?",
                    [(iid,) for (iid,) in rows],
                )
                con2.commit()
                con2.close()
            except Exception:
                pass
        return n

    def belief_report(self, item_id: str) -> Optional[dict]:
        con = sqlite3.connect(str(self.db_path))
        row = con.execute(
            "SELECT belief, evidence_count, belief_updated, status FROM l2_items WHERE id=?",
            (item_id,),
        ).fetchone()
        con.close()
        if row is None:
            return None
        return {
            "belief": round(float(row[0]), 4),
            "evidence_count": int(row[1]),
            "updated": float(row[2]),
            "status": row[3],
            "downgrade_hint": float(row[0]) < self.BELIEF_DOWNGRADE_HINT,
        }

    def store_item(self, item: L2Item) -> None:
        """Synchronous L2 write (sqlite + fts + keyword mirror). No judging.

        Used by the memory.save capability (explicit model-triggered store);
        the async adjudication rail remains the default for turn-derived items.
        """
        with self._lock:
            con = sqlite3.connect(str(self.db_path))
            try:
                now = time.time()
                con.execute(
                    """
                    INSERT OR REPLACE INTO l2_items
                    (id,tier,type,importance,summary,content_hash,keywords,status,evidence_ref,created_at,version,obsolete_of,access_count,last_accessed,belief,evidence_count,belief_updated)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        item.id, item.tier, item.type, item.importance, item.summary,
                        item.content_hash, item.keywords, item.status,
                        item.evidence_ref, item.created_at, item.version,
                        item.obsolete_of, 0, now, 0.5, 0, now,
                    ),
                )
                con.execute(
                    "INSERT OR REPLACE INTO l2_fts(sid, keywords, summary) VALUES (?,?,?)",
                    (item.id, item.keywords, item.summary),
                )
                con.commit()
            finally:
                con.close()
        self._sync_kw([item])

    def mark(self, item_id: str, status: str) -> None:
        if status not in {"active", "downgraded", "cold", "archive"}:
            raise ValueError("illegal status; memory is never deleted")
        con = sqlite3.connect(str(self.db_path))
        con.execute("UPDATE l2_items SET status=? WHERE id=?", (status, item_id))
        con.commit()
        con.close()

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """Tool-type recall; never auto-injected.

        Ledger 0148: keyword-index (mini inverted catalog) is the primary
        ranking path; the SQLite FTS5/LIKE path is retained as fallback when
        the index is broken/missing (recall never hard-fails).
        """
        q = str(query or "").strip()
        if not q:
            return []
        ranked = self._recall_via_kw(q, int(limit))
        if ranked is not None:
            return ranked
        return self._recall_via_sqlite(q, int(limit))

    def _recall_via_kw(self, q: str, limit: int) -> Optional[list[dict]]:
        try:
            if self._kw is not None:
                hits = self._kw.query(q, limit=limit, source="l2")
            else:
                from backend.target_kw_index import DEFAULT_DB, KeywordIndex

                if not Path(DEFAULT_DB).exists():
                    return None
                hits = KeywordIndex().query(q, limit=limit, source="l2")
        except Exception:
            return None
        if not hits:
            return []
        con = sqlite3.connect(str(self.db_path))
        try:
            out: list[dict] = []
            for h in hits:
                row = con.execute(
                    """
                    SELECT id, tier, type, importance, status, evidence_ref, summary
                    FROM l2_items WHERE id=?
                    """,
                    (h["docid"],),
                ).fetchone()
                if row is None:
                    continue
                out.append(
                    {
                        "id": row[0], "tier": row[1], "type": row[2],
                        "importance": row[3], "status": row[4],
                        "evidence_ref": row[5], "summary": row[6],
                    }
                )
                if len(out) >= limit:
                    break
            for h in hits[: min(limit, len(out))]:
                try:
                    self.observe_hit(h["docid"], strength=float(h.get("confidence", 0.3)) * 0.3)
                except Exception:
                    pass
            return out
        finally:
            con.close()

    def _recall_via_sqlite(self, q: str, limit: int) -> list[dict]:
        con = sqlite3.connect(str(self.db_path))
        rows = []
        try:
            rows = con.execute(
                """
                SELECT i.id, i.tier, i.type, i.importance, i.status, i.evidence_ref, i.summary
                FROM l2_fts f JOIN l2_items i ON i.id = f.sid
                WHERE l2_fts MATCH ?
                ORDER BY i.importance DESC, i.last_accessed DESC
                LIMIT ?
                """,
                (q, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if not rows:
            pattern = f"%{q}%"
            rows = con.execute(
                """
                SELECT id, tier, type, importance, status, evidence_ref, summary
                FROM l2_items
                WHERE (summary LIKE ? ESCAPE '\\' OR keywords LIKE ? ESCAPE '\\')
                  AND status IN ('active','downgraded')
                ORDER BY importance DESC, last_accessed DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
        con.close()
        return [
            {
                "id": r[0], "tier": r[1], "type": r[2], "importance": r[3],
                "status": r[4], "evidence_ref": r[5], "summary": r[6],
            }
            for r in rows
        ]

    def rebuild_fts(self) -> None:
        with self._lock:
            con = sqlite3.connect(str(self.db_path))
            try:
                con.execute("DELETE FROM l2_fts")
                # 'DELETE FROM fts' is a rebuild trick for fts5; insert all active
                for row in con.execute("SELECT id, keywords, summary FROM l2_items").fetchall():
                    con.execute("INSERT INTO l2_fts(sid, keywords, summary) VALUES (?,?,?)", row)
            finally:
                con.commit()
                con.close()

    # ---------- L3 persona draft ----------
    def persona_draft(self, *, max_tokens_chars: int = 300) -> str:
        """Read-only five-dim draft rendered from golden memory/ files."""
        parts: list[str] = []
        rules = {p.stem: p for p in GOLDEN_MEMORY.glob("*.md")}
        identity = rules.get("user_identity")
        project = rules.get("yhlz_project_context")
        collab = rules.get("collaboration_rules")
        if project:
            m = re.search(r"## YHLZ核心理念(.*?)(?=\n##|\Z)", project.read_text(encoding="utf-8"), re.S)
            if m:
                parts.append("理念: " + _normalize(m.group(1))[:120])
        if collab:
            m = re.search(r"## 设计思想(.*?)(?=\n##|\Z)", collab.read_text(encoding="utf-8"), re.S)
            if m:
                parts.append("思想: " + _normalize(m.group(1))[:180])
        if identity:
            m = re.search(r"## 我的决策方式(.*?)(?=\n##|\Z)", identity.read_text(encoding="utf-8"), re.S)
            if m:
                parts.append("决策: " + _normalize(m.group(1))[:120])
        draft = "；".join(parts)[:max_tokens_chars]
        return draft or SYSTEM_TEMPLATE

    def health(self) -> dict:
        con = sqlite3.connect(str(self.db_path))
        n = con.execute("SELECT COUNT(*) FROM l2_items").fetchone()[0]
        active = con.execute("SELECT COUNT(*) FROM l2_items WHERE status='active'").fetchone()[0]
        con.close()
        return {
            "provider": "target-memory-v1",
            "l2_items": int(n),
            "l2_active": int(active),
            "l1_window": int(len(self._turns)),
            "summary_pending": bool(self._summary_pending),
            "db": str(self.db_path),
        }
