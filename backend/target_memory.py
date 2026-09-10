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
COGNITION_FILE = _PROJECT_ROOT / "docs" / "元亨认知根基.md"

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
    salience: float = 0.5  # 0..1 情感/理想显著度：越高越难忘（design v1 §1.1）

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
            "salience": self.salience,
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
        self._boost_ts: dict[str, float] = {}  # recall-use boost dedup window (ledger 0189)
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
                ("salience", "REAL NOT NULL DEFAULT 0.5"),
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
            try:
                raw = extractor.compress(dropped, prev=self._summary)
            except TypeError:
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

    def summary_line(self) -> str:
        """Rolling L1 summary as one context line (injected ahead of recent
        turns so very long conversations don't lose their early arc)."""
        with self._lock:
            if not self._summary:
                return ""
            return f"[早前对话摘要] {self._summary}"

    def bm25_search(self, query: str, limit: int = 8) -> list[dict]:
        """FTS5 BM25 search over L2 (fallback-safe; never raises)."""
        q = str(query or "").strip()
        if not q:
            return []
        import re as _re

        toks = [t for t in _re.split(r"[\s,，。、？！!?;；]+", q) if len(t) >= 2]
        if not toks:
            return []
        match = " OR ".join('"' + t.replace('"', "") + '"' for t in toks[:8])
        con = sqlite3.connect(str(self.db_path))
        try:
            rows = con.execute(
                "SELECT i.id, i.type, i.importance, i.status, i.summary, "
                "bm25(l2_fts) AS s FROM l2_fts JOIN l2_items i "
                "ON l2_fts.sid=i.id WHERE l2_fts MATCH ? "
                "ORDER BY s LIMIT ?", (match, max(1, int(limit)))).fetchall()
        except Exception:
            rows = []
        finally:
            con.close()
        return [{"id": r[0], "type": r[1], "importance": r[2], "status": r[3],
                 "summary": r[4], "bm25": r[5]} for r in rows]

    def contextual_recall(self, text: str, limit: int = 2) -> list[dict]:
        """Lightweight topic recall for auto-injection (ledger 0217).

        Distinct from the tool ``recall`` (which is user-triggered with short
        keywords): this runs on whole casual sentences, so it matches the turn
        against stored item *keywords* by substring. Returns only solid active
        items (importance>=4); empty means nothing worth surfacing.
        """
        q = str(text or "").strip()
        if len(q) < 6:  # too short / pure greeting: skip auto-inject
            return []
        # char-level relevance: stored keywords/summary are often the whole
        # sentence (memory_save fills them verbatim), so use shared 2-grams.
        grams = {q[i:i + 2] for i in range(len(q) - 1)}
        if not grams:
            return []
        # only user-related memories surface casually (not tech facts/knowledge)
        _INJECT_TYPES = ("preference", "event", "decision")
        try:
            with self._lock:
                con = sqlite3.connect(str(self.db_path))
                try:
                    rows = con.execute(
                        "SELECT id, type, importance, status, keywords, summary "
                        "FROM l2_items").fetchall()
                finally:
                    con.close()
        except Exception:
            return []
        good = []
        seen: set[str] = set()
        # 1) semantic candidates (换说法, higher confidence)
        try:
            from backend.vector_memory import semantic_l2

            for it in semantic_l2(q, top=limit * 3, min_score=0.42):
                if int(it.get("importance", 0) or 0) < 5:
                    continue
                if it.get("status") not in (None, "", "active"):
                    continue
                good.append({"id": it["id"], "tier": "L2",
                             "type": it.get("type", "fact"),
                             "importance": it.get("importance", 5),
                             "status": "active",
                             "summary": it.get("summary", ""),
                             "_score": float(it.get("score", 0.0))})
                seen.add(it["id"])
        except Exception:
            pass
        # 2) literal 2-gram candidates (baseline below semantic)
        for r in rows:
            try:
                if r[1] not in _INJECT_TYPES:
                    continue
                if int(r[2] or 0) < 5:
                    continue
                if r[3] not in (None, "", "active"):
                    continue
                store = str(r[4] or "") or str(r[5] or "")
                if not any(g in store for g in grams):
                    continue
                s = str(r[5] or "").strip()
            except Exception:
                continue
            if s and len(s) >= 4 and r[0] not in seen:
                good.append({"id": r[0], "tier": "L2", "type": r[1],
                             "importance": r[2], "status": r[3],
                             "summary": s, "_score": 0.45})
                seen.add(r[0])
        # 3) diary semantic (own words can also be recalled in chat)
        try:
            from backend.vector_memory import semantic_any

            for d in semantic_any(q, ["diary"], top=limit, min_score=0.48):
                did = d.get("id", "")
                if not did or did in seen:
                    continue
                good.append({"id": did, "tier": "diary", "type": "diary",
                             "importance": 6, "status": "active",
                             "summary": str(d.get("text", ""))[:120],
                             "_score": float(d.get("score", 0.0))})
                seen.add(did)
        except Exception:
            pass
        # 4) BM25 candidates (lexical strength) then cross-encoder rerank
        try:
            for b in self.bm25_search(q, limit=limit * 4):
                if b["id"] in seen:
                    continue
                if b.get("type") not in _INJECT_TYPES:
                    continue
                if int(b.get("importance", 0) or 0) < 5:
                    continue
                if b.get("status") not in (None, "", "active"):
                    continue
                good.append({"id": b["id"], "tier": "L2", "type": b["type"],
                             "importance": b["importance"],
                             "status": b["status"],
                             "summary": b["summary"], "_score": 0.45})
                seen.add(b["id"])
        except Exception:
            pass
        if len(good) > 1:
            try:
                from backend.vector_memory import rerank

                scores = rerank(q, [g["summary"] for g in good])
                for g, s in zip(good, scores):
                    g["_score"] = float(s)
            except Exception:
                pass
        good.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
        # de-dup by text (diary/l2 may hold the same sentence)
        uniq: list[dict] = []
        seen_txt: set[str] = set()
        for g in good:
            t = str(g.get("summary", ""))[:80]
            if t in seen_txt:
                continue
            seen_txt.add(t)
            uniq.append(g)
        good = uniq
        for g in good:
            g.pop("_score", None)
        return good[:limit]

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
                    (id,tier,type,importance,summary,content_hash,keywords,status,evidence_ref,created_at,version,obsolete_of,access_count,last_accessed,belief,evidence_count,belief_updated,salience)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      tier=excluded.tier, type=excluded.type,
                      importance=excluded.importance, summary=excluded.summary,
                      content_hash=excluded.content_hash, keywords=excluded.keywords,
                      status=excluded.status, evidence_ref=excluded.evidence_ref,
                      version=excluded.version, obsolete_of=excluded.obsolete_of,
                      salience=excluded.salience
                    """,
                    (
                        item.id, item.tier, item.type, item.importance, item.summary,
                        item.content_hash, item.keywords, item.status, item.evidence_ref,
                        item.created_at, item.version, item.obsolete_of, 0, 0.0,
                        0.5, 0, time.time(), float(getattr(item, "salience", 0.5)),
                    ),
                )
                con.execute("INSERT OR REPLACE INTO l2_fts(sid, keywords, summary) VALUES (?,?,?)",
                            (item.id, item.keywords, item.summary))
            con.commit()
            con.close()
        try:
            # vector side-table for semantic recall (ledger 0226); lazy model
            keep = [it for it in items if it.status != "archive" and it.summary]
            if keep:
                from backend.vector_memory import _conn as _vc, embed as _emb

                texts = [f"{it.summary} {it.keywords}".strip()[:256]
                         for it in keep]
                vs = _emb(texts)
                vc = _vc()
                try:
                    for it, v in zip(keep, vs):
                        vc.execute(
                            "INSERT OR REPLACE INTO vec(id,scope,vec)"
                            " VALUES(?,?,?)", (it.id, "l2", v.tobytes()))
                    vc.commit()
                finally:
                    vc.close()
        except Exception:
            pass
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
    BELIEF_LAMBDA_DAY = 1.0 / 8.0  # ~7 days of no use drops belief 0.5 -> <0.22 (cold hint), ledger 0189
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
        # ledger 0189: legacy rows with belief_updated=0 never decayed; backfill
        # from created_at so real age counts from the first upkeep on.
        con.execute(
            "UPDATE l2_items SET belief_updated=created_at "
            "WHERE belief_updated=0 AND created_at>0"
        )
        con.commit()
        rows = con.execute(
            "SELECT id, belief, belief_updated, salience FROM l2_items WHERE belief_updated > 0"
        ).fetchall()
        n = 0
        for iid, b, updated, sal in rows:
            days = max(0.0, (now - float(updated)) / 86400.0)
            if days <= 0:
                continue
            s = max(0.0, min(1.0, float(sal if sal is not None else 0.5)))
            eff_days = days * (1.0 - 0.7 * s)  # high salience -> near-permanent
            nb = self.belief_step(float(b), 0.0, decay_days=eff_days)
            con.execute(
                "UPDATE l2_items SET belief=?, belief_updated=? WHERE id=?",
                (nb, now, iid),
            )
            n += 1
        con.commit()
        con.close()
        return n

    def set_salience(self, item_id: str, value: float) -> None:
        """Set an item's emotional/ideal salience (0..1). High salience -> the
        item barely decays (design v1 §1.1: 情感/理想高峰近乎不遗忘)."""
        v = max(0.0, min(1.0, float(value)))
        con = sqlite3.connect(str(self.db_path))
        con.execute("UPDATE l2_items SET salience=? WHERE id=?", (v, item_id))
        con.commit()
        con.close()

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


    def review_reinforce(self, min_importance: int = 7, stale_days: float = 3.0,
                         now: Optional[float] = None) -> int:
        """A2 (ledger 0193): weekly reinforcement — high-importance items that
        have been idle (no belief update / access for `stale_days`) get their
        belief_updated refreshed and +1 evidence, so important memories are
        NOT washed away by time-decay. Zero LLM. Returns count reinforced."""
        import time as _t

        now = float(now or _t.time())
        con = sqlite3.connect(str(self.db_path))
        rows = con.execute(
            "SELECT id FROM l2_items "
            "WHERE status='active' AND importance>=? AND belief_updated>0 "
            "AND (? - belief_updated) > (?*86400.0)",
            (int(min_importance), now, float(stale_days)),
        ).fetchall()
        n = 0
        for (iid,) in rows:
            con.execute(
                "UPDATE l2_items SET belief_updated=?, evidence_count=evidence_count+1, "
                "last_accessed=? WHERE id=?",
                (now, now, iid),
            )
            n += 1
        con.commit()
        con.close()
        return n

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

    def audit_suspicious(self, limit: int = 20) -> dict:
        """Memory health check (ledger 0226): sample recent active L2 items,
        ask the local model to flag fabricated / unsupported / contradictory
        ones, and DOWNGRADE them (never delete)."""
        import json as _json
        import urllib.request

        con = sqlite3.connect(str(self.db_path))
        try:
            rows = con.execute(
                "SELECT id, type, importance, summary FROM l2_items "
                "WHERE status='active' AND type IN ('fact','event') "
                "AND summary NOT LIKE '认知%' "
                "ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),)).fetchall()
        finally:
            con.close()
        if not rows:
            return {"checked": 0, "flagged": [], "downgraded": 0}
        listing = "\n".join(f"{r[0]} | {r[3][:120]}" for r in rows)
        prompt = ("下面是你（元亨）的一些长期记忆条目。请挑出【可能有问题】的："
                  "凭空编造、缺少依据、或与常理自相矛盾的。没有就返回空数组。"
                  "只输出 JSON 数组，每项 {\"id\":\"...\",\"reason\":\"...\"}。\n"
                  + listing)
        flagged = []
        try:
            body = _json.dumps({
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 800, "temperature": 0.2,
                "reasoning_effort": "none",
            }).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:8081/v1/chat/completions", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = _json.loads(r.read().decode("utf-8", "replace"))
                txt = str(d["choices"][0]["message"].get("content") or "")
            import re as _re

            m = _re.search(r"\[.*\]", txt, _re.S)
            if m:
                for it in _json.loads(m.group(0)) or []:
                    iid = str(it.get("id", "")).strip()
                    if iid and any(iid == r0[0] for r0 in rows):
                        flagged.append({"id": iid,
                                        "reason": str(it.get("reason", ""))[:80]})
        except Exception:
            flagged = []
        downgraded = 0
        for f in flagged:
            try:
                self.mark(f["id"], "downgraded")
                downgraded += 1
            except Exception:
                pass
        return {"checked": len(rows), "flagged": flagged,
                "downgraded": downgraded}

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
            self._boost_recalled(ranked)
            return ranked
        sql = self._recall_via_sqlite(q, int(limit))
        self._boost_recalled(sql)
        return sql

    def _boost_recalled(self, items: list[dict]) -> None:
        """R1 (ledger 0189): using a memory strengthens it — each recall adds a
        weak +0.05 evidence to the hits, deduped within a 30 s window so a burst
        of identical queries cannot inflate belief."""
        import time as _t

        try:
            now = _t.time()
            for h in (items or [])[:5]:
                iid = str(h.get("id", ""))
                if not iid:
                    continue
                if now - self._boost_ts.get(iid, 0.0) < 30.0:
                    continue
                self._boost_ts[iid] = now
                self.observe_hit(iid, strength=0.05)
        except Exception:
            pass

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
    def persona_draft(self, *, max_tokens_chars: int = 560) -> str:
        """Read-only draft rendered from golden memory/ files + cognition
        foundation (docs/元亨认知根基.md) — the L3 persona block."""
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
        if COGNITION_FILE.exists():
            text = COGNITION_FILE.read_text(encoding="utf-8")
            for sec, label in (
                ("## 三、人机关系：同一 / 互补 / 独特", "人机"),
                ("## 五、命名考与四德", "名德"),
                ("## 六、成长路线", "成长"),
            ):
                m = re.search(re.escape(sec) + r"(.*?)(?=\n## |\Z)", text, re.S)
                if m:
                    part = _normalize(m.group(1))[:110]
                    if part:
                        parts.append(f"{label}: " + part)
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
