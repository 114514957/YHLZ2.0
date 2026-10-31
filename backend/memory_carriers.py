"""Carrier evidence in the existing L2 SQLite, not a new memory database.

Channel strings are routing labels, NOT authentication. The session entry must
supply owner_access after its existing ingress gate. Group/public calls are
refused here even if a private capability accidentally leaks through a registry.
An intent is durable before a carrier mutation; crash leftovers stay pending for
human reconciliation rather than silently being replayed into diary/plan/L2.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
import uuid
from dataclasses import dataclass, replace
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CarrierOrigin:
    channel: str
    carrier: str
    owner_access: bool
    actor: str = "agent"

    def __post_init__(self):
        if self.carrier not in {"memory", "diary", "plan", "kb", "schedule"}:
            raise ValueError("unknown carrier")
        if not self.channel or len(self.channel) > 120:
            raise ValueError("invalid channel")
        # An ingress bug cannot turn an explicit group/public label into owner.
        if self.owner_access and not (self.channel in {"private", "console", "owner_local"}
                                      or self.channel.startswith("qq_p")):
            raise ValueError("owner route contradicts channel")
        if self.actor not in {"owner", "agent"}:
            raise ValueError("invalid actor")

    @property
    def scope(self):
        if self.carrier == "kb":
            return "knowledge" if self.owner_access else "external:" + self.channel
        return "owner" if self.owner_access else "channel:" + self.channel

    @property
    def source(self):
        return "owner" if self.carrier == "memory" and self.owner_access else "agent"

    @property
    def stance(self):
        return "fact" if self.source == "owner" else "opinion"


class CarrierEvidence:
    """No raw prompts, credentials or private text in the evidence journal."""
    def __init__(self, db_path: Path, *, timeout_s: float = 1.0):
        self.db_path = Path(db_path)
        if not self.db_path.is_file():
            raise FileNotFoundError("select an initialized L2 SQLite first")
        self.timeout_s = max(0.01, min(float(timeout_s), 5))
        with self._db() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS carrier_events (
                trace_id TEXT PRIMARY KEY, evidence_ref TEXT NOT NULL UNIQUE,
                carrier TEXT NOT NULL, channel TEXT NOT NULL, scope TEXT NOT NULL,
                source TEXT NOT NULL, stance TEXT NOT NULL, actor TEXT NOT NULL,
                observed_at REAL NOT NULL, content_hash TEXT NOT NULL,
                content_chars INTEGER NOT NULL, operation TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', target_ref TEXT NOT NULL DEFAULT '',
                error_type TEXT NOT NULL DEFAULT '', finished_at REAL NOT NULL DEFAULT 0)""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_carrier_scope_state ON carrier_events(scope,state)")

    @contextmanager
    def _db(self):
        con = sqlite3.connect(str(self.db_path), timeout=self.timeout_s)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def begin(self, origin: CarrierOrigin, *, content: str, operation: str,
              observed_at: float | None = None) -> dict:
        if not origin.owner_access:
            raise PermissionError("public/group carriers require a separate review queue")
        stamp = time.time() if observed_at is None else float(observed_at)
        if not math.isfinite(stamp) or stamp <= 0:
            raise ValueError("invalid observed_at")
        trace = uuid.uuid4().hex
        ref = "carrier:" + origin.carrier + ":" + trace
        text = str(content)
        op = str(operation)
        if op not in {"save", "write", "add", "done"}:
            raise ValueError("invalid operation")
        row = dict(trace_id=trace, evidence_ref=ref, carrier=origin.carrier,
                   channel=origin.channel, scope=origin.scope, source=origin.source,
                   stance=origin.stance, actor=origin.actor, observed_at=stamp,
                   content_hash=hashlib.sha256(text.encode()).hexdigest(),
                   content_chars=len(text), operation=op)
        with self._db() as con:
            keys = tuple(row)
            con.execute("INSERT INTO carrier_events(" + ",".join(keys) + ") VALUES(" +
                        ",".join("?" for _ in keys) + ")", tuple(row.values()))
        return row

    def finish(self, trace_id: str, *, state: str, target_ref: str = "", error_type: str = ""):
        if state not in {"committed", "refused", "failed"}:
            raise ValueError("invalid terminal state")
        # Diagnostics contain only the class name; never exception messages.
        if error_type and not error_type.isidentifier():
            raise ValueError("error_type must be a class name")
        with self._db() as con:
            cur = con.execute("UPDATE carrier_events SET state=?,target_ref=?,error_type=?,finished_at=? "
                              "WHERE trace_id=? AND state='pending'",
                              (state, str(target_ref)[:300], error_type[:80], time.time(), trace_id))
            if cur.rowcount != 1:
                raise RuntimeError("carrier intent missing/already terminal")

    def list(self, *, channel: str = "", state: str = "", limit: int = 50) -> list[dict]:
        if state and state not in {"pending", "committed", "refused", "failed"}:
            raise ValueError("invalid state")
        where, params = [], []
        if channel:
            where.append("channel=?"); params.append(channel)
        if state:
            where.append("state=?"); params.append(state)
        sql = "SELECT * FROM carrier_events" + (" WHERE " + " AND ".join(where) if where else "")
        with self._db() as con:
            rows = con.execute(sql + " ORDER BY observed_at DESC,trace_id LIMIT ?",
                               (*params, max(1, min(int(limit), 200)))).fetchall()
        return [dict(row) for row in rows]

    def health(self) -> dict:
        with self._db() as con:
            counts = dict(con.execute("SELECT state,COUNT(*) FROM carrier_events GROUP BY state").fetchall())
        return {"states": counts, "pending_reconciliation": counts.get("pending", 0),
                "automatic_replay": False}


def bind_memory_carriers(registry: Any, service: Any, *, channel: str, owner_access: bool):
    """Session-local closures; preserve all capability policies/verification metadata.

    Does NOT promote diary, plans or KB into L2/L3. Source is assigned by trusted
    glue, never accepted from the model's arguments. Read-only plan calls remain
    read-only. Evidence failure is visible and never triggers a duplicate retry.
    """
    from backend.target_scheduler_tools import memory_save, kb_add, _looks_like_profile
    mapping = {"memory.save": "memory", "diary.write": "diary",
               "task.plan": "plan", "kb.add": "kb", "schedule.plan": "schedule"}
    for name, carrier in mapping.items():
        cap = registry.get(name)
        if cap is None:
            continue
        origin = CarrierOrigin(channel, carrier, bool(owner_access))
        def handler(params, *, _carrier=carrier, _origin=origin, _handler=cap.handler):
            if not _origin.owner_access:
                raise PermissionError("private carrier denied for public/group channel")
            if _carrier == "plan" and str(params.get("action", "add")) == "list":
                return _handler(params)
            if _carrier == "schedule" and str(params.get("action", "list")).lower() in {"", "list", "show_all", "get", "show"}:
                return _handler(params)
            operation = {"memory": "save", "diary": "write", "kb": "add"}.get(
                _carrier, str(params.get("action", "add")))
            content = str(params.get("summary" if _carrier == "kb" else "content", ""))
            if _carrier == "schedule":
                content = json.dumps(params, ensure_ascii=False, sort_keys=True)
            journal = CarrierEvidence(service.db_path)
            event = journal.begin(_origin, content=content, operation=operation)
            try:
                if _carrier == "memory":
                    output = memory_save(content, str(params.get("kind", "preference")),
                                         int(params.get("importance", 0) or 0), service=service,
                                         source="owner", kind_profile=bool(params.get("profile") or _looks_like_profile(content)),
                                         evidence_ref=event["evidence_ref"])
                elif _carrier == "kb":
                    output = kb_add(content, category=str(params.get("category", "tech")),
                                    source=event["evidence_ref"], detail=str(params.get("detail", "")))
                else:
                    output = _handler(params)
            except BaseException as exc:
                try:
                    journal.finish(event["trace_id"], state="failed", error_type=type(exc).__name__)
                except Exception:
                    pass  # The durable pending intent remains visible for reconciliation.
                raise
            accepted = str(output).startswith(("已", "重复条目已存在", "近似条目已存在", "该内容已在记忆中", "近似记忆已存在"))
            try:
                journal.finish(event["trace_id"], state="committed" if accepted else "refused",
                               target_ref=event["evidence_ref"])
            except Exception as exc:
                # Carrier mutation may have succeeded. Do not lie or replay it.
                return str(output) + "（证据确认失败，保留待核对记录：" + type(exc).__name__ + "；不要自动重试）"
            return output
        registry.register_capability(replace(cap, handler=handler), override=True)
