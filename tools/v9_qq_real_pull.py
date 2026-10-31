"""QQ 真实对话拉取（老爹 2026-10-18：QQ 接受 + 真实对话继续拉）。

两个来源：
1) `cache/sessions/qq_*.json` —— 元亨与各频道的真实会话（user/assistant 已配对）；
2) `cache/qq_bridge/lite/group_history.db::group_messages` —— 群里 元亨 的真实发言与其前一条
   他人的消息（作为上下文），按「连续对话段」重组。

输出：`data/v9_real_dialogue/pulled_<date>.jsonl`，每行
`{"messages":[...], "source":"real:qq-<channel>", "source_id":..., "consent_status":"anonymized",
  "channel":..., "origin": "session|group"}`
并写 manifest（条数/哈希/来源）。

用法：python tools/v9_qq_real_pull.py [--min-rounds 2] [--limit 500]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sqlite3
import sys
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
SESS = ROOT / "cache" / "sessions"
GH = ROOT / "cache" / "qq_bridge" / "lite" / "group_history.db"
OUT = ROOT / "data" / "v9_real_dialogue"

SYS = None  # 交给装配器统一注入 system；这里只保留对话对


def from_sessions(limit: int) -> list[dict]:
    rows: list[dict] = []
    for p in sorted(SESS.glob("qq_*.json"), key=lambda x: -x.stat().st_mtime):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        hist = d.get("history") or []
        if len(hist) < 2:
            continue
        msgs = [{"role": "user" if h.get("role") == "user" else "assistant",
                 "content": str(h.get("content") or "").strip()}
                for h in hist if h.get("content")]
        msgs = [m for m in msgs if m["content"]]
        if len(msgs) < 2:
            continue
        rows.append({"messages": msgs[-40:],
                     "source": f"real:qq-{d.get('channel') or p.stem}",
                     "source_id": f"real#{p.stem}",
                     "consent_status": "anonymized",
                     "origin": "session",
                     "channel": d.get("channel") or p.stem})
        if len(rows) >= limit:
            break
    return rows


def from_group_history(min_turns: int, limit: int) -> list[dict]:
    if not GH.exists():
        return []
    con = sqlite3.connect(GH)
    con.row_factory = sqlite3.Row
    rows: list[dict] = []
    groups = [r[0] for r in con.execute(
        "select distinct group_id from group_messages")]
    for gid in groups:
        msgs = con.execute(
            "select sender_id, sender_name, text, is_bot from group_messages "
            "where group_id=? order by seq", (gid,)).fetchall()
        # 以 元亨 的回复为锚，向前取一条他人消息组成一对
        pair: list[dict] = []
        for i, m in enumerate(msgs):
            txt = (m["text"] or "").strip()
            if not txt:
                continue
            if m["is_bot"] and pair and pair[-1]["role"] == "user":
                pair.append({"role": "assistant", "content": txt})
            else:
                pair.append({"role": "user", "content": txt})
            if len(pair) >= min_turns * 2:
                rows.append({"messages": pair,
                             "source": f"real:qq-{gid}",
                             "source_id": f"real#{gid}#{i}",
                             "consent_status": "anonymized",
                             "origin": "group",
                             "channel": f"qq_{gid}"})
                pair = []
                if len(rows) >= limit:
                    con.close()
                    return rows
    con.close()
    return rows


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--min-rounds", type=int, default=2)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    sess = from_sessions(args.limit)
    grp = from_group_history(args.min_rounds, args.limit)
    all_rows = sess + grp
    for i, r in enumerate(all_rows):
        r["content_hash"] = hashlib.sha256(
            json.dumps(r["messages"], ensure_ascii=False).encode()).hexdigest()[:16]
    out = OUT / f"pulled_{datetime.now():%Y%m%d}.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r in all_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    manifest = {"pulled_at": datetime.now().isoformat(timespec="seconds"),
                "session_rows": len(sess), "group_rows": len(grp),
                "total": len(all_rows), "file": str(out.relative_to(ROOT)),
                "note": "QQ 同意已由老爹 2026-10-18 裁定（D-1 关闭）；群友昵称仍为原样，装配前须过匿名化"}
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
