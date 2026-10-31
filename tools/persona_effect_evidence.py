"""Independent committed-data readback for dedicated persona fixture workers.

Handler success is not proof of persistence. Never use this module against real
user stores: every path is checked against the explicit temporary root. Receipts
contain hashes/counts only; they do not grant semantic or production acceptance.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3

WRITE_CAPS = ('memory.save', 'diary.write', 'task.plan', 'schedule.plan', 'kb.add')


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    default=str).encode()).hexdigest()


class FixtureEffects:
    def __init__(self, root: Path, memory):
        self.root = Path(root).resolve()
        self.memory = memory
        self.receipts = []

    def _path(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.root):
            raise PermissionError('readback path outside fixture')
        return path

    def _rows(self, path, query, args=()):
        path = self._path(path)
        if not path.exists():
            return []
        # Separate connection: uncommitted handler writes are not visible here.
        con = sqlite3.connect(str(path), timeout=1)
        con.execute('PRAGMA query_only=ON')
        try:
            return [list(row) for row in con.execute(query, args).fetchall()]
        finally:
            con.close()

    def _snapshot(self, name, params):
        from backend import target_scheduler_tools as st, target_schedule, yuanheng_kb
        text = str(params.get('summary' if name == 'kb.add' else 'content', '')).strip()
        if name == 'memory.save':
            rows = self._rows(self.memory.db_path,
                "SELECT id,summary,status,evidence_ref FROM l2_items WHERE summary=? AND status IN ('active','downgraded')",
                (text[:500],))
            return {'matches': len(rows), 'sha256': _hash(rows)}
        if name == 'kb.add':
            try:
                rows = self._rows(yuanheng_kb.DEFAULT_KB_DB,
                    "SELECT id,summary,status,source FROM kb_items WHERE summary=? AND status='active'", (text,))
            except sqlite3.OperationalError as exc:
                if 'no such table' not in str(exc):
                    raise
                rows = []
            return {'matches': len(rows), 'sha256': _hash(rows)}
        if name in ('diary.write', 'task.plan'):
            path = self._path(st.DIARY_FILE if name == 'diary.write' else st.TASK_FILE)
            data = path.read_text(encoding='utf-8') if path.exists() else ''
            if name == 'task.plan':
                action = params.get('action', 'add')
                if action not in ('add', 'done'):
                    return None
                needle = '- [ ] ' + text if action == 'add' else '- [x] ' + text
                count = sum(line == needle if action == 'add' else line.startswith('- [x]') and text in line
                            for line in data.splitlines()) if text else 0
            else:
                count = data.count('\n' + text + '\n') if text else 0
            return {'matches': count, 'sha256': _hash(data)}
        if name == 'schedule.plan':
            if params.get('action', 'add') != 'add':
                return None
            path = self._path(target_schedule.SCHED_FILE)
            rows = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
            steps = [s.strip()[:300] for s in str(params.get('steps', '')).splitlines() if s.strip()][:6]
            matches = [r for r in rows if r.get('name') == str(params.get('name', '')).strip()
                       and r.get('cadence', {}).get('time') == str(params.get('time', ''))
                       and r.get('cadence', {}).get('type') == str(params.get('cadence', 'daily'))
                       and r.get('steps') == steps and r.get('enabled') is True]
            return {'matches': len(matches), 'sha256': _hash(rows)}
        return None

    def check_requested_content(self, name, text):
        """Compare actual stored summaries with user intent, ignoring only final punctuation.

        No semantic substitution accepted: a changed subject/object still fails.
        Limited to synthetic fixture checks; never scans production data.
        """
        from backend import yuanheng_kb
        norm = lambda value: str(value).strip().rstrip('。.!！')
        if name == 'memory.save':
            rows = self._rows(self.memory.db_path, "SELECT summary FROM l2_items WHERE status IN ('active','downgraded')")
        elif name == 'kb.add':
            rows = self._rows(yuanheng_kb.DEFAULT_KB_DB, "SELECT summary FROM kb_items WHERE status='active'")
        else:
            raise ValueError('unsupported content check')
        return {'mode': 'trim_terminal_punctuation_only',
                'matches': sum(norm(row[0]) == norm(text) for row in rows),
                'sha256': _hash(rows)}

    def bind(self, registry):
        for name in WRITE_CAPS:
            cap = registry.get(name)
            if cap is None:
                continue
            def handler(params, *, _name=name, _handler=cap.handler):
                receipt = {'name': _name.replace('.', '_'), 'scope': 'temporary_fixture',
                           'arguments_sha256': _hash(params), 'status': 'not_verified'}
                self.receipts.append(receipt)
                try:
                    before = self._snapshot(_name, params)
                    output = _handler(params)
                    after = self._snapshot(_name, params)
                    receipt.update(before=before, after=after)
                    if after is None:
                        receipt['status'] = 'unsupported_operation'
                    elif after['matches'] > (before or {}).get('matches', 0):
                        receipt['status'] = 'verified_in_fixture'
                    elif after['matches'] > 0:
                        receipt['status'] = 'already_present_in_fixture'
                    else:
                        receipt['status'] = 'effect_missing'
                    return output
                except BaseException as exc:
                    receipt.update(status='readback_or_handler_error', error_type=type(exc).__name__)
                    raise
            registry.register_capability(replace(cap, handler=handler), override=True)
