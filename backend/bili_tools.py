"""B站 browser lane: queue -> worker -> notes (read-only).

The browser trip takes 1-3 minutes (Edge launch + subtitle fetch + local
Gemma note), far longer than an agent tool turn should block.  So the agent
capabilities only *enqueue* a job and return a job id; ``tools/bili_worker.py``
processes the queue one job at a time (a dedicated Edge profile can only be
used by one process) and writes a JSON result plus a Markdown note.

Capabilities exposed to 元亨 (see target_scheduler_tools.scheduler_capabilities):
  bili.find    enqueue a keyword search -> pick -> watch -> note
  bili.watch   enqueue one BV/url
  bili.status  recent jobs and their status
  bili.notes   recent finished notes
  bili.read    read one note by BV

Read-only by design: no like/coin/favourite/comment/follow.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
BILI = ROOT / "cache" / "bilibili"
QUEUE = BILI / "queue"
RESULTS = BILI / "results"
NOTES = BILI / "notes"
LOCK = BILI / "worker.lock"
WORKER = ROOT / "tools" / "bili_worker.py"
CLI = ROOT / "tools" / "bili_browse.py"
for _d in (QUEUE, RESULTS, NOTES):
    _d.mkdir(parents=True, exist_ok=True)

BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
KINDS = ("find", "watch")


def _atomic_write(path: pathlib.Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        import psutil
        return bool(psutil.pid_exists(int(pid)))
    except Exception:
        try:
            os.kill(int(pid), 0)
            return True
        except Exception:
            return False


def worker_pid() -> int:
    """Live worker pid from the lock file, or 0."""
    data = _read_json(LOCK)
    pid = int(data.get("pid") or 0)
    return pid if _pid_alive(pid) else 0


def ensure_worker(timeout: float = 3.0) -> int:
    """Start the worker if it is not already alive. Returns its pid or 0."""
    pid = worker_pid()
    if pid:
        return pid
    flags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
    # The daemon is restarted by the watchdog; without breakaway the worker
    # (a daemon child) dies mid-job and leaves a running marker forever.
    breakaway = 0x01000000
    last_exc: Exception | None = None
    for extra in (breakaway, 0):
        try:
            subprocess.Popen(
                [sys.executable, str(WORKER)],
                cwd=str(ROOT), close_fds=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=flags | extra,
            )
            last_exc = None
            break
        except Exception as exc:  # breakaway may be denied by the job
            last_exc = exc
    if last_exc is not None:
        return 0
    deadline = time.time() + max(0.5, timeout)
    while time.time() < deadline:
        pid = worker_pid()
        if pid:
            return pid
        time.sleep(0.1)
    return 0


def enqueue(kind: str, params: dict) -> str:
    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    recover_stale()
    ensure_worker()
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    _atomic_write(QUEUE / f"{job_id}.json", {
        "id": job_id, "kind": kind, "params": dict(params or {}),
        "created_at": time.time(), "status": "queued",
    })
    return job_id


def enqueue_find(keyword: str, limit: int = 10) -> str:
    kw = str(keyword or "").strip()[:80]
    if not kw:
        return "需要关键词（1-80 字）"
    try:
        n = max(1, min(20, int(limit or 10)))
    except Exception:
        n = 10
    job_id = enqueue("find", {"keyword": kw, "limit": n})
    return (f"已排队 bili.find：job={job_id} 关键词={kw}。"
            f"后台会开浏览器搜片→抓字幕→Gemma 写笔记（约 1-3 分钟）。"
            f"稍后用 bili.status 看状态，用 bili.notes / bili.read 读笔记。")


def enqueue_watch(target: str) -> str:
    raw = str(target or "").strip()
    bv = BV_RE.search(raw)
    if not bv:
        return "需要 B 站视频链接或 BV 号"
    job_id = enqueue("watch", {"target": raw, "bvid": bv.group(1)})
    return (f"已排队 bili.watch：job={job_id} 视频={bv.group(1)}。"
            f"完成后用 bili.status / bili.notes 查看。")


def recover_stale(max_age: float = 330.0) -> int:
    """Turn a dead worker's running marker into an error result."""
    recovered = 0
    for path in RESULTS.glob("*.running.json"):
        try:
            if time.time() - path.stat().st_mtime < max_age:
                continue
            data = _read_json(path)
            job_id = str(data.get("id") or path.name.replace(".running.json", ""))
            data.update(status="error", error="worker interrupted",
                        finished_at=time.time())
            _atomic_write(RESULTS / f"{job_id}.json", data)
            path.unlink(missing_ok=True)
            recovered += 1
        except Exception:
            pass
    return recovered


def list_jobs(limit: int = 10) -> str:
    recover_stale()
    try:
        n = max(1, min(50, int(limit or 10)))
    except Exception:
        n = 10
    rows: list[dict] = []
    for p in QUEUE.glob("*.json"):
        d = _read_json(p)
        if d:
            d.setdefault("status", "queued")
            rows.append(d)
    for p in RESULTS.glob("*.json"):
        d = _read_json(p)
        if d:
            rows.append(d)
    rows.sort(key=lambda d: float(d.get("created_at") or 0), reverse=True)
    if not rows:
        return "B站队列是空的（还没有排队或完成的看片任务）。"
    lines = [f"最近 {min(len(rows), n)} 条 B站看片任务："]
    for d in rows[:n]:
        kind = d.get("kind") or "?"
        status = d.get("status") or "?"
        params = d.get("params") or {}
        target = params.get("keyword") or params.get("bvid") or params.get("target") or ""
        res = d.get("result") or {}
        title = res.get("title") or ""
        extra = f" → {title[:40]}" if title else ""
        lines.append(f"- [{status}] {kind} {target}{extra} (job={d.get('id')})")
    return "\n".join(lines)


def _note_meta(path: pathlib.Path) -> dict:
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    head = text.splitlines()
    title = head[0][2:].strip() if head and head[0].startswith("# ") else path.stem
    up = ""
    when = ""
    for line in head[:12]:
        if line.startswith("- UP:"):
            up = line.split(":", 1)[1].strip()
        elif line.startswith("- 抓取时间:"):
            when = line.split(":", 1)[1].strip()
    return {"bvid": path.stem, "title": title, "up": up, "when": when,
            "has_summary": "## 元亨的笔记" in text,
            "chars": len(text), "path": str(path)}


def recent_notes(limit: int = 10) -> str:
    try:
        n = max(1, min(50, int(limit or 10)))
    except Exception:
        n = 10
    paths = sorted(NOTES.glob("*.md"), key=lambda p: p.stat().st_mtime,
                   reverse=True)[:n]
    if not paths:
        return "还没有看片笔记。先用 bili.find 搜一个话题。"
    lines = [f"最近 {len(paths)} 篇看片笔记（按时间倒序）："]
    for p in paths:
        m = _note_meta(p)
        if not m:
            continue
        mark = "有笔记" if m["has_summary"] else "只有字幕"
        lines.append(f"- {m['bvid']}《{m['title'][:50]}》UP:{m['up'] or '?'} "
                     f"{m['when']} [{mark}]")
    return "\n".join(lines)


def read_note(bvid: str, max_chars: int = 6000) -> str:
    m = BV_RE.search(str(bvid or ""))
    if not m:
        return "需要一个 BV 号"
    path = NOTES / f"{m.group(1)}.md"
    if not path.exists():
        return f"没有找到 {m.group(1)} 的笔记（先用 bili.notes 看有哪些）。"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"读取失败：{type(exc).__name__}"
    try:
        limit = max(500, min(20000, int(max_chars or 6000)))
    except Exception:
        limit = 6000
    if len(text) > limit:
        return text[:limit] + f"\n\n……（已截断，原文 {len(text)} 字）"
    return text
