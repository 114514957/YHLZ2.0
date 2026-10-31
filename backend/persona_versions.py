"""L3 recoverable intents in the existing L2 database.

SQLite and a Markdown file are NOT one atomic transaction. Persist a prepared
intent before touching the file, then finalize evidence stamps transactionally.
After a crash recover explicitly; never overwrite an externally edited file.
Only the owner approval flow/local confirmed CLI may call mutation methods.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class PersonaConflict(RuntimeError):
    pass


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic(path, text):
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tmp.open("w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


class PersonaVersions:
    def __init__(self, db_path: Path, foundation: Path):
        self.db_path = Path(db_path).resolve()
        self.foundation = Path(foundation).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)
        self.key = os.path.normcase(str(self.foundation))
        with self._transaction() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS persona_changes (
                id TEXT PRIMARY KEY, foundation TEXT NOT NULL, version INTEGER NOT NULL,
                operation TEXT NOT NULL, target TEXT NOT NULL, state TEXT NOT NULL,
                before_text TEXT NOT NULL, after_text TEXT NOT NULL,
                before_hash TEXT NOT NULL, after_hash TEXT NOT NULL,
                sources TEXT NOT NULL, claims TEXT NOT NULL, reason TEXT NOT NULL,
                created_at REAL NOT NULL, finished_at REAL NOT NULL DEFAULT 0)""")
            con.execute("CREATE INDEX IF NOT EXISTS persona_change_path ON persona_changes(foundation,state)")

    @contextmanager
    def _transaction(self):
        con = sqlite3.connect(str(self.db_path), timeout=5)
        con.row_factory = sqlite3.Row
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def _text(self):
        try:
            return self.foundation.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    @staticmethod
    def _source(con, iid):
        r = con.execute("SELECT id,status,evidence_ref,summary,version,invalid_at,superseded_by "
                        "FROM l2_items WHERE id=?", (iid,)).fetchone()
        if r is None:
            raise PersonaConflict("source no longer exists")
        return dict(r)

    def _no_pending(self, con):
        if con.execute("SELECT 1 FROM persona_changes WHERE foundation=? AND state='prepared'",
                       (self.key,)).fetchone():
            raise PersonaConflict("prepared intent requires explicit recovery")

    def apply(self, version, body, item_ids, claim_ids, *, expected_before):
        if not body or not claim_ids:
            raise ValueError("approved claims and body required")
        change_id = "persona_" + uuid.uuid4().hex
        with self._transaction() as con:
            self._no_pending(con)
            if self._text() != expected_before:
                raise PersonaConflict("foundation changed since approval")
            if con.execute("SELECT 1 FROM persona_changes WHERE foundation=? AND version=? "
                           "AND operation='apply'", (self.key, int(version))).fetchone():
                raise PersonaConflict("version already used (including reverted versions)")
            sources = []
            for iid in sorted(set(item_ids)):
                before = self._source(con, iid)
                if before['status'] not in ('active', 'downgraded') or before['invalid_at']:
                    raise PersonaConflict("source changed or invalidated before approval")
                after = dict(before, status='archive', evidence_ref=f'persona:consolidated:v{version}')
                sources.append({'before': before, 'after': after})
            self._prepare(con, change_id, version, 'apply', '', expected_before, body,
                          sources, claim_ids, 'owner-approved')
        self.recover(change_id)
        return change_id

    def _prepare(self, con, iid, version, operation, target, before, after, sources, claims, reason):
        con.execute("INSERT INTO persona_changes(id,foundation,version,operation,target,state,"
                    "before_text,after_text,before_hash,after_hash,sources,claims,reason,created_at) "
                    "VALUES(?,?,?,?,?,'prepared',?,?,?,?,?,?,?,?)",
                    (iid, self.key, int(version), operation, target, before, after, _sha(before),
                     _sha(after), json.dumps(sources, ensure_ascii=False), json.dumps(claims),
                     reason, time.time()))

    def recover(self, change_id):
        """Idempotent roll-forward. Only exact before/after snapshots are safe."""
        with self._transaction() as con:
            r = con.execute("SELECT * FROM persona_changes WHERE id=? AND foundation=?",
                            (change_id, self.key)).fetchone()
            if r is None:
                raise ValueError('unknown change')
            if r['state'] != 'prepared':
                return r['state']
            current = self._text()
            if current not in (r['before_text'], r['after_text']):
                raise PersonaConflict('external foundation edits; manual reconciliation required')
            sources = json.loads(r['sources'])
            for entry in sources:
                if self._source(con, entry['before']['id']) != entry['before']:
                    raise PersonaConflict('source evidence changed; manual reconciliation required')
            if current != r['after_text']:
                _atomic(self.foundation, r['after_text'])
            for entry in sources:
                after = entry['after']
                con.execute('UPDATE l2_items SET status=?,evidence_ref=? WHERE id=?',
                            (after['status'], after['evidence_ref'], after['id']))
            con.execute("UPDATE persona_changes SET state='applied',finished_at=? WHERE id=?",
                        (time.time(), change_id))
            if r['operation'] == 'revert':
                con.execute("UPDATE persona_changes SET state='reverted' WHERE id=?", (r['target'],))
        return 'applied'

    def revert(self, change_id, *, reason):
        """Revert only an unchanged approved tip; keep snapshots and all L2 rows."""
        if not reason.strip():
            raise ValueError('owner reason required')
        rid = 'persona_' + uuid.uuid4().hex
        with self._transaction() as con:
            self._no_pending(con)
            r = con.execute('SELECT * FROM persona_changes WHERE id=? AND foundation=?',
                            (change_id, self.key)).fetchone()
            if r is None or r['operation'] != 'apply' or r['state'] != 'applied':
                raise PersonaConflict('not an applied cognition version')
            if self._text() != r['after_text']:
                raise PersonaConflict('only the unchanged tip may be reverted')
            inverse = []
            for entry in json.loads(r['sources']):
                if self._source(con, entry['after']['id']) != entry['after']:
                    raise PersonaConflict('source was edited after approval')
                inverse.append({'before': entry['after'], 'after': entry['before']})
            self._prepare(con, rid, r['version'], 'revert', change_id,
                          r['after_text'], r['before_text'], inverse, [], reason)
        self.recover(rid)
        return rid

    def get(self, change_id):
        """Return one change with snapshots/source evidence for a read-only review."""
        with self._transaction() as con:
            row = con.execute(
                'SELECT * FROM persona_changes WHERE id=? AND foundation=?',
                (str(change_id), self.key),
            ).fetchone()
            if row is None:
                raise KeyError(str(change_id))
            item = dict(row)
            for field in ("sources", "claims"):
                try:
                    item[field] = json.loads(item[field])
                except (TypeError, ValueError):
                    pass
            return item

    def list(self):
        with self._transaction() as con:
            return [dict(r) for r in con.execute(
                'SELECT id,version,operation,target,state,before_hash,after_hash,reason,created_at '
                'FROM persona_changes WHERE foundation=? ORDER BY created_at', (self.key,))]
