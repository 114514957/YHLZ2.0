"""S3 L2 review queue. Model/group producers may submit, never approve.

Candidate, decision, provenance, FTS and L2 changes share ONE SQLite transaction.
The local CLI is the review boundary; no HTTP/MCP/LLM write tool is registered.
Approval means permission to retain an external claim, NOT proof it is true.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from backend.target_memory import DEFAULT_DB, TargetMemoryService, _normalize

KINDS = frozenset({'fact', 'event', 'preference', 'decision'})


class ReviewConflict(ValueError):
    pass


class MemoryReviewQueue:
    def __init__(self, db_path: Path = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Deliberately do not initialize TargetMemoryService or read owner L1.
        with self._transaction() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS memory_candidates (
                id TEXT PRIMARY KEY, summary TEXT NOT NULL, kind TEXT NOT NULL,
                channel TEXT NOT NULL, speaker TEXT NOT NULL, observed_at REAL NOT NULL,
                evidence_ref TEXT NOT NULL, evidence_json TEXT NOT NULL,
                replaces_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL, decided_at REAL NOT NULL DEFAULT 0,
                reviewer TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
                item_id TEXT NOT NULL DEFAULT '')''')
            con.execute('''CREATE TABLE IF NOT EXISTS memory_review_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT NOT NULL,
                item_id TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL,
                reason TEXT NOT NULL, at REAL NOT NULL)''')
            con.execute('''CREATE TABLE IF NOT EXISTS memory_provenance (
                item_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL UNIQUE,
                channel TEXT NOT NULL, speaker TEXT NOT NULL, observed_at REAL NOT NULL,
                evidence_ref TEXT NOT NULL, evidence_json TEXT NOT NULL)''')
            con.execute('CREATE INDEX IF NOT EXISTS idx_candidates_status '
                        'ON memory_candidates(status, channel)')

    @contextmanager
    def _transaction(self):
        con = sqlite3.connect(str(self.db_path), timeout=5)
        con.row_factory = sqlite3.Row
        try:
            con.execute('BEGIN IMMEDIATE')
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _event(con, cid, iid, action, actor, reason, now):
        con.execute('INSERT INTO memory_review_events '
                    '(candidate_id,item_id,action,actor,reason,at) VALUES (?,?,?,?,?,?)',
                    (cid, iid, action, actor, reason, now))

    def submit(self, *, summary: str, channel: str, speaker: str = 'unknown',
               kind: str = 'fact', observed_at: float, evidence_ref: str,
               user_text: str, assistant_text: str = '', replaces_id: str = '') -> dict:
        summary = str(summary).strip()
        if not 4 <= len(summary) <= 500 or not _normalize(summary):
            raise ValueError('summary must contain 4..500 characters')
        if kind not in KINDS:
            raise ValueError('unsupported L2 kind; L3 cannot enter this queue')
        if not (re.fullmatch(r'qq_g[0-9]{5,15}', channel) or channel == 'owner_local'):
            raise ValueError('only group proposals or explicit local corrections')
        if replaces_id and channel != 'owner_local':
            raise ValueError('group proposals cannot replace owner facts')
        if (not math.isfinite(observed_at) or observed_at <= 0
                or not evidence_ref.strip() or not user_text.strip()):
            raise ValueError('time and source evidence required')
        if len(evidence_ref) > 300 or len(speaker) > 120:
            raise ValueError('source metadata too long')
        # Stable across restarts and extraction retries. A changed model type
        # or evidence reference cannot resurrect an identical rejected claim.
        key = json.dumps([channel, _normalize(summary), replaces_id], ensure_ascii=False)
        cid = 'review_' + hashlib.sha256(key.encode()).hexdigest()[:24]
        now = time.time()
        evidence = json.dumps({'user_text': user_text[:4000],
                               'assistant_text': assistant_text[:2000],
                               'truncated': len(user_text) > 4000 or len(assistant_text) > 2000},
                              ensure_ascii=False)
        with self._transaction() as con:
            old = con.execute('SELECT * FROM memory_candidates WHERE id=?', (cid,)).fetchone()
            if old:
                return {**dict(old), 'created': False}
            total = con.execute("SELECT COUNT(*) FROM memory_candidates WHERE status='pending'").fetchone()[0]
            scoped = con.execute("SELECT COUNT(*) FROM memory_candidates WHERE status='pending' AND channel=?", (channel,)).fetchone()[0]
            if total >= 1000 or scoped >= 100:
                raise ReviewConflict('pending review capacity reached; nothing discarded')
            con.execute('''INSERT INTO memory_candidates
                (id,summary,kind,channel,speaker,observed_at,evidence_ref,evidence_json,replaces_id,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (cid, summary, kind, channel, speaker, observed_at, evidence_ref, evidence, replaces_id, now))
            self._event(con, cid, '', 'submitted', channel, '', now)
            row = con.execute('SELECT * FROM memory_candidates WHERE id=?', (cid,)).fetchone()
            return {**dict(row), 'created': True}

    def list(self, status: str = 'pending', limit: int = 50) -> list[dict]:
        if status not in {'pending', 'approved', 'rejected', 'all'}:
            raise ValueError('invalid candidate status')
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        try:
            # Stable IDs, not mutable list positions, are used for decisions.
            rows = con.execute('SELECT * FROM memory_candidates WHERE (?=\'all\' OR status=?) '
                               'ORDER BY created_at,id LIMIT ?',
                               (status, status, max(1, min(limit, 1000)))).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def inspect(self, cid: str) -> dict:
        """Show review history separately from the approved item's current state."""
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        try:
            con.execute('BEGIN')
            row = con.execute('SELECT * FROM memory_candidates WHERE id=?', (cid,)).fetchone()
            if row is None:
                raise KeyError(cid)
            item = None
            if row['item_id']:
                item = con.execute('SELECT id,summary,status,invalid_at,superseded_by,obsolete_of '
                                   'FROM l2_items WHERE id=?', (row['item_id'],)).fetchone()
            events = con.execute('SELECT * FROM memory_review_events WHERE candidate_id=? '
                                 "OR (item_id<>'' AND item_id=?) ORDER BY seq",
                                 (cid, row['item_id'])).fetchall()
            return {'candidate': dict(row), 'item': dict(item) if item else None,
                    'events': [dict(event) for event in events]}
        finally:
            con.close()

    def decide(self, cid: str, *, approve: bool, reason: str,
               service: TargetMemoryService | None = None) -> dict:
        """LOCAL owner review only. Not an authentication API for remote callers."""
        if not reason.strip() or len(reason) > 1000:
            raise ValueError('a review reason (1..1000 characters) is required')
        if approve and (service is None or service.db_path.resolve() != self.db_path.resolve()):
            raise ValueError('approval requires the explicitly selected target L2 service')
        now = time.time()
        with self._transaction() as con:
            row = con.execute('SELECT * FROM memory_candidates WHERE id=?', (cid,)).fetchone()
            if row is None:
                raise KeyError(cid)
            state = 'approved' if approve else 'rejected'
            if row['status'] == state:
                return {**dict(row), 'changed': False}
            if row['status'] != 'pending':
                raise ReviewConflict('decision is terminal; rejected candidates cannot auto-reopen')
            iid = ''
            if approve:
                from backend.target_constitution import check_text
                allowed, _ = check_text(row['summary'])
                if not allowed:
                    raise ReviewConflict('content gate refused; candidate remains pending')
                old = None
                if row['replaces_id']:
                    old = con.execute('SELECT * FROM l2_items WHERE id=?', (row['replaces_id'],)).fetchone()
                    if (old is None or old['invalid_at'] or old['status'] != 'active'
                            or old['protected'] or old['kind'] == 'profile' or old['tier'] != 'L2'):
                        raise ReviewConflict('replacement target missing/inactive/protected; requires separate review')
                iid = 'mem_' + cid
                con.execute('''INSERT INTO l2_items
                    (id,tier,type,importance,summary,content_hash,keywords,status,evidence_ref,
                     created_at,belief_updated,source,stance,valid_at,obsolete_of)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (iid, 'L2', row['kind'], 5, row['summary'],
                     hashlib.sha256(row['summary'].encode()).hexdigest()[:16], row['summary'][:80],
                     'active', 'review:' + cid, now, now,
                     '群聊' if row['channel'].startswith('qq_g') else 'owner',
                     'speculation' if row['channel'].startswith('qq_g') else 'fact',
                     now, row['replaces_id']))
                con.execute('INSERT INTO l2_fts(sid,keywords,summary) VALUES (?,?,?)',
                            (iid, row['summary'][:80], row['summary']))
                con.execute('INSERT INTO memory_provenance VALUES (?,?,?,?,?,?,?)',
                            (iid, cid, row['channel'], row['speaker'], row['observed_at'],
                             row['evidence_ref'], row['evidence_json']))
                if old is not None:
                    con.execute('UPDATE l2_items SET invalid_at=?,superseded_by=? WHERE id=?',
                                (now, iid, row['replaces_id']))
                    self._event(con, cid, row['replaces_id'], 'superseded', 'owner_local', reason, now)
            con.execute('UPDATE memory_candidates SET status=?,decided_at=?,reviewer=?,reason=?,item_id=? WHERE id=?',
                        (state, now, 'owner_local', reason, iid, cid))
            self._event(con, cid, iid, state, 'owner_local', reason, now)
            out = dict(con.execute('SELECT * FROM memory_candidates WHERE id=?', (cid,)).fetchone())
        # FTS is atomic above. Global keyword/vector mirrors are deliberately
        # NOT required for a commit and must never auto-adjudicate the new fact.
        return {**out, 'changed': True}

    def invalidate(self, iid: str, *, reason: str) -> bool:
        """Explicit local soft invalidation. No deletion and no root/persona edit."""
        if not reason.strip() or len(reason) > 1000:
            raise ValueError('invalidation reason required')
        with self._transaction() as con:
            row = con.execute('SELECT * FROM l2_items WHERE id=?', (iid,)).fetchone()
            if row is None:
                raise KeyError(iid)
            if row['protected'] or row['kind'] == 'profile' or row['tier'] != 'L2':
                raise ReviewConflict('protected/profile/L3 requires separate review')
            if row['invalid_at']:
                return False
            now = time.time()
            con.execute('UPDATE l2_items SET invalid_at=? WHERE id=?', (now, iid))
            self._event(con, '', iid, 'invalidated', 'owner_local', reason, now)
            return True
