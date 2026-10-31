"""Durable outage notices for QQ Bridge Lite (P2).

Fixed texts only; unique key ``bot_uin + outage_id + lost/recovered +
recipient``. A lost notice is attempted before its recovered notice; if a lost
notice is stuck pending beyond ``release_s`` the recovered notice is released
first (ordering wait must not block forever). Statuses: pending / sending /
sent / unknown / failed. ``unknown`` is never resent.
"""
from __future__ import annotations

import json
import pathlib
import time

NOTICE_TEXTS = {
    "lost": "【系统检测到异常，元亨丢失】",
    "recovered": "【元亨已接续】",
    # 账号监管（2026-10-10）：被踢下线 / 自动重登 / 需要扫码。
    "account_lost": "【元亨号被下线】正在尝试自动重新登录…",
    "account_recovered": "【元亨号已重新上线】",
    "account_needs_scan": "【元亨号需扫码】自动重登未成功，请在电脑端重新扫码登录"
                          "（工作台「元亨 QQ」卡片）。",
}
_ACCOUNT_LOST_KINDS = ("lost", "account_lost", "account_needs_scan")
_ACCOUNT_RECOVERED_KINDS = ("recovered", "account_recovered")
TERMINAL = ("sent", "unknown", "failed")


class NoticeStore:
    def __init__(self, path, *, bot_uin: str = "", release_s: float = 10.0,
                 max_retries: int = 2, retry_backoff_s: float = 5.0) -> None:
        self.path = pathlib.Path(path)
        self.bot_uin = str(bot_uin)
        self.release_s = float(release_s)
        self.max_retries = int(max_retries)
        self.retry_backoff_s = float(retry_backoff_s)

    # ---- persistence -----------------------------------------------------
    def _load(self) -> list[dict]:
        try:
            raw = self.path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        out = []
        for line in raw:
            try:
                item = json.loads(line)
                if isinstance(item, dict) and item.get("notice_id"):
                    out.append(item)
            except Exception:
                continue
        return out

    def _save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n"
                               for i in items), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def notice_id(bot_uin: str, outage_id: str, kind: str,
                  recipient: str) -> str:
        return f"{bot_uin}:{outage_id}:{kind}:{recipient}"

    # ---- api -------------------------------------------------------------
    def create(self, *, outage_id: str, kind: str, recipient: str,
               now: float | None = None) -> dict:
        now = time.time() if now is None else now
        nid = self.notice_id(self.bot_uin, outage_id, kind, recipient)
        items = self._load()
        for item in items:
            if item.get("notice_id") == nid:
                return item
        record = {
            "notice_id": nid, "bot_uin": self.bot_uin,
            "outage_id": outage_id, "kind": kind,
            "recipient": str(recipient), "text": NOTICE_TEXTS.get(kind, ""),
            "status": "pending", "attempts": 0, "created_at": now,
            "updated_at": now, "last_error": "",
        }
        items.append(record)
        self._save(items)
        return record

    def mark(self, notice_id: str, status: str, *, error: str = "",
             now: float | None = None) -> dict:
        now = time.time() if now is None else now
        items = self._load()
        for item in items:
            if item.get("notice_id") == notice_id:
                item["status"] = status
                item["updated_at"] = now
                item["last_error"] = str(error)[:120]
                if status in ("sending", "pending"):
                    item["attempts"] = int(item.get("attempts", 0)) + 1
                self._save(items)
                return item
        return {}

    def get(self, notice_id: str) -> dict:
        for item in self._load():
            if item.get("notice_id") == notice_id:
                return item
        return {}

    def pending(self) -> list[dict]:
        return [i for i in self._load() if i.get("status") == "pending"]

    def summary(self) -> dict:
        items = self._load()
        counts: dict[str, int] = {}
        for item in items:
            key = str(item.get("status"))
            counts[key] = counts.get(key, 0) + 1
        return {"total": len(items), "by_status": counts,
                "pending": [i.get("notice_id") for i in items
                            if i.get("status") == "pending"]}

    def next_to_send(self, now: float | None = None) -> dict | None:
        """Lost first; recovered waits for its lost notice or the release."""
        now = time.time() if now is None else now
        items = self._load()
        pending = [i for i in items if i.get("status") == "pending"]
        if not pending:
            return None
        lost = [i for i in pending if i.get("kind") in _ACCOUNT_LOST_KINDS]
        recovered = [i for i in pending
                     if i.get("kind") in _ACCOUNT_RECOVERED_KINDS]
        for item in lost:
            attempts = int(item.get("attempts", 0))
            age = now - float(item.get("updated_at") or item.get("created_at") or 0)
            if attempts == 0 and age < self.release_s:
                return item
            if 0 < attempts <= self.max_retries and age >= self.retry_backoff_s:
                return item
        for item in recovered:
            outage_id = item.get("outage_id")
            related = [i for i in items
                       if i.get("outage_id") == outage_id
                       and i.get("kind") == "lost"]
            if not related:
                return item
            lost_item = related[0]
            if lost_item.get("status") in TERMINAL:
                return item
            age = now - float(lost_item.get("created_at") or 0)
            if age >= self.release_s:
                return item
        return lost[0] if lost else None
