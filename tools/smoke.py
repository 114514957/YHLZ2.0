"""Read-only smoke check for the YH stack (ledger 0957, debt item F2).

Answers one question in ten seconds: is the stack alive, and what is degraded?
Never restarts anything, never writes. Exit code 0 = no FAIL, 1 = at least one FAIL.

Usage:
    python tools/smoke.py
    python tools/smoke.py --json

Hard failures (exit 1): gemma 8081, daemon 8321, worker 8347.
Degradations (warn only): NapCat 3001, QQ bridge ws_state, DSH GUI.
Optional (never FAIL): Ollama 11434 — `YHLZ_START_OLLAMA` is off by design.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import socket
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRIDGE_STATUS = ROOT / "cache" / "qq_bridge" / "lite" / "bridge_status.json"
DSH_GUI_PORT = int(os.getenv("YHLZ_DSH_GUI_PORT", "61175"))

OK, WARN, FAIL = "OK", "WARN", "FAIL"


def _http(url: str, timeout: float = 5.0) -> tuple[bool, dict | str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read(200_000)
            try:
                return True, json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                return True, raw.decode("utf-8", "replace")[:200]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _port(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_gemma() -> tuple[str, str, str]:
    ok, body = _http("http://127.0.0.1:8081/health")
    if not ok:
        return FAIL, "gemma 8081", str(body)
    if not isinstance(body, dict) or body.get("status") != "ok":
        return FAIL, "gemma 8081", "health responded but status != ok"
    return OK, "gemma 8081", f"status=ok slots={body.get('slots')}"


def check_ollama() -> tuple[str, str, str]:
    """Optional by design (launcher leaves it alone unless YHLZ_START_OLLAMA=1)."""
    enabled = str(os.getenv("YHLZ_START_OLLAMA", "")).strip().lower() in (
        "1", "true", "yes", "on")
    if _port("127.0.0.1", 11434):
        return OK, "ollama 11434", "listening"
    if enabled:
        return WARN, "ollama 11434", "not listening but YHLZ_START_OLLAMA is set"
    return OK, "ollama 11434", "off (optional; YHLZ_START_OLLAMA unset)"


def check_daemon() -> tuple[str, str, str]:
    ok, body = _http("http://127.0.0.1:8321/state")
    if not ok:
        return FAIL, "daemon 8321", str(body)
    if not isinstance(body, dict) or not body.get("ok"):
        return FAIL, "daemon 8321", "state responded but ok != true"
    gemma = body.get("gemma", "?")
    qq = body.get("qq") or {}
    detail = (f"gemma={gemma} ollama={body.get('ollama')} "
              f"qq_online={qq.get('online')} bridge_pid={qq.get('bridge_pid')}")
    return OK, "daemon 8321", detail


def check_worker() -> tuple[str, str, str]:
    ok, body = _http("http://127.0.0.1:8347/health")
    if not ok:
        return FAIL, "worker 8347", str(body)
    return OK, "worker 8347", json.dumps(body, ensure_ascii=False)[:160] if isinstance(body, dict) else str(body)[:160]


def check_bridge() -> tuple[str, str, str]:
    if not BRIDGE_STATUS.exists():
        return WARN, "qq bridge", "bridge_status.json missing"
    try:
        status = json.loads(BRIDGE_STATUS.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return WARN, "qq bridge", f"unreadable: {type(exc).__name__}"
    ws = status.get("ws_state") or status.get("state", "?")
    loop_ts = float(status.get("event_loop_ts") or 0)
    age = time.time() - loop_ts if loop_ts else -1
    detail = (f"ws_state={ws} pid={status.get('pid')} "
              f"reconnects={status.get('reconnect_count')} loop_age={age:.0f}s")
    if age > 60:
        return WARN, "qq bridge", detail + " (stale: bridge loop not ticking)"
    if ws != "connected":
        return WARN, "qq bridge", detail
    return OK, "qq bridge", detail


def check_napcat() -> tuple[str, str, str]:
    if _port("127.0.0.1", 3001):
        return OK, "napcat 3001", "listening"
    return WARN, "napcat 3001", "not listening — QQ offline (bridge keeps retrying)"


def check_gui() -> tuple[str, str, str]:
    if _port("127.0.0.1", DSH_GUI_PORT):
        return OK, f"dsh gui {DSH_GUI_PORT}", "listening"
    return WARN, f"dsh gui {DSH_GUI_PORT}", "not listening — set YHLZ_DSH_GUI_PORT"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    checks = [check_gemma(), check_daemon(), check_worker(), check_ollama(),
              check_bridge(), check_napcat(), check_gui()]
    failed = sum(1 for level, _, _ in checks if level == FAIL)
    warned = sum(1 for level, _, _ in checks if level == WARN)

    if args.json:
        print(json.dumps({
            "checks": [{"level": l, "name": n, "detail": d} for l, n, d in checks],
            "fail": failed, "warn": warned,
        }, ensure_ascii=False, indent=2))
    else:
        for level, name, detail in checks:
            print(f"[{level:4}] {name:<16} {detail}")
        verdict = "FAIL" if failed else ("DEGRADED" if warned else "OK")
        print(f"\n{verdict}: {failed} fail, {warned} warn "
              f"({time.strftime('%Y-%m-%d %H:%M:%S')})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
