"""QQ sticker library for Lite (P4, 2026-10-06).

Content-addressed assets with exact sha256 dedupe; a vision judge decides
accept / review / reject into a strict schema; retrieval only ever returns
candidate asset ids (never local paths); sending enforces scope, cooldown and
one-image-per-reply. No torch/CUDA import here: vision is an injected
capability, unavailable by default (assets stay pending).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
import time
import uuid

ACCEPT_CONFIDENCE = 0.85
REVIEW_CONFIDENCE = 0.60
MAX_ASSET_BYTES = 8 * 1024 * 1024
SEND_COOLDOWN_S = 600.0
RECENT_AVOID = 5
ALLOWED_RESULT_KEYS = {
    "decision", "is_reusable_sticker", "confidence", "description",
    "keywords", "emotion", "use_when", "avoid_when", "ocr_text",
    "contains_private_info",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
  asset_id TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL UNIQUE,
  format TEXT NOT NULL DEFAULT '',
  size INTEGER NOT NULL DEFAULT 0,
  rel_path TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  model_version TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  recognized_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS asset_sources (
  asset_id TEXT NOT NULL,
  source_message_id TEXT NOT NULL DEFAULT '',
  source_kind TEXT NOT NULL DEFAULT '',
  source_id TEXT NOT NULL DEFAULT '',
  scope TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (asset_id, source_message_id, source_kind, source_id)
);
CREATE TABLE IF NOT EXISTS asset_tags (
  asset_id TEXT PRIMARY KEY,
  keywords TEXT NOT NULL DEFAULT '[]',
  emotion TEXT NOT NULL DEFAULT '[]',
  use_when TEXT NOT NULL DEFAULT '[]',
  avoid_when TEXT NOT NULL DEFAULT '[]',
  description TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS asset_usage (
  asset_id TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT '',
  last_used REAL NOT NULL DEFAULT 0,
  confirmed_count INTEGER NOT NULL DEFAULT 0,
  unknown_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (asset_id, scope)
);
CREATE TABLE IF NOT EXISTS recognition_jobs (
  content_hash TEXT PRIMARY KEY,
  message_id TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
"""


class NullVision:
    """Default: no verified pixel-capable backend -> assets stay pending."""

    available = False

    def judge(self, path: str):
        return None


def validate_result(raw: dict) -> dict | None:
    """Strict schema check; unknown keys or bad types are rejected."""
    if not isinstance(raw, dict):
        return None
    if set(raw.keys()) - ALLOWED_RESULT_KEYS:
        return None
    decision = raw.get("decision")
    if decision not in ("accept", "reject", "unsure"):
        return None
    try:
        confidence = float(raw.get("confidence", -1))
    except Exception:
        return None
    if not 0 <= confidence <= 1:
        return None
    def _list(key, cap):
        value = raw.get(key) or []
        if not isinstance(value, list):
            return None
        out = []
        for item in value:
            if not isinstance(item, str) or len(item) > 20:
                return None
            out.append(item[:20])
        return out[:cap]
    keywords = _list("keywords", 8)
    emotion = _list("emotion", 8)
    use_when = _list("use_when", 8)
    avoid_when = _list("avoid_when", 8)
    if keywords is None or emotion is None or use_when is None \
            or avoid_when is None:
        return None
    if not 3 <= len(keywords) <= 8:
        return None
    description = raw.get("description") or ""
    if not isinstance(description, str) or len(description) > 120:
        return None
    return {
        "decision": decision,
        "is_reusable_sticker": bool(raw.get("is_reusable_sticker")),
        "confidence": confidence,
        "description": description,
        "keywords": keywords,
        "emotion": emotion,
        "use_when": use_when,
        "avoid_when": avoid_when,
        "contains_private_info": bool(raw.get("contains_private_info")),
    }


def decide_status(result: dict) -> str:
    conf = float(result.get("confidence") or 0)
    if result.get("decision") != "accept" or not result.get(
            "is_reusable_sticker"):
        return "rejected"
    if result.get("contains_private_info"):
        return "rejected"
    if conf >= ACCEPT_CONFIDENCE:
        return "active"
    if conf >= REVIEW_CONFIDENCE:
        return "review"
    return "rejected"


class StickerStore:
    def __init__(self, db_path, *, media_dir, vision=None,
                 max_bytes: int = MAX_ASSET_BYTES) -> None:
        self.db_path = pathlib.Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_dir = pathlib.Path(media_dir)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.vision = vision if vision is not None else NullVision()
        self.max_bytes = int(max_bytes)
        con = sqlite3.connect(str(self.db_path), timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(_SCHEMA)
        con.commit()
        con.close()

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=15)
        con.row_factory = sqlite3.Row
        return con

    # ---- ingest ----------------------------------------------------------
    def ingest(self, path: str, *, source_message_id: str = "",
               source_kind: str = "", source_id: str = "", scope: str = "",
               now: float | None = None) -> dict:
        now = time.time() if now is None else now
        p = pathlib.Path(path)
        try:
            data = p.read_bytes()
        except Exception:
            return {"status": "error", "error": "unreadable"}
        if len(data) > self.max_bytes:
            return {"status": "error", "error": "too_large"}
        sha = hashlib.sha256(data).hexdigest()
        con = self._con()
        try:
            row = con.execute("SELECT * FROM assets WHERE sha256=?",
                              (sha,)).fetchone()
            if row:
                asset_id = row["asset_id"]
                con.execute(
                    "INSERT OR IGNORE INTO asset_sources(asset_id,"
                    "source_message_id,source_kind,source_id,scope) "
                    "VALUES(?,?,?,?,?)",
                    (asset_id, str(source_message_id), str(source_kind),
                     str(source_id), str(scope)))
                con.commit()
                return {"status": "duplicate", "asset_id": asset_id,
                        "sha256": sha, "asset_status": row["status"]}
            asset_id = "stk_" + uuid.uuid4().hex[:12]
            ext = p.suffix.lstrip(".").lower() or "jpg"
            rel = pathlib.Path(sha[:2]) / f"{sha}.{ext}"
            dest = self.media_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            con.execute(
                "INSERT INTO assets(asset_id,sha256,format,size,rel_path,"
                "status,created_at) VALUES(?,?,?,?,?,'pending',?)",
                (asset_id, sha, ext, len(data), str(rel), now))
            con.execute(
                "INSERT OR IGNORE INTO asset_sources(asset_id,"
                "source_message_id,source_kind,source_id,scope) "
                "VALUES(?,?,?,?,?)",
                (asset_id, str(source_message_id), str(source_kind),
                 str(source_id), str(scope)))
            con.execute(
                "INSERT OR IGNORE INTO recognition_jobs(content_hash,"
                "message_id,state,created_at,updated_at) VALUES(?,?,"
                "'pending',?,?)", (sha, str(source_message_id), now, now))
            con.commit()
        finally:
            con.close()
        return {"status": "new", "asset_id": asset_id, "sha256": sha,
                "asset_status": "pending"}

    # ---- recognition -----------------------------------------------------
    def recognize(self, asset_id: str, raw_result: dict | None,
                  *, model_version: str = "unknown") -> str:
        con = self._con()
        try:
            row = con.execute("SELECT * FROM assets WHERE asset_id=?",
                              (asset_id,)).fetchone()
            if not row:
                return "missing"
            if raw_result is None:
                con.execute(
                    "UPDATE recognition_jobs SET state='pending', attempts="
                    "attempts+1, updated_at=? WHERE content_hash=?",
                    (time.time(), row["sha256"]))
                con.commit()
                return "pending"
            result = validate_result(raw_result)
            if result is None:
                con.execute(
                    "UPDATE recognition_jobs SET state='failed', error="
                    "'invalid_schema', attempts=attempts+1, updated_at=? "
                    "WHERE content_hash=?", (time.time(), row["sha256"]))
                con.commit()
                return "rejected_schema"
            status = decide_status(result)
            con.execute(
                "UPDATE assets SET status=?, model_version=?, recognized_at=? "
                "WHERE asset_id=?", (status, str(model_version)[:60],
                                     time.time(), asset_id))
            con.execute(
                "INSERT OR REPLACE INTO asset_tags(asset_id,keywords,emotion,"
                "use_when,avoid_when,description,confidence) "
                "VALUES(?,?,?,?,?,?,?)",
                (asset_id, json.dumps(result["keywords"], ensure_ascii=False),
                 json.dumps(result["emotion"], ensure_ascii=False),
                 json.dumps(result["use_when"], ensure_ascii=False),
                 json.dumps(result["avoid_when"], ensure_ascii=False),
                 result["description"], result["confidence"]))
            con.execute(
                "UPDATE recognition_jobs SET state='finished', updated_at=? "
                "WHERE content_hash=?", (time.time(), row["sha256"]))
            con.commit()
            return status
        finally:
            con.close()

    # ---- retrieval / send ------------------------------------------------
    def search(self, scope: str, text: str, limit: int = 5) -> list[dict]:
        tokens = [t for t in str(text).replace("，", " ").replace("。", " ")
                  .replace("！", " ").replace("？", " ").split() if t]
        con = self._con()
        try:
            rows = con.execute(
                "SELECT a.asset_id, a.rel_path, t.keywords, t.emotion, "
                "t.description, "
                "(SELECT group_concat(s.scope) FROM asset_sources s WHERE "
                " s.asset_id=a.asset_id) AS scopes "
                "FROM assets a LEFT JOIN asset_tags t ON t.asset_id=a.asset_id "
                "WHERE a.status='active'").fetchall()
        finally:
            con.close()
        scored = []
        for row in rows:
            scopes = str(row["scopes"] or "")
            if scopes and "global" not in scopes and str(scope) not in scopes:
                continue
            try:
                keywords = json.loads(row["keywords"] or "[]")
                emotion = json.loads(row["emotion"] or "[]")
            except Exception:
                keywords, emotion = [], []
            hay = " ".join(keywords + emotion + [row["description"] or ""])
            text_s = str(text)
            score = 0
            for word in keywords + emotion:
                if word and word in text_s:
                    score += 2
            for tok in tokens:
                if tok and tok in hay:
                    score += 1
                for word in keywords:
                    if tok and word and word in tok:
                        score += 1
            if score or not tokens:
                scored.append((score, row, keywords))
        scored.sort(key=lambda x: -x[0])
        out = []
        for score, row, keywords in scored[:max(1, int(limit))]:
            out.append({"asset_id": row["asset_id"], "score": score,
                        "description": row["description"] or "",
                        "keywords": keywords})
        return out

    def resolve(self, asset_id: str, scope: str) -> str:
        con = self._con()
        try:
            row = con.execute(
                "SELECT a.*, (SELECT group_concat(scope) FROM asset_sources s "
                "WHERE s.asset_id=a.asset_id) AS scopes FROM assets a WHERE "
                "a.asset_id=?", (str(asset_id),)).fetchone()
        finally:
            con.close()
        if not row or row["status"] != "active":
            return ""
        scopes = str(row["scopes"] or "")
        if scopes and "global" not in scopes and str(scope) not in scopes:
            return ""
        path = self.media_dir / row["rel_path"]
        return str(path) if path.exists() else ""

    def can_send(self, asset_id: str, scope: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        con = self._con()
        try:
            row = con.execute(
                "SELECT last_used FROM asset_usage WHERE asset_id=? AND "
                "scope=?", (asset_id, str(scope))).fetchone()
        finally:
            con.close()
        if row and now - float(row["last_used"]) < SEND_COOLDOWN_S:
            return False
        return True

    def record_use(self, asset_id: str, scope: str, status: str = "confirmed",
                   now: float | None = None) -> None:
        now = time.time() if now is None else now
        confirmed = 1 if status == "confirmed" else 0
        unknown = 1 if status == "unknown" else 0
        con = self._con()
        try:
            con.execute(
                "INSERT INTO asset_usage(asset_id,scope,last_used,"
                "confirmed_count,unknown_count) VALUES(?,?,?,?,?) "
                "ON CONFLICT(asset_id,scope) DO UPDATE SET last_used=?, "
                "confirmed_count=confirmed_count+?, "
                "unknown_count=unknown_count+?",
                (asset_id, str(scope), now, confirmed, unknown, now,
                 confirmed, unknown))
            con.commit()
        finally:
            con.close()

    def recent(self, scope: str, limit: int = RECENT_AVOID) -> list[str]:
        con = self._con()
        try:
            rows = con.execute(
                "SELECT asset_id FROM asset_usage WHERE scope=? ORDER BY "
                "last_used DESC LIMIT ?", (str(scope), int(limit))).fetchall()
        finally:
            con.close()
        return [str(r["asset_id"]) for r in rows]

    def summary(self) -> dict:
        con = self._con()
        try:
            states = con.execute("SELECT status, COUNT(*) n FROM assets "
                                 "GROUP BY status").fetchall()
            jobs = con.execute("SELECT state, COUNT(*) n FROM recognition_jobs "
                               "GROUP BY state").fetchall()
        finally:
            con.close()
        return {"assets": {r["status"]: r["n"] for r in states},
                "jobs": {r["state"]: r["n"] for r in jobs}}


def vision_available() -> bool:
    """True only when a pixel-capable backend is explicitly configured."""
    import os

    return bool(os.getenv("YHLZ_QQ_VISION_CMD", "").strip())
