"""T3（R3, ledger 0611）：SQLite 持久投递存储——统一普通回复与主动通知的效果状态。

设计（未接生产调用；生产启用仍过 G3）：
- 状态机：queued → sending → confirmed | rejected | retryable | unknown | expired
- 租约：lease_owner/lease_epoch/lease_until；**过期 sending 一律回收为 unknown**
  （不恢复为 queued 直接重发——发送后断连/丢 ack 无法撤回外部效应）。
- 幂等：唯一键 = (source_event_id, target_type, target_id, kind)。
- 只读诊断只给状态/摘要，不含正文（正文在受限 payload 存储）。
- 租约代际只保护本地写入；QQ 端无幂等键时无法承诺严格恰好一次。
"""
from __future__ import annotations

import pathlib
import sqlite3
import time
import uuid

from backend.qq_bridge_state import path as _bridge_path

DEFAULT_DB = _bridge_path(
    "outbox.db",
    pathlib.Path(__file__).resolve().parent.parent / "cache" / "qq_deliveries.db")

STATES = ("queued", "sending", "confirmed", "rejected", "retryable", "unknown", "expired")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deliveries (
  delivery_id      TEXT PRIMARY KEY,
  source_event_id  TEXT NOT NULL,
  effect_id        TEXT NOT NULL DEFAULT '',
  channel          TEXT NOT NULL,
  target_type      TEXT NOT NULL,
  target_id        TEXT NOT NULL,
  kind             TEXT NOT NULL DEFAULT 'reply',
  payload_ref      TEXT NOT NULL DEFAULT '',
  payload_hash     TEXT NOT NULL DEFAULT '',
  state            TEXT NOT NULL DEFAULT 'queued',
  created_at       REAL NOT NULL,
  expires_at       REAL,
  attempts         INTEGER NOT NULL DEFAULT 0,
  next_retry_at    REAL,
  lease_owner      TEXT NOT NULL DEFAULT '',
  lease_epoch      INTEGER NOT NULL DEFAULT 0,
  lease_until      REAL,
  submission_marker TEXT NOT NULL DEFAULT '',
  remote_message_id TEXT NOT NULL DEFAULT '',
  ack_ref          TEXT NOT NULL DEFAULT '',
  last_error_code  TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_deliveries_source
  ON deliveries(source_event_id, target_type, target_id, kind);
"""


def connect(path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_SCHEMA)
    con.commit()
    return con


def enqueue(con: sqlite3.Connection, *, source_event_id: str, channel: str,
            target_type: str, target_id: str, kind: str = "reply",
            payload_ref: str = "", payload_hash: str = "", effect_id: str = "",
            expires_at: float | None = None, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    did = uuid.uuid4().hex[:16]
    try:
        con.execute(
            "INSERT INTO deliveries(delivery_id,source_event_id,effect_id,channel,target_type,"
            "target_id,kind,payload_ref,payload_hash,state,created_at,expires_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,'queued',?,?)",
            (did, source_event_id, effect_id, channel, target_type, target_id, kind,
             payload_ref, payload_hash, now, expires_at))
        con.commit()
        return {"ok": True, "delivery_id": did, "state": "queued", "idempotent": False}
    except sqlite3.IntegrityError:
        row = con.execute(
            "SELECT delivery_id,state FROM deliveries WHERE source_event_id=? AND "
            "target_type=? AND target_id=? AND kind=?",
            (source_event_id, target_type, target_id, kind)).fetchone()
        return {"ok": True, "delivery_id": row[0], "state": row[1], "idempotent": True}


def claim_due(con: sqlite3.Connection, owner: str, *, now: float | None = None,
              lease_s: float = 90.0, limit: int = 1) -> list:
    now = time.time() if now is None else now
    con.execute("BEGIN IMMEDIATE")
    try:
        rows = con.execute(
            "SELECT delivery_id,lease_epoch FROM deliveries WHERE state IN ('queued','retryable') "
            "AND (next_retry_at IS NULL OR next_retry_at<=?) "
            "AND (expires_at IS NULL OR expires_at>?) ORDER BY created_at LIMIT ?",
            (now, now, limit)).fetchall()
        out = []
        for did, ep in rows:
            con.execute(
                "UPDATE deliveries SET state='sending', lease_owner=?, lease_epoch=lease_epoch+1, "
                "lease_until=?, submission_marker=?, attempts=attempts+1 WHERE delivery_id=?",
                (owner, now + lease_s, f"intent:{now}", did))
            out.append({"delivery_id": did, "lease_epoch": ep + 1})
        con.commit()
        return out
    except Exception:
        con.rollback()
        raise


def claim_by_id(con: sqlite3.Connection, delivery_id: str, owner: str, *,
                now: float | None = None, lease_s: float = 90.0) -> dict:
    """按 id 领取（供统一发送适配器；仍有租约与 epoch）。"""
    now = time.time() if now is None else now
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute("SELECT lease_epoch,state FROM deliveries WHERE delivery_id=?",
                          (delivery_id,)).fetchone()
        if not row or row[1] not in ("queued", "retryable"):
            con.rollback()
            return {}
        con.execute(
            "UPDATE deliveries SET state='sending', lease_owner=?, lease_epoch=lease_epoch+1, "
            "lease_until=?, submission_marker=?, attempts=attempts+1 WHERE delivery_id=?",
            (owner, now + lease_s, f"intent:{now}", delivery_id))
        con.commit()
        return {"delivery_id": delivery_id, "lease_epoch": row[0] + 1}
    except Exception:
        con.rollback()
        raise


def mark_rejected(con: sqlite3.Connection, delivery_id: str, *, lease_epoch: int,
                  error_code: str = "") -> bool:
    cur = con.execute(
        "UPDATE deliveries SET state='rejected', last_error_code=?, lease_owner='', "
        "lease_until=NULL WHERE delivery_id=? AND lease_epoch=? AND state='sending'",
        (error_code, delivery_id, lease_epoch))
    con.commit()
    return cur.rowcount == 1


def mark_confirmed(con: sqlite3.Connection, delivery_id: str, *, lease_epoch: int,
                   remote_message_id: str = "", ack_ref: str = "") -> bool:
    cur = con.execute(
        "UPDATE deliveries SET state='confirmed', remote_message_id=?, ack_ref=?, "
        "lease_owner='', lease_until=NULL WHERE delivery_id=? AND lease_epoch=? AND state='sending'",
        (remote_message_id, ack_ref, delivery_id, lease_epoch))
    con.commit()
    return cur.rowcount == 1


def mark_failed(con: sqlite3.Connection, delivery_id: str, *, lease_epoch: int,
                before_send: bool, error_code: str = "", retry_at: float | None = None) -> str:
    """before_send=True → retryable；False（发送后断连/超时/丢ack）→ **unknown**。"""
    state = "retryable" if before_send else "unknown"
    cur = con.execute(
        "UPDATE deliveries SET state=?, last_error_code=?, next_retry_at=?, lease_owner='', "
        "lease_until=NULL WHERE delivery_id=? AND lease_epoch=? AND state='sending'",
        (state, error_code, retry_at, delivery_id, lease_epoch))
    con.commit()
    return state if cur.rowcount == 1 else "stale"


def reclaim_expired(con: sqlite3.Connection, *, now: float | None = None) -> int:
    """租约过期的 sending → unknown（先查后决，不直接重发）。"""
    now = time.time() if now is None else now
    cur = con.execute(
        "UPDATE deliveries SET state='unknown', last_error_code='lease_expired_after_send' "
        "WHERE state='sending' AND lease_until IS NOT NULL AND lease_until<?", (now,))
    con.commit()
    return cur.rowcount


def expire_due(con: sqlite3.Connection, *, now: float | None = None) -> int:
    now = time.time() if now is None else now
    cur = con.execute(
        "UPDATE deliveries SET state='expired', last_error_code='ttl_expired' "
        "WHERE state IN ('queued','retryable') AND expires_at IS NOT NULL AND expires_at<=?", (now,))
    con.commit()
    return cur.rowcount


def status_summary(con: sqlite3.Connection) -> dict:
    rows = con.execute("SELECT state, COUNT(*) FROM deliveries GROUP BY state").fetchall()
    return {s: n for s, n in rows}
