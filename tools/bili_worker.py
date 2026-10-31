"""Process queued B站 browser jobs one at a time (read-only).

Started on demand by ``backend.bili_tools.ensure_worker``; exits after a short
idle period so it does not stay resident forever. A lock file guarantees only
one worker owns the dedicated Edge profile at a time.

Usage:
    python tools/bili_worker.py [--once] [--idle-exit 30] [--poll 2]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import bili_tools as bt  # noqa: E402

LOG = bt.BILI / "worker.log"


def _log(line: str) -> None:
    try:
        if LOG.exists() and LOG.stat().st_size > 1_000_000:
            LOG.replace(LOG.with_suffix(".log.1"))
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception:
        pass


def _acquire_lock() -> bool:
    """Create the lock atomically; tolerate a stale lock whose pid is gone."""
    for attempt in range(2):
        try:
            fd = os.open(bt.LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps({"pid": os.getpid(),
                                     "started_at": time.time()}).encode())
            os.close(fd)
            return True
        except FileExistsError:
            other = bt.worker_pid()
            if other:
                return False
            time.sleep(0.3)
            if attempt == 0:
                try:
                    bt.LOCK.unlink()
                except Exception:
                    return False
            else:
                return False
        except Exception:
            return False
    return False


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    dec = json.JSONDecoder()
    best: dict = {}
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
        except Exception:
            continue
        if isinstance(obj, dict) and (obj.get("title") or obj.get("bvid")):
            best = obj
    return best


def _run_job(job: dict) -> dict:
    kind = str(job.get("kind") or "")
    params = job.get("params") or {}
    argv = [sys.executable, str(bt.CLI), kind]
    if kind == "find":
        argv += [str(params.get("keyword") or ""), "--limit",
                 str(params.get("limit") or 10)]
    elif kind == "watch":
        argv += [str(params.get("target") or params.get("bvid") or "")]
    else:
        return {"status": "error", "error": f"unknown kind {kind}"}
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.time()
    try:
        proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=300, env=env)
        meta = _extract_json(proc.stdout)
        ok = bool(meta.get("title") or meta.get("bvid"))
        return {
            "id": job.get("id"), "kind": kind, "params": params,
            "status": "done" if ok else "error",
            "result": meta,
            "error": "" if ok else ((proc.stderr or "")[-800:]
                                     or "no JSON result from bili_browse"),
            "exit_code": proc.returncode,
            "started_at": started, "finished_at": time.time(),
            "stdout_tail": (proc.stdout or "")[-800:],
        }
    except subprocess.TimeoutExpired:
        return {"id": job.get("id"), "kind": kind, "params": params,
                "status": "error", "result": {},
                "error": "bilibili browse timed out (300s)",
                "started_at": started, "finished_at": time.time()}
    except Exception as exc:
        return {"id": job.get("id"), "kind": kind, "params": params,
                "status": "error", "result": {},
                "error": f"{type(exc).__name__}: {exc}",
                "started_at": started, "finished_at": time.time()}


def _recover_stale(max_age: float = 600.0) -> None:
    """Turn a crashed worker's running marker into an error result."""
    for p in bt.RESULTS.glob("*.running.json"):
        try:
            if time.time() - p.stat().st_mtime < max_age:
                continue
            d = bt._read_json(p)
            job_id = str(d.get("id") or p.name.replace(".running.json", ""))
            d.update(status="error", error="worker interrupted",
                     finished_at=time.time())
            bt._atomic_write(bt.RESULTS / f"{job_id}.json", d)
            p.unlink(missing_ok=True)
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--idle-exit", type=float, default=30.0)
    ap.add_argument("--poll", type=float, default=2.0)
    args = ap.parse_args(argv)

    if not _acquire_lock():
        return 0
    _recover_stale()
    _log(f"worker start pid={os.getpid()}")
    started = time.time()
    processed = 0
    try:
        while True:
            jobs = sorted(bt.QUEUE.glob("*.json"))
            if not jobs:
                if args.once:
                    break
                if time.time() - started > max(5.0, args.idle_exit):
                    break
                time.sleep(max(0.5, args.poll))
                continue
            path = jobs[0]
            job = bt._read_json(path)
            if not job:
                path.unlink(missing_ok=True)
                continue
            job_id = str(job.get("id") or path.stem)
            job.update(status="running", started_at=time.time())
            running = bt.RESULTS / f"{job_id}.running.json"
            bt._atomic_write(running, job)
            path.unlink(missing_ok=True)
            try:
                result = _run_job(job)
            except Exception as exc:  # belt and braces
                result = {"id": job_id, "kind": job.get("kind"),
                          "params": job.get("params") or {},
                          "status": "error",
                          "error": f"{type(exc).__name__}: {exc}"}
            bt._atomic_write(bt.RESULTS / f"{job_id}.json", result)
            running.unlink(missing_ok=True)
            processed += 1
            _log(f"job={job_id} kind={job.get('kind')} "
                 f"status={result.get('status')} "
                 f"title={(result.get('result') or {}).get('title', '')[:40]}")
            if args.once:
                break
    finally:
        try:
            bt.LOCK.unlink(missing_ok=True)
        except Exception:
            pass
        _log(f"worker exit pid={os.getpid()} processed={processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
