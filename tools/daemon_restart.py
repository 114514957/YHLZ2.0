"""Reliably (re)start the YHLZ daemon (8321) — v2 (ledger 0803).

What v1 got wrong (incident 2026-10-13 16:00): `psutil.Process.kill()` failures
were swallowed (`killed=0` printed as success), so a *new* instance was spawned
while the old one still held 8321 — two daemons, the stale one still serving.
Also, the daemon is a **pair** (venv-python launcher + real interpreter), so
"any target_daemon pid that is not the port owner" is NOT a duplicate; only a
process outside the port owner's own family is.

v2 therefore:
  1. kills by `taskkill /F /T` with a psutil fallback, and **reports failures**
     instead of swallowing them;
  2. decides success by **who owns 8321** plus `/health` answering with a fresh
     uptime — never by "some target_daemon process exists";
  3. treats launcher+interpreter as one instance (port owner + parent/children);
  4. cleans up only *extra* instances and reports exactly what it did.

Usage:
  python tools/daemon_restart.py            # restart, verify, clean extras
  python tools/daemon_restart.py --status   # read-only report (no kill/spawn)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import psutil  # noqa: E402

from yhlz_launcher import _spawn_daemon  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = _ROOT / ".venv" / "Scripts" / "python.exe"
PORT = 8321
HEALTH = f"http://127.0.0.1:{PORT}/health"
WAIT_SECONDS = 40.0        # how long to wait for a *fresh* /health after spawn
FRESH_UPTIME = 60.0        # uptime below this = the instance we just started


def daemon_pids() -> list[int]:
    """Every python process whose cmdline runs backend.target_daemon."""
    out: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
        except Exception:
            continue
        if "target_daemon" in cmdline and \
                (proc.info.get("name") or "").startswith("python"):
            out.append(int(proc.info["pid"]))
    return sorted(out)


def port_owner(port: int = PORT) -> int:
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == "LISTEN" and conn.laddr and \
                    conn.laddr.port == port:
                return int(conn.pid or 0)
    except Exception:
        pass
    return 0


def instance_family(pid: int) -> set[int]:
    """The instance behind a port owner: itself + parent + children."""
    family = {pid}
    try:
        proc = psutil.Process(pid)
        family.add(proc.ppid())
        family |= {child.pid for child in proc.children(recursive=True)}
    except Exception:
        pass
    return family


def health(timeout: float = 8.0) -> dict | None:
    try:
        with urllib.request.urlopen(HEALTH, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def kill_pid(pid: int) -> tuple[bool, str]:
    """Kill a pid and its tree; psutil fallback. Returns (ok, detail).

    "Already gone" counts as success: killing the launcher of the
    launcher+interpreter pair takes the child with it, so the second kill is
    expected to find nothing (incident note, ledger 0803).
    """
    detail = ""
    try:
        done = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", check=False)
        if done.returncode == 0:
            return True, "taskkill"
        detail = (done.stderr or done.stdout or f"taskkill rc={done.returncode}")
        detail = detail.strip()[:120]
        if "not found" in detail.lower() or "找不到" in detail:
            return True, "already gone"
    except Exception as exc:  # noqa: BLE001
        detail = f"taskkill error {type(exc).__name__}"
    try:
        psutil.Process(pid).kill()
        return True, "psutil"
    except psutil.NoSuchProcess:
        return True, "already gone"
    except Exception as exc:  # noqa: BLE001
        return False, f"{detail}; psutil {type(exc).__name__}: {exc}"


def _report(tag: str) -> tuple[list[int], int, dict | None]:
    pids = daemon_pids()
    owner = port_owner()
    state = health()
    print(f"[{tag}] daemon pids={pids} port{PORT}_owner={owner} "
          f"health={'ok' if state else 'down'}"
          + (f" uptime={state.get('uptime_s'):.1f}s" if state else ""))
    return pids, owner, state


def restart() -> int:
    pids, owner, _ = _report("before")
    failed: list[str] = []
    for pid in pids:
        ok, detail = kill_pid(pid)
        print(f"  kill {pid}: {'ok' if ok else 'FAILED'} ({detail})")
        if not ok:
            failed.append(f"{pid}: {detail}")
    time.sleep(3)
    left = daemon_pids()
    if left:
        print(f"  still alive after kill: {left}")

    _spawn_daemon()  # shared spawn with cache/logs/daemon.log redirect
    print(f"  spawned; waiting up to {WAIT_SECONDS:.0f}s for a fresh /health ...")
    deadline = time.time() + WAIT_SECONDS
    fresh: dict | None = None
    while time.time() < deadline:
        state = health()
        if state and float(state.get("uptime_s") or 0) < FRESH_UPTIME:
            fresh = state
            break
        time.sleep(2)
    pids2, owner2, _ = _report("after")

    # only a process outside the port owner's family is a real duplicate
    extras: list[int] = []
    if owner2:
        family = instance_family(owner2)
        extras = [p for p in pids2 if p not in family and p != owner2]
        for pid in extras:
            ok_kill, detail = kill_pid(pid)
            print(f"  clean extra {pid}: {'ok' if ok_kill else 'FAILED'} ({detail})")
    leftovers: list[int] = []
    if extras:
        time.sleep(2)
        pids3, owner3, _ = _report("cleaned")
        if owner3:
            owner2 = owner3
            family3 = instance_family(owner3)
            leftovers = [p for p in pids3 if p not in family3 and p != owner3]

    ok = bool(owner2) and fresh is not None and not leftovers
    print(f"result: {'OK' if ok else 'FAILED'} "
          f"owner={owner2} fresh_health={'yes' if fresh else 'no'} "
          f"kill_failures={failed or '-'} cleaned={extras or '-'} "
          f"leftovers={leftovers or '-'}")
    return 0 if ok else 1


def status() -> int:
    pids, owner, state = _report("status")
    if owner:
        print(f"  instance family={sorted(instance_family(owner))}")
    return 0 if owner and state else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true",
                    help="read-only: report pids/port owner/health")
    args = ap.parse_args()
    return status() if args.status else restart()


if __name__ == "__main__":
    raise SystemExit(main())
