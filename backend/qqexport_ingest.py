"""Ingest QCE (qq-chat-exporter) JSON export into the watcher candidate store.

Appends to the same jsonl files the live watcher uses; the qqextract cursor
only reads new lines, so historical ingests flow through the same pipeline
(candidate -> cloud refine -> L2 knowledge) as live messages.
"""
from __future__ import annotations

import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE / "config" / "qqwatch.json"
CAND_DIR = BASE / "cache" / "qqwatch"

SELF_UIN = "2258374446"
SELF_KEY = "self_id"


def _cfg() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _clean_text(text: str) -> str:
    """Strip media placeholders / reply frames; keep real words and real links."""
    import re as _re

    t = _re.sub(r"\[(?:图片|表情|视频|文件|资源):[^\]]*\]", " ", text)
    t = _re.sub(r"\[回复[^\]]*\]", " ", t)
    t = _re.sub(r"@\S+", "", t)
    return _re.sub(r"\s+", " ", t).strip()


def extract_text(msg: dict) -> str:
    """Plain text + inline resource notes from a QCE message dict."""
    content = msg.get("content") or {}
    text = str(content.get("text") or "")
    res = content.get("resources") or []
    parts = [text]
    for r in res:
        url = (r.get("url") or "") if isinstance(r, dict) else ""
        fname = (r.get("fileName") or r.get("name") or "") if isinstance(r, dict) else ""
        if url:
            parts.append(f"[图:{url}]" if fname else f"[资源:{url}]")
    return "".join(parts)


def iter_messages(path: pathlib.Path, *, skip_recalled: bool = True, skip_system: bool = True):
    """Yield normalized records from a QCE export file (oldest first)."""
    import time

    from backend.qqwatcher import classify, is_candidate

    raw = json.loads(path.read_text(encoding="utf-8"))
    chat = raw.get("chatInfo") or {}
    group_id = ""
    import re

    m = re.search(r"group_(\d+)", str(path.name))
    if m:
        group_id = m.group(1)
    cfg = _cfg()
    min_chars = int(cfg.get("min_chars", 60))
    trusted = [str(u) for u in cfg.get("trusted_users") or []]
    for msg in raw.get("messages") or []:
        if skip_recalled and msg.get("recalled"):
            continue
        if skip_system and msg.get("system"):
            continue
        ts = int((msg.get("timestamp") or 0) / 1000)
        if not ts:
            continue
        sender = msg.get("sender") or {}
        uid = str(sender.get("uin") or "")
        text = extract_text(msg).strip()
        if not text:
            continue
        clean = _clean_text(text)
        if len(clean) < 4:
            continue
        is_self = uid == SELF_UIN or uid == str(cfg.get(SELF_KEY, ""))
        if is_self:
            continue
        # candidate rules identical to live watcher (on real words/links only)
        cand = (len(clean) >= min_chars or "http" in clean or "```" in clean
                or uid in trusted)
        rec = {
            "ts": ts,
            "group_id": group_id,
            "user_id": uid,
            "nickname": str(sender.get("name") or sender.get("nickname") or ""),
            "text": text[:2000],
            "candidate": cand,
            "tags": classify(clean),
        }
        yield rec


def ingest(path: pathlib.Path, *, max_messages: int = 0, max_candidates: int = 0) -> dict:
    """Append to candidate store. Returns counts."""
    CAND_DIR.mkdir(parents=True, exist_ok=True)
    n = n_cand = 0
    with (CAND_DIR / "all.jsonl").open("a", encoding="utf-8") as all_f, \
         (CAND_DIR / "_skip.jsonl").open("a", encoding="utf-8") as skip_f:
        for rec in iter_messages(path):
            if max_messages and n >= max_messages:
                break
            f = all_f if rec["candidate"] else skip_f
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            if rec["candidate"]:
                n_cand += 1
                if max_candidates and n_cand >= max_candidates:
                    break
    return {"group_msgs": n, "candidates": n_cand}


def main() -> int:
    args = [a for a in sys.argv[1:]]
    path = pathlib.Path(args[0])
    limit_msgs = 0
    limit_cand = 0
    if "--limit-msgs" in args:
        limit_msgs = int(args[args.index("--limit-msgs") + 1])
    if "--max-candidates" in args:
        limit_cand = int(args[args.index("--max-candidates") + 1])
    res = ingest(path, max_messages=limit_msgs, max_candidates=limit_cand)
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
    except Exception:
        pass
    sys.exit(main())
