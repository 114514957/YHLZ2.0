"""Pull raw QQ group history via the local QCE plugin, preserving original text.

Training-data oriented: copies the untouched QCE export JSON into the project
(`data/finetune/qq_raw/`) and emits `data/finetune/corpus_qq_raw.jsonl` where
every message keeps its original text verbatim — no cleaning, no truncation,
no filtering (recalled/system are kept and flagged).

Distinct from `backend.qqexport_ingest`, which cleans/filters for the knowledge
pipeline; this path is for raw training corpora.

Usage:
    python tools/qq_pull_raw.py                       # default two groups
    python tools/qq_pull_raw.py --group 855372167 --group 681195563
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_RAW = ROOT / "data" / "finetune" / "qq_raw"
OUT_JSONL = ROOT / "data" / "finetune" / "corpus_qq_raw.jsonl"
QCE_BASE = "http://127.0.0.1:40653"
DEFAULT_GROUPS = ["855372167", "681195563"]


def _token() -> str:
    sec = (pathlib.Path(os.path.expanduser("~"))
           / ".qq-chat-exporter" / "security.json")
    if not sec.exists():
        raise SystemExit("QCE security.json 不存在：请先启动 NapCat/QCE")
    return json.loads(sec.read_text(encoding="utf-8")).get("accessToken", "")


async def export_group(group: str, name: str) -> pathlib.Path:
    """Ask QCE to export one group; return the produced JSON file path."""
    import httpx

    headers = {"Authorization": "Bearer " + _token()}
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(QCE_BASE + "/api/messages/export", headers=headers, json={
            "peer": {"chatType": 2, "peerUid": group},
            "format": "JSON",
            "options": {},
            "sessionName": name,
        })
        r.raise_for_status()
        task = r.json().get("data") or {}
        task_id = task.get("taskId")
        if not task_id:
            raise RuntimeError(f"导出任务未创建 group={group}")
        file_path = task.get("filePath", "")
        st: dict = {}
        for _ in range(180):
            await asyncio.sleep(2)
            rr = await c.get(QCE_BASE + "/api/tasks/" + task_id, headers=headers)
            st = rr.json().get("data") or {}
            if st.get("status") in ("completed", "failed"):
                break
        if not file_path or not pathlib.Path(file_path).exists():
            ex = (pathlib.Path(os.path.expanduser("~"))
                  / ".qq-chat-exporter" / "exports")
            cands = sorted(ex.glob(f"group_{group}_*.json"),
                           key=lambda p: p.stat().st_mtime)
            file_path = str(cands[-1]) if cands else ""
    if not file_path or not pathlib.Path(file_path).exists():
        raise RuntimeError(f"导出文件未找到 group={group} status={st.get('status')}")
    return pathlib.Path(file_path)


def raw_records(path: pathlib.Path):
    """Yield every message verbatim, original content preserved."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    chat = raw.get("chatInfo") or {}
    m = re.search(r"group_(\d+)", path.name)
    group = m.group(1) if m else str(chat.get("name", ""))
    for msg in raw.get("messages") or []:
        content = msg.get("content") or {}
        sender = msg.get("sender") or {}
        yield {
            "group": group,
            "msg_id": str(msg.get("id", "")),
            "seq": str(msg.get("seq", "")),
            "ts": int((msg.get("timestamp") or 0) / 1000),
            "time": str(msg.get("time", "")),
            "user": str(sender.get("uin") or ""),
            "nick": str(sender.get("name") or sender.get("nickname")
                        or sender.get("groupCard") or ""),
            "text": str(content.get("text") or ""),
            "elements": content.get("elements") or [],
            "resources": content.get("resources") or [],
            "mentions": content.get("mentions") or [],
            "recalled": bool(msg.get("recalled")),
            "system": bool(msg.get("system")),
        }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    groups = ([args[i + 1] for i, a in enumerate(args) if a == "--group"]
              or DEFAULT_GROUPS)
    OUT_RAW.mkdir(parents=True, exist_ok=True)
    files: list[pathlib.Path] = []
    for g in groups:
        fp = asyncio.run(export_group(g, f"g{g}"))
        dst = OUT_RAW / fp.name
        dst.write_bytes(fp.read_bytes())
        files.append(dst)
        print(f"[export] group={g} -> {dst} ({dst.stat().st_size} B)")
    n = 0
    seen: set[tuple[str, str]] = set()
    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for fp in files:
            for rec in raw_records(fp):
                k = (rec["group"], rec["msg_id"])
                if rec["msg_id"] and k in seen:
                    continue
                seen.add(k)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
    print(json.dumps({"groups": groups, "messages": n,
                      "jsonl": str(OUT_JSONL), "raw_dir": str(OUT_RAW)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
