"""QQ watch capture: silent OneBot v11 receiver + local rule prefilter.

Silent by design: watch mode never sends frames; only explicit subcommands
(--list-groups) send OneBot API requests (no messages).
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re
import sys
import time

import websockets

BASE = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE / "config" / "qqwatch.json"
CAND_DIR = BASE / "cache" / "qqwatch"

DEFAULT_CONFIG = {
    "ws_url": "ws://127.0.0.1:3001",
    "token": "yhlz2026",
    "groups": [],          # whitelist group ids; empty => observe all (log only)
    "self_id": "2258374446",
    "min_chars": 60,       # candidate if text >= min_chars
    "trusted_users": [],   # extra signal source uins
    "log_all": True,       # record every whitelist message (for stats), candidates flagged
}

URL_RE = re.compile(r"https?://\S+")
CODE_RE = re.compile(r"```|[\w\s]{20,}[;{}<>\[\]()=]|^\s{4,}\S", re.M)
MISC_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", flags=re.UNICODE)


def _log(*parts) -> None:
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] " + " ".join(str(p) for p in parts)
    d = BASE / "cache" / "qqwatch"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "watcher.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        print(line, flush=True)
    except Exception:
        pass


def load_config() -> dict:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def extract_text(event: dict) -> str:
    """Segment-array or string message -> plain text (image urls kept inline)."""
    msg = event.get("message")
    if isinstance(msg, str):
        return msg
    if isinstance(msg, list):
        parts = []
        for seg in msg:
            if not isinstance(seg, dict):
                continue
            t = seg.get("type")
            d = seg.get("data") or {}
            if t == "text":
                parts.append(d.get("text", ""))
            elif t == "image":
                parts.append(f"[图:{d.get('url', '')}]")
            elif t == "face":
                parts.append("[表情]")
            elif t == "at":
                parts.append("@" + str(d.get("qq", "")))
            elif t == "reply":
                parts.append(f"[引用:{d.get('text', '')[:40]}]")
        return "".join(parts)
    return ""


def is_candidate(text: str, cfg: dict, user_id: str) -> bool:
    """Local rule prefilter: length / code-like / links / trusted source."""
    if not text:
        return False
    if user_id in (cfg.get("trusted_users") or []):
        return True
    t = text.strip()
    if len(t) >= cfg.get("min_chars", 60):
        return True
    if URL_RE.search(t):
        return True
    if CODE_RE.search(t):
        return True
    return False


def classify(text: str) -> list[str]:
    tags = []
    if URL_RE.search(text):
        tags.append("link")
    if CODE_RE.search(text):
        tags.append("code")
    if len(text) >= 80:
        tags.append("long")
    return tags or ["short"]


class QqWatcher:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.seen: set[str] = set()
        self._next_id = 0
        self._pending: dict[str, asyncio.Future] = {}

    async def connect(self) -> websockets.WebSocketClientProtocol:
        headers = {}
        if self.cfg.get("token"):
            headers["Authorization"] = "Bearer " + self.cfg["token"]
        _log("connecting", self.cfg["ws_url"])
        ws = await websockets.connect(self.cfg["ws_url"], additional_headers=headers)
        _log("connected")
        return ws

    async def send_api(self, ws, action: str, params: dict, echo: str) -> dict:
        await ws.send(json.dumps({"action": action, "params": params, "echo": echo}))
        while True:
            raw = await ws.recv()
            ev = json.loads(raw)
            if ev.get("echo") == echo:
                return ev

    async def handle(self, ev: dict) -> bool:
        if ev.get("post_type") != "message":
            return False
        if ev.get("message_type") != "group":
            return False
        gid = str(ev.get("group_id", ""))
        cfg_groups = [str(g) for g in self.cfg.get("groups") or []]
        if cfg_groups and gid not in cfg_groups:
            return False
        uid = str(ev.get("user_id", ""))
        if uid == str(self.cfg.get("self_id", "")):
            return False
        text = extract_text(ev)
        if not text.strip():
            return False
        mid = str(ev.get("message_id", ""))
        if mid in self.seen:
            return False
        self.seen.add(mid)
        if len(self.seen) > 5000:
            self.seen = set(list(self.seen)[-3000:])
        rec = {
            "ts": int(time.time()),
            "group_id": gid,
            "user_id": uid,
            "nickname": (ev.get("sender") or {}).get("card") or (ev.get("sender") or {}).get("nickname", ""),
            "text": text,
            "candidate": is_candidate(text, self.cfg, uid),
            "tags": classify(text),
        }
        CAND_DIR.mkdir(parents=True, exist_ok=True)
        f = CAND_DIR / ("all.jsonl" if rec["candidate"] else "_skip.jsonl")
        with open(f, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if rec["candidate"] or self.cfg.get("log_all"):
            _log("msg", f"g{gid}", uid, "cand" if rec["candidate"] else "skip", text[:60].replace("\n", " "))
        return rec["candidate"]

    async def watch(self, once_seconds: float = 0) -> int:
        """Continuous silent receive. Never sends frames here."""
        count = 0
        while True:
            try:
                async with await self.connect() as ws:
                    deadline = time.time() + once_seconds if once_seconds else 0
                    while True:
                        if once_seconds and time.time() > deadline:
                            return count
                        raw = await asyncio.wait_for(ws.recv(), timeout=300)
                        ev = json.loads(raw)
                        try:
                            if await self.handle(ev):
                                count += 1
                        except Exception as e:
                            _log("handler err", e)
            except Exception as e:
                _log("conn err", e, "retry in 5s")
                if once_seconds:
                    return count
                await asyncio.sleep(5)

    async def list_groups(self) -> None:
        async with await self.connect() as ws:
            resp = await self.send_api(ws, "get_group_list", {}, "g1")
            groups = resp.get("data") or []
            for g in groups:
                print(f"{g.get('group_id')}\t{g.get('group_name')}\t{g.get('member_count')}人")
            print(f"-- total {len(groups)} groups")


def main() -> int:
    cfg = load_config()
    CAND_DIR.mkdir(parents=True, exist_ok=True)
    w = QqWatcher(cfg)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "watch"
    if cmd == "list-groups":
        asyncio.run(w.list_groups())
    elif cmd == "once":
        n = asyncio.run(w.watch(once_seconds=float(sys.argv[2]) if len(sys.argv) > 2 else 60))
        _log("once done, candidates:", n)
    else:
        asyncio.run(w.watch())
    return 0


if __name__ == "__main__":
    try:
        sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
    except Exception:
        pass
    sys.exit(main())
