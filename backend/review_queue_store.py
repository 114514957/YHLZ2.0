"""T4（R3, ledger 0628）：持久复盘任务存储（review_jobs）。

复用 MemoryReviewQueue 的模式（不另造第三套状态）：
- 状态：`pending → leased → extracting → adjudicating → committing → done`
  可恢复错误 → `retry_wait`；不可恢复 → `needs_review`；**`validated_empty` 是明确成功**。
- **幂等键** = sha256(channel|principal|session|start_seq|end_seq|pipeline_version)
  （**不用纯内容前缀**）。
- **失败不推进水位**；水位只在 `commit_review` 的**一个短事务**里推进。
- 租约 `lease_owner/lease_epoch/lease_until`；**旧 epoch 不可提交**；过期租约回收为 `retry_wait`
  （**不直接重发**，先核对结果）。
- 模型调用由调用方在**写事务外**执行；本模块只做状态与事务。
"""
from __future__ import annotations

import hashlib
import pathlib
import sqlite3
import time
import uuid

DEFAULT_DB = pathlib.Path(__file__).resolve().parent.parent / "cache" / "review_jobs.db"
# 离线测试套件可置 False（避免连生产库触发评测守卫）；生产/评测沙箱保持 True。
ENABLED = True

STATES = ("pending", "leased", "extracting", "adjudicating", "committing",
          "done", "retry_wait", "needs_review", "validated_empty")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_jobs (
  job_id          TEXT PRIMARY KEY,
  channel         TEXT NOT NULL,
  principal_id    TEXT NOT NULL DEFAULT '',
  session_id      TEXT NOT NULL DEFAULT '',
  start_seq       INTEGER NOT NULL,
  end_seq         INTEGER NOT NULL,
  source_ref      TEXT NOT NULL DEFAULT '',
  snapshot_hash   TEXT NOT NULL DEFAULT '',
  state           TEXT NOT NULL DEFAULT 'pending',
  attempts        INTEGER NOT NULL DEFAULT 0,
  next_retry_at   REAL,
  last_error_code TEXT NOT NULL DEFAULT '',
  lease_owner     TEXT NOT NULL DEFAULT '',
  lease_epoch     INTEGER NOT NULL DEFAULT 0,
  lease_until     REAL,
  result_ref      TEXT NOT NULL DEFAULT '',
  pipeline_version TEXT NOT NULL DEFAULT 'v1',
  idempotency_key TEXT NOT NULL,
  created_at      REAL NOT NULL,
  updated_at      REAL NOT NULL,
  committed_at    REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_review_jobs_idem ON review_jobs(idempotency_key);
CREATE TABLE IF NOT EXISTS review_watermarks (
  scope_key  TEXT PRIMARY KEY,
  committed_seq INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL
);
"""


def connect(path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_SCHEMA)
    con.commit()
    return con


def _idem(channel, principal, session, start_seq, end_seq, pipeline_version) -> str:
    raw = f"{channel}|{principal}|{session}|{int(start_seq)}|{int(end_seq)}|{pipeline_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _scope(channel, principal, session) -> str:
    return f"{channel}|{principal}|{session}"


def enqueue_window(con, *, channel: str, principal_id: str = "", session_id: str = "",
                   start_seq: int, end_seq: int, source_ref: str = "",
                   snapshot_hash: str = "", pipeline_version: str = "v1",
                   now: float | None = None) -> dict:
    now = time.time() if now is None else now
    key = _idem(channel, principal_id, session_id, start_seq, end_seq, pipeline_version)
    jid = uuid.uuid4().hex[:16]
    try:
        con.execute(
            "INSERT INTO review_jobs(job_id,channel,principal_id,session_id,start_seq,end_seq,"
            "source_ref,snapshot_hash,state,pipeline_version,idempotency_key,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,'pending',?,?,?,?)",
            (jid, channel, principal_id, session_id, int(start_seq), int(end_seq),
             source_ref, snapshot_hash, pipeline_version, key, now, now))
        con.commit()
        return {"ok": True, "job_id": jid, "state": "pending", "idempotent": False}
    except sqlite3.IntegrityError:
        row = con.execute("SELECT job_id,state FROM review_jobs WHERE idempotency_key=?",
                          (key,)).fetchone()
        return {"ok": True, "job_id": row[0], "state": row[1], "idempotent": True}


def claim_by_id(con, job_id: str, owner: str, *, now: float | None = None,
                lease_s: float = 90.0) -> dict:
    """按 id 领取（供会话复盘真实入口）。"""
    now = time.time() if now is None else now
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute("SELECT lease_epoch,state FROM review_jobs WHERE job_id=?",
                          (job_id,)).fetchone()
        if not row or row[1] not in ("pending", "retry_wait"):
            con.rollback()
            return {}
        con.execute(
            "UPDATE review_jobs SET state='leased', lease_owner=?, lease_epoch=lease_epoch+1, "
            "lease_until=?, attempts=attempts+1, updated_at=? WHERE job_id=?",
            (owner, now + lease_s, now, job_id))
        con.commit()
        return {"job_id": job_id, "lease_epoch": row[0] + 1}
    except Exception:
        con.rollback()
        raise


def claim_due(con, owner: str, *, now: float | None = None, lease_s: float = 90.0,
              limit: int = 1) -> list:
    now = time.time() if now is None else now
    con.execute("BEGIN IMMEDIATE")
    try:
        rows = con.execute(
            "SELECT job_id,lease_epoch FROM review_jobs WHERE state IN ('pending','retry_wait') "
            "AND (next_retry_at IS NULL OR next_retry_at<=?) ORDER BY start_seq LIMIT ?",
            (now, limit)).fetchall()
        out = []
        for jid, ep in rows:
            con.execute(
                "UPDATE review_jobs SET state='leased', lease_owner=?, lease_epoch=lease_epoch+1, "
                "lease_until=?, attempts=attempts+1, updated_at=? WHERE job_id=?",
                (owner, now + lease_s, now, jid))
            out.append({"job_id": jid, "lease_epoch": ep + 1})
        con.commit()
        return out
    except Exception:
        con.rollback()
        raise


def advance(con, job_id: str, *, lease_epoch: int, state: str,
            result_ref: str = "") -> bool:
    """推进阶段（extracting/adjudicating/committing）；须持有效 epoch。"""
    if state not in ("extracting", "adjudicating", "committing"):
        raise ValueError("advance 只接受 extracting/adjudicating/committing")
    cur = con.execute(
        "UPDATE review_jobs SET state=?, result_ref=?, updated_at=? "
        "WHERE job_id=? AND lease_epoch=? AND state NOT IN ('done','validated_empty','needs_review')",
        (state, result_ref, time.time(), job_id, lease_epoch))
    con.commit()
    return cur.rowcount == 1


def commit_review(con, job_id: str, *, lease_epoch: int, committed_seq: int,
                  result_ref: str = "") -> bool:
    """**短事务**：job→done/validated_empty + 水位推进（仅此处推进水位）。"""
    now = time.time()
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute("SELECT channel,principal_id,session_id,state FROM review_jobs "
                          "WHERE job_id=? AND lease_epoch=?", (job_id, lease_epoch)).fetchone()
        if not row or row[3] in ("done", "validated_empty"):
            con.rollback()
            return False
        scope = _scope(row[0], row[1], row[2])
        con.execute("UPDATE review_jobs SET state=?, result_ref=?, lease_owner='', lease_until=NULL, "
                    "updated_at=?, committed_at=? WHERE job_id=?",
                    ("done", result_ref, now, now, job_id))
        con.execute(
            "INSERT INTO review_watermarks(scope_key,committed_seq,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(scope_key) DO UPDATE SET committed_seq=MAX(committed_seq,excluded.committed_seq),"
            "updated_at=excluded.updated_at",
            (scope, int(committed_seq), now))
        con.commit()
        return True
    except Exception:
        con.rollback()
        raise


def mark_validated_empty(con, job_id: str, *, lease_epoch: int, committed_seq: int) -> bool:
    """validated_empty 是**明确成功**（同样推进水位）。"""
    now = time.time()
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute("SELECT channel,principal_id,session_id FROM review_jobs "
                          "WHERE job_id=? AND lease_epoch=?", (job_id, lease_epoch)).fetchone()
        if not row:
            con.rollback()
            return False
        scope = _scope(row[0], row[1], row[2])
        con.execute("UPDATE review_jobs SET state='validated_empty', lease_owner='', "
                    "lease_until=NULL, updated_at=?, committed_at=? WHERE job_id=?",
                    (now, now, job_id))
        con.execute(
            "INSERT INTO review_watermarks(scope_key,committed_seq,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(scope_key) DO UPDATE SET committed_seq=MAX(committed_seq,excluded.committed_seq),"
            "updated_at=excluded.updated_at", (scope, int(committed_seq), now))
        con.commit()
        return True
    except Exception:
        con.rollback()
        raise


def schedule_retry(con, job_id: str, *, lease_epoch: int, error_code: str = "",
                   retry_at: float | None = None, permanent: bool = False) -> str:
    """可恢复 → retry_wait（**水位不动**）；不可恢复 → needs_review。"""
    state = "needs_review" if permanent else "retry_wait"
    cur = con.execute(
        "UPDATE review_jobs SET state=?, last_error_code=?, next_retry_at=?, lease_owner='', "
        "lease_until=NULL, updated_at=? WHERE job_id=? AND lease_epoch=?",
        (state, error_code, retry_at, time.time(), job_id, lease_epoch))
    con.commit()
    return state if cur.rowcount == 1 else "stale"


def recover_expired(con, *, now: float | None = None) -> int:
    """过期租约 → retry_wait（先核对结果，不直接重发）。"""
    now = time.time() if now is None else now
    cur = con.execute(
        "UPDATE review_jobs SET state='retry_wait', last_error_code='lease_expired', "
        "lease_owner='', lease_until=NULL, updated_at=? "
        "WHERE state IN ('leased','extracting','adjudicating','committing') "
        "AND lease_until IS NOT NULL AND lease_until<?", (now, now))
    con.commit()
    return cur.rowcount


def watermark(con, *, channel: str, principal_id: str = "", session_id: str = "") -> int:
    row = con.execute("SELECT committed_seq FROM review_watermarks WHERE scope_key=?",
                      (_scope(channel, principal_id, session_id),)).fetchone()
    return int(row[0]) if row else 0


def status_summary(con) -> dict:
    rows = con.execute("SELECT state, COUNT(*) FROM review_jobs GROUP BY state").fetchall()
    return {s: n for s, n in rows}
