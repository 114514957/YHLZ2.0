"""Persistent QQ dev job store (P3, 2026-10-06).

SQLite, profile-scoped: never shares cache/dev/state.json with Full. Job
states: accepted -> running -> awaiting_owner / completed / failed /
interrupted. Reports carry a monotonically increasing result_version so the
bridge can relay each report exactly once to QQ (unknown delivery is never
blindly resent; the version is marked reported either way).

``backend`` records the executor; since ledger 0797 it is always ``dsh``
(harness). Historical rows written as ``opencode`` still execute — the worker
routes them to harness.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import time
import uuid

ACTIVE_STATES = ("accepted", "running", "awaiting_owner")
JOB_STATES = ("accepted", "running", "awaiting_owner", "completed", "failed",
              "interrupted")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dev_jobs (
  job_id            TEXT PRIMARY KEY,
  owner_id          TEXT NOT NULL,
  channel           TEXT NOT NULL DEFAULT '',
  target_project    TEXT NOT NULL DEFAULT '',
  workspace         TEXT NOT NULL DEFAULT '',
  shared_workspace  INTEGER NOT NULL DEFAULT 0,
  branch            TEXT NOT NULL DEFAULT '',
  backend           TEXT NOT NULL DEFAULT 'dsh',
  session_id        TEXT NOT NULL DEFAULT '',
  state             TEXT NOT NULL DEFAULT 'accepted',
  task              TEXT NOT NULL DEFAULT '',
  question          TEXT NOT NULL DEFAULT '',
  answer            TEXT NOT NULL DEFAULT '',
  report            TEXT NOT NULL DEFAULT '',
  base_head         TEXT NOT NULL DEFAULT '',
  base_status       TEXT NOT NULL DEFAULT '',
  changed_files     TEXT NOT NULL DEFAULT '[]',
  commit_message    TEXT NOT NULL DEFAULT '',
  commit_hash       TEXT NOT NULL DEFAULT '',
  pushed            INTEGER NOT NULL DEFAULT 0,
  execution_id      TEXT NOT NULL DEFAULT '',
  pid               INTEGER NOT NULL DEFAULT 0,
  pid_create_time   REAL NOT NULL DEFAULT 0,
  log_path          TEXT NOT NULL DEFAULT '',
  result_version    INTEGER NOT NULL DEFAULT 0,
  reported_version  INTEGER NOT NULL DEFAULT 0,
  confirmed_snapshot TEXT NOT NULL DEFAULT '',
  error             TEXT NOT NULL DEFAULT '',
  created_at        REAL NOT NULL,
  updated_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_dev_jobs_state ON dev_jobs(state);
"""


def connect(path) -> sqlite3.Connection:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_SCHEMA)
    con.commit()
    return con


def _row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    try:
        d["changed_files"] = json.loads(d.get("changed_files") or "[]")
    except Exception:
        d["changed_files"] = []
    return d


def create(con, *, owner_id: str, channel: str, target_project: str,
           workspace: str, shared_workspace: bool, branch: str, backend: str,
           task: str, base_head: str, base_status: str,
           now: float | None = None) -> dict:
    now = time.time() if now is None else now
    job_id = "job" + time.strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4]
    con.execute(
        "INSERT INTO dev_jobs(job_id,owner_id,channel,target_project,workspace,"
        "shared_workspace,branch,backend,state,task,base_head,base_status,"
        "created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,'accepted',?,?,?,?,?)",
        (job_id, str(owner_id), str(channel), str(target_project),
         str(workspace), 1 if shared_workspace else 0, str(branch),
         str(backend), str(task), str(base_head), str(base_status), now, now))
    con.commit()
    return get(con, job_id)


def update(con, job_id: str, **fields) -> dict:
    if not fields:
        return get(con, job_id) or {}
    fields["updated_at"] = time.time()
    if "changed_files" in fields and not isinstance(fields["changed_files"], str):
        fields["changed_files"] = json.dumps(fields["changed_files"],
                                             ensure_ascii=False)
    cols = ", ".join(f"{k}=?" for k in fields)
    con.execute(f"UPDATE dev_jobs SET {cols} WHERE job_id=?",
                (*fields.values(), job_id))
    con.commit()
    return get(con, job_id) or {}


def bump_result(con, job_id: str) -> dict:
    con.execute(
        "UPDATE dev_jobs SET result_version=result_version+1, updated_at=? "
        "WHERE job_id=?", (time.time(), job_id))
    con.commit()
    return get(con, job_id) or {}


def get(con, job_id: str) -> dict | None:
    return _row(con.execute("SELECT * FROM dev_jobs WHERE job_id=?",
                            (job_id,)).fetchone())


def active(con) -> dict | None:
    q = ",".join("?" for _ in ACTIVE_STATES)
    return _row(con.execute(
        f"SELECT * FROM dev_jobs WHERE state IN ({q}) "
        "ORDER BY created_at DESC LIMIT 1", ACTIVE_STATES).fetchone())


def latest(con) -> dict | None:
    return _row(con.execute(
        "SELECT * FROM dev_jobs ORDER BY created_at DESC LIMIT 1").fetchone())


def awaiting(con, *, owner_id: str, channel: str | None = None) -> dict | None:
    if channel:
        return _row(con.execute(
            "SELECT * FROM dev_jobs WHERE state='awaiting_owner' AND "
            "owner_id=? AND channel=? ORDER BY created_at DESC LIMIT 1",
            (str(owner_id), str(channel))).fetchone())
    return _row(con.execute(
        "SELECT * FROM dev_jobs WHERE state='awaiting_owner' AND owner_id=? "
        "ORDER BY created_at DESC LIMIT 1", (str(owner_id),)).fetchone())


def pending_reports(con) -> list[dict]:
    rows = con.execute(
        "SELECT * FROM dev_jobs WHERE result_version > reported_version "
        "AND result_version > 0 ORDER BY updated_at ASC").fetchall()
    return [r for r in (_row(x) for x in rows) if r]


def mark_reported(con, job_id: str, version: int) -> None:
    con.execute(
        "UPDATE dev_jobs SET reported_version=? WHERE job_id=? AND "
        "reported_version<?", (int(version), job_id, int(version)))
    con.commit()


def running_jobs(con) -> list[dict]:
    rows = con.execute("SELECT * FROM dev_jobs WHERE state IN "
                       "('accepted','running')").fetchall()
    return [_row(r) for r in rows]


def summary(con) -> dict:
    rows = con.execute("SELECT state, COUNT(*) AS n FROM dev_jobs "
                       "GROUP BY state").fetchall()
    return {str(r["state"]): int(r["n"]) for r in rows}
