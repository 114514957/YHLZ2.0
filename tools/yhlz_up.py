"""Bring the YHLZ local services up (ledger 0426).

Checks Ollama (11434), Yuanheng llama-server (8081, v6 LoRA) and the
workbench daemon (8321); starts whatever is missing (detached, logs under
cache/logs/), then polls health and prints a status table.

Usage:
    python tools/yhlz_up.py            # ensure everything is up
    python tools/yhlz_up.py --check    # report only, never start
    python tools/yhlz_up.py --no-ollama
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LOGS = _ROOT / "cache" / "logs"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SERVICES = {
    "ollama": ("http://127.0.0.1:11434", "/api/tags"),
    "llama": ("http://127.0.0.1:8081", "/health"),
    "daemon": ("http://127.0.0.1:8321", "/health"),
}


def _get(url: str, path: str, timeout: float = 4.0):
    try:
        with urllib.request.urlopen(url + path, timeout=timeout) as r:
            return r.status, r.read(200).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _up(name: str) -> bool:
    base, path = SERVICES[name]
    code, _ = _get(base, path)
    return code == 200


def _spawn(argv: list[str], log: str) -> None:
    _LOGS.mkdir(parents=True, exist_ok=True)
    handle = open(_LOGS / log, "ab")
    subprocess.Popen(argv, cwd=str(_ROOT), stdout=handle,
                     stderr=subprocess.STDOUT, creationflags=_NO_WINDOW,
                     close_fds=True)


def _start(name: str) -> bool:
    from tools.yhlz_launcher import _spawn_daemon, _spawn_llama

    if name == "ollama":
        import shutil

        exe = shutil.which("ollama")
        if not exe:
            print("[up] ollama not found in PATH — skipping")
            return False
        _spawn([exe, "serve"], "ollama.log")
    elif name == "llama":
        _spawn_llama()  # single source of truth: v6 production config
    elif name == "daemon":
        _spawn_daemon()
    else:
        return False
    return True


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="report only")
    ap.add_argument("--timeout", type=float, default=150.0)
    ap.add_argument("--no-ollama", action="store_true")
    ap.add_argument("--no-llama", action="store_true")
    ap.add_argument("--no-daemon", action="store_true")
    a = ap.parse_args()
    skip = {"ollama": a.no_ollama, "llama": a.no_llama, "daemon": a.no_daemon}

    started: list[str] = []
    for name in SERVICES:
        if skip[name] or _up(name) or a.check:
            continue
        if _start(name):
            started.append(name)
            print(f"[up] starting {name} …", flush=True)

    deadline = time.time() + float(a.timeout)
    pending = [n for n in SERVICES if not skip[n] and not _up(n)]
    while pending and time.time() < deadline:
        time.sleep(3)
        pending = [n for n in pending if not _up(n)]

    print("\n%-8s %-8s %s" % ("service", "state", "endpoint"))
    rc = 0
    for name, (base, path) in SERVICES.items():
        ok = _up(name)
        if ok:
            state = "up"
        elif skip[name]:
            state = "skipped"
        else:
            state = "DOWN"
            rc = 1
        print("%-8s %-8s %s%s" % (name, state, base, path))
    if started:
        print("started: " + ", ".join(started))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
