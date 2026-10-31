"""Persistent QQ group history for Lite (P4, 2026-10-06).

Per (bot_uin, group_id) partition; message_id dedupe; insert happens before
reply/rate-limit/LLM so context survives silence. Window = latest N messages
strictly before the current one. Extractive summary keeps source message ids
and never claims unavailability is completeness.

Backfill via NapCat's get_group_msg_history is a probe-able extension: when
unsupported the store reports partial completeness instead of faking a full
window.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS group_messages (
  bot_uin     TEXT NOT NULL,
  group_id    TEXT NOT NULL,
  message_id  TEXT NOT NULL,
  seq         INTEGER NOT NULL,
  sender_id   TEXT NOT NULL DEFAULT '',
  sender_name TEXT NOT NULL DEFAULT '',
  text        TEXT NOT NULL DEFAULT '',
  media       TEXT NOT NULL DEFAULT '[]',
  is_bot      INTEGER NOT NULL DEFAULT 0,
  at          REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (bot_uin, group_id, message_id)
);
CREATE INDEX IF NOT EXISTS ix_group_seq ON group_messages(bot_uin, group_id, seq);
"""


class GroupHistoryStore:
    def __init__(self, path, *, bot_uin: str = "", turns: int = 50) -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.bot_uin = str(bot_uin)
        self.turns = int(turns)
        con = sqlite3.connect(str(self.path), timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(_SCHEMA)
        con.commit()
        con.close()

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=15)
        con.row_factory = sqlite3.Row
        return con

    # ---- write -----------------------------------------------------------
    def add(self, *, group_id: str, message_id: str, sender_id: str,
            text: str, media: list | None = None, sender_name: str = "",
            is_bot: bool = False, at: float | None = None) -> int:
        """Insert one message; returns its seq (0 when deduplicated)."""
        at = time.time() if at is None else float(at)
        media_json = json.dumps(media or [], ensure_ascii=False)
        con = self._con()
        try:
            row = con.execute(
                "SELECT seq FROM group_messages WHERE bot_uin=? AND group_id=? "
                "AND message_id=?", (self.bot_uin, str(group_id),
                                     str(message_id))).fetchone()
            if row:
                return 0
            nxt = con.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM group_messages "
                "WHERE bot_uin=? AND group_id=?", (self.bot_uin,
                                                   str(group_id))).fetchone()[0]
            con.execute(
                "INSERT INTO group_messages(bot_uin,group_id,message_id,seq,"
                "sender_id,sender_name,text,media,is_bot,at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (self.bot_uin, str(group_id), str(message_id), int(nxt),
                 str(sender_id), str(sender_name)[:60], str(text)[:2000],
                 media_json, 1 if is_bot else 0, at))
            con.commit()
            return int(nxt)
        finally:
            con.close()

    def add_many(self, records: list[dict]) -> int:
        """Backfill merge; dedupe by message_id; returns inserted count."""
        inserted = 0
        con = self._con()
        try:
            for rec in records:
                mid = str(rec.get("message_id") or "")
                if not mid:
                    continue
                exists = con.execute(
                    "SELECT 1 FROM group_messages WHERE bot_uin=? AND "
                    "group_id=? AND message_id=?",
                    (self.bot_uin, str(rec.get("group_id", "")), mid)).fetchone()
                if exists:
                    continue
                nxt = con.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM group_messages "
                    "WHERE bot_uin=? AND group_id=?",
                    (self.bot_uin, str(rec.get("group_id", "")))).fetchone()[0]
                con.execute(
                    "INSERT INTO group_messages(bot_uin,group_id,message_id,seq,"
                    "sender_id,sender_name,text,media,is_bot,at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (self.bot_uin, str(rec.get("group_id", "")), mid, int(nxt),
                     str(rec.get("sender_id", "")),
                     str(rec.get("sender_name", ""))[:60],
                     str(rec.get("text", ""))[:2000],
                     json.dumps(rec.get("media") or [], ensure_ascii=False),
                     1 if rec.get("is_bot") else 0,
                     float(rec.get("at") or time.time())))
                inserted += 1
            con.commit()
        finally:
            con.close()
        return inserted

    # ---- read ------------------------------------------------------------
    def window(self, group_id: str, *, before_seq: int | None = None,
               limit: int | None = None) -> list[dict]:
        limit = int(limit or self.turns)
        con = self._con()
        try:
            if before_seq is None:
                before_seq = con.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM group_messages "
                    "WHERE bot_uin=? AND group_id=?",
                    (self.bot_uin, str(group_id))).fetchone()[0]
            rows = con.execute(
                "SELECT * FROM group_messages WHERE bot_uin=? AND group_id=? "
                "AND seq < ? ORDER BY seq DESC LIMIT ?",
                (self.bot_uin, str(group_id), int(before_seq), limit)).fetchall()
        finally:
            con.close()
        return [dict(r) for r in reversed(rows)]

    def count(self, group_id: str) -> int:
        con = self._con()
        try:
            return int(con.execute(
                "SELECT COUNT(*) FROM group_messages WHERE bot_uin=? AND "
                "group_id=?", (self.bot_uin, str(group_id))).fetchone()[0])
        finally:
            con.close()

    def all_messages(self, limit: int = 50000) -> list[dict]:
        """All stored messages (profile building; small local volumes)."""
        con = self._con()
        try:
            rows = con.execute(
                "SELECT * FROM group_messages WHERE bot_uin=? ORDER BY at, seq "
                "LIMIT ?", (self.bot_uin, int(limit))).fetchall()
        finally:
            con.close()
        return [dict(r) for r in rows]

    # ---- backfill contract ----------------------------------------------
    def backfill_supported(self) -> bool:
        """NapCat extension; unverified locally -> False until probed."""
        return False

    def merge_backfill(self, records: list[dict]) -> dict:
        inserted = self.add_many(records)
        return {"supported": self.backfill_supported(),
                "requested": len(records), "inserted": inserted}

    # ---- summary ---------------------------------------------------------
    @staticmethod
    def summarize(window: list[dict], *, max_facts: int = 10) -> str:
        if not window:
            return "（暂无可用群上下文）"
        lines = [f"[群上下文摘要 {len(window)} 条，均带来源ID]"]
        seen_speakers: dict[str, int] = {}
        questions: list[str] = []
        for msg in window:
            speaker = ("元亨" if msg.get("is_bot")
                       else str(msg.get("sender_name") or msg.get("sender_id")))
            text = " ".join(str(msg.get("text") or "").split())
            if not text:
                media = msg.get("media") or []
                text = f"[媒体×{len(media)}]" if media else ""
            if not text:
                continue
            if text.endswith(("?", "？")) and not msg.get("is_bot"):
                questions.append(f"[{msg.get('message_id')}] {speaker}: {text[:80]}")
            n = seen_speakers.get(speaker, 0)
            if n < 2 and len(lines) <= max_facts:
                seen_speakers[speaker] = n + 1
                lines.append(f"[{msg.get('message_id')}] {speaker}: {text[:100]}")
        if questions:
            lines.append("未回答/待确认问题：" + "；".join(questions[-3:]))
        return "\n".join(lines[:max_facts + 2])

    def context_block(self, group_id: str, *, before_seq: int | None = None,
                      raw: int = 8) -> dict:
        """summary + recent raw + completeness, strictly before current."""
        win = self.window(group_id, before_seq=before_seq)
        summary = self.summarize(win)
        recent = win[-raw:]
        raw_lines = []
        for msg in recent:
            who = ("元亨" if msg.get("is_bot")
                   else str(msg.get("sender_name") or msg.get("sender_id")))
            raw_lines.append(f"{who}: {str(msg.get('text') or '')[:200]}")
        complete = len(win) >= self.turns
        return {
            "summary": summary,
            "recent": "\n".join(raw_lines),
            "source_ids": [str(m.get("message_id")) for m in win],
            "senders": sorted({str(m.get("sender_id")) for m in win
                               if not m.get("is_bot")
                               and str(m.get("sender_id") or "").isdigit()}),
            "count": len(win),
            "completeness": "full" if complete
            else f"partial {len(win)}/{self.turns}",
        }
