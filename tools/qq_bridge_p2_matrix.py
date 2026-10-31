"""P2 restart matrix evidence (offline, fake checker, deterministic clock).

Cases: single-attempt recovery, two-attempt lost notice, manual stop/start,
PID-reuse refusal, static isolation of the Lite watch set.

Usage:
    .venv\\Scripts\\python.exe tools\\qq_bridge_p2_matrix.py --out artifacts\\qq_lite\\p2_<id>
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

from backend.qq_bridge_lock import (  # noqa: E402
    owner_matches, read_info, terminate_owned,
)
from backend.qq_bridge_notices import NoticeStore  # noqa: E402

from qq_bridge_service import write_desired  # noqa: E402
from qq_bridge_watchdog import FakeChecker, Watchdog  # noqa: E402

RECOVERY = {
    "check_interval_seconds": 2,
    "attempt_timeout_seconds": 15,
    "attempt2_delay_seconds": 2,
    "stall_seconds": 30,
    "start_grace_seconds": 30,
    "backoff_seconds": [15, 30, 60],
    "blocked_after_failures": 5,
    "blocked_retry_seconds": 600,
}
FORBIDDEN = re.compile(
    r"ensure" + r"_stack|_spawn" + r"_ollama|_spawn" + r"_llama"
    r"|_spawn" + r"_daemon|_spawn" + r"_napcat"
    r"|yhlz" + r"_launcher|yhlz" + r"_watchdog")


def _resolved(base: pathlib.Path) -> dict:
    return {"profile": "lite", "state_dir": str(base),
            "masters": ["2258374446"], "uin": "3655185302",
            "config": {"recovery": dict(RECOVERY)}}


def _alive(entry: str) -> dict:
    return {"pid": 4242, "create_time": 1.0, "profile": "lite",
            "role": "bridge", "entry": entry, "instance_id": "fixture"}


def _status(ts: float, state: str = "connected", online: bool = True) -> dict:
    return {"state": state, "event_loop_ts": ts, "account_online": online,
            "inbox": {"pending": 0, "busy": 0}, "pid": 4242}


def case_crash_recover(base: pathlib.Path) -> dict:
    clock = {"t": 1000.0}
    entry = str(_ROOT / "tools" / "qq_bridge_service.py")
    checker = FakeChecker({
        "owner_ok": [True], "bridge_pid_info": [_alive(entry)],
        "bridge_status": [_status(1000.0)], "send_results": ["confirmed"],
        "uin": "3655185302",
    })
    wd = Watchdog(_resolved(base), checker=checker, now=lambda: clock["t"],
                  jitter=lambda: 1.0, state_dir=base)
    wd.tick()
    clock["t"] = 1006.0
    wd.tick()  # stable -> seen_bridge

    checker.set_script({"owner_ok": [False], "bridge_pid_info": [{}],
                        "bridge_status": [{}], "send_results": ["confirmed"]})
    clock["t"] = 1007.0
    wd.tick()  # outage + attempt1

    checker.set_script({"owner_ok": [True], "bridge_pid_info": [_alive(entry)],
                        "bridge_status": [_status(1008.0)],
                        "send_results": ["confirmed"]})
    clock["t"] = 1008.0
    wd.tick()  # fresh, wait stable
    clock["t"] = 1014.0
    snap = wd.tick()  # stable -> recovered notice

    notices = NoticeStore(base / "notices.jsonl", bot_uin="3655185302")._load()
    kinds = {n["kind"]: n for n in notices}
    ok = (checker.calls["spawn"] == 1
          and "lost" not in kinds
          and kinds.get("recovered", {}).get("status") == "sent"
          and kinds.get("recovered", {}).get("text") == "【元亨已接续】"
          and snap["phase"] == "healthy")
    return {"pass": bool(ok), "spawn_calls": checker.calls["spawn"],
            "notices": [{"kind": n["kind"], "status": n["status"],
                         "text": n["text"]} for n in notices],
            "final_phase": snap["phase"]}


def case_two_attempts_lost(base: pathlib.Path) -> dict:
    base.mkdir(parents=True, exist_ok=True)
    clock = {"t": 2000.0}
    checker = FakeChecker({
        "owner_ok": [False], "bridge_pid_info": [{}], "bridge_status": [{}],
        "send_results": ["confirmed"], "uin": "3655185302",
    })
    wd = Watchdog(_resolved(base), checker=checker, now=lambda: clock["t"],
                  jitter=lambda: 1.0, state_dir=base)
    clock["t"] = 2000.0
    wd.tick()  # attempt1
    clock["t"] = 2015.0
    wd.tick()  # attempt1 failed -> backoff 2s
    clock["t"] = 2017.0
    wd.tick()  # attempt2
    clock["t"] = 2032.0
    wd.tick()  # attempt2 failed -> lost notice
    notices = NoticeStore(base / "notices.jsonl", bot_uin="3655185302")._load()
    lost = next((n for n in notices if n["kind"] == "lost"), {})
    ok = (checker.calls["spawn"] == 2
          and lost.get("status") == "sent"
          and lost.get("text") == "【系统检测到异常，元亨丢失】"
          and wd.state.get("attempt") == 2
          and wd.state.get("phase") == "backoff")
    return {"pass": bool(ok), "spawn_calls": checker.calls["spawn"],
            "lost": {k: lost.get(k) for k in ("status", "text", "attempts")},
            "phase": wd.state.get("phase")}


def case_manual_stop_start(base: pathlib.Path) -> dict:
    base.mkdir(parents=True, exist_ok=True)
    write_desired(base, "stopped")
    clock = {"t": 3000.0}
    checker = FakeChecker({"owner_ok": [False], "bridge_pid_info": [{}],
                           "bridge_status": [{}], "uin": "3655185302"})
    wd = Watchdog(_resolved(base), checker=checker, now=lambda: clock["t"],
                  jitter=lambda: 1.0, state_dir=base)
    snap_stopped = wd.tick()
    spawn_while_stopped = checker.calls["spawn"]
    write_desired(base, "running")
    clock["t"] = 3002.0
    snap_running = wd.tick()
    notices = NoticeStore(base / "notices.jsonl",
                          bot_uin="3655185302").summary()
    ok = (snap_stopped["phase"] == "stopped"
          and spawn_while_stopped == 0
          and checker.calls["spawn"] == 1
          and snap_running["phase"].startswith("recovering")
          and notices["total"] == 0)
    return {"pass": bool(ok), "stopped_phase": snap_stopped["phase"],
            "spawn_after_start": checker.calls["spawn"],
            "notices_total": notices["total"]}


def case_pid_reuse_refusal(base: pathlib.Path) -> dict:
    base.mkdir(parents=True, exist_ok=True)
    clock = {"t": 4000.0}
    entry = str(_ROOT / "tools" / "qq_bridge_service.py")
    checker = FakeChecker({
        "owner_ok": [True], "bridge_pid_info": [_alive(entry)],
        "bridge_status": [_status(3900.0)], "terminate_result": [[False, "pid_reused"]],
        "uin": "3655185302",
    })
    wd = Watchdog(_resolved(base), checker=checker, now=lambda: clock["t"],
                  jitter=lambda: 1.0, state_dir=base)
    wd.tick()  # stale starts
    clock["t"] = 4031.0
    wd.tick()  # stuck >= 30 -> try terminate, refused
    results = checker.calls.get("terminate_results", [])
    ok = (checker.calls["terminate"] == 1 and results
          and results[0][0] is False and results[0][1] == "pid_reused"
          and checker.calls["spawn"] == 0)
    return {"pass": bool(ok), "terminate_calls": checker.calls["terminate"],
            "terminate_results": results, "spawn_calls": checker.calls["spawn"]}


class RealStubChecker:
    """Real spawn/kill against tools/qq_bridge_p2_stub_bridge.py (no QQ)."""

    def __init__(self, base: pathlib.Path) -> None:
        self.base = base
        self.entry = str((_ROOT / "tools" / "qq_bridge_p2_stub_bridge.py").resolve())
        self.calls: dict = {"spawn": 0, "terminate": 0, "notice_sends": []}
        self.procs: list = []

    def bot_uin(self) -> str:
        return "3655185302"

    def bridge_pid_info(self, state_dir: pathlib.Path) -> dict:
        return read_info(state_dir / "bridge.pid")

    def bridge_status(self, state_dir: pathlib.Path) -> dict:
        try:
            return json.loads((state_dir / "bridge_status.json").read_text("utf-8"))
        except Exception:
            return {}

    def onebot_reachable(self) -> bool:
        return True

    def verify(self, info: dict) -> tuple[bool, str]:
        if not info:
            return False, "missing"
        return owner_matches(info)

    def spawn_bridge(self) -> None:
        self.calls["spawn"] += 1
        flags = 0x08000000 if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            [sys.executable, self.entry, "--profile", "lite",
             "--state-dir", str(self.base)],
            cwd=str(_ROOT), creationflags=flags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        self.procs.append(proc)

    def terminate(self, info: dict) -> tuple[bool, str]:
        self.calls["terminate"] += 1
        return terminate_owned(info, entry=self.entry)

    def try_send_notice(self, text: str, recipient: str) -> str:
        self.calls["notice_sends"].append({"text": text, "recipient": recipient})
        return "confirmed"


def case_real_spawn_recover(base: pathlib.Path) -> dict:
    base.mkdir(parents=True, exist_ok=True)
    checker = RealStubChecker(base)
    wd = Watchdog(_resolved(base), checker=checker, state_dir=base)
    checker.spawn_bridge()  # initial instance
    deadline = time.time() + 8
    while time.time() < deadline and not (base / "bridge.pid").exists():
        time.sleep(0.2)
    wd.tick()
    time.sleep(5.2)
    snap = wd.tick()
    initial_healthy = snap["phase"] == "healthy"

    info = read_info(base / "bridge.pid")
    killed = False
    if info:
        killed, _ = terminate_owned(info, entry=checker.entry)
        deadline = time.time() + 8
        while time.time() < deadline and owner_matches(info)[0]:
            time.sleep(0.2)

    wd.tick()  # outage + attempt1 (real spawn)
    recovered = False
    deadline = time.time() + 20
    while time.time() < deadline:
        time.sleep(0.5)
        snap = wd.tick()
        if snap["phase"] == "healthy" and snap["notices"]["by_status"].get(
                "sent", 0) >= 1:
            recovered = True
            break
    notices = NoticeStore(base / "notices.jsonl",
                          bot_uin="3655185302")._load()
    current = read_info(base / "bridge.pid")
    if current:
        terminate_owned(current, entry=checker.entry)
    for proc in checker.procs:
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    kinds = {n["kind"] for n in notices}
    ok = (initial_healthy and killed and checker.calls["spawn"] >= 2
          and recovered and "lost" not in kinds
          and kinds == {"recovered"})
    return {"pass": bool(ok), "initial_healthy": initial_healthy,
            "killed": killed, "spawn_calls": checker.calls["spawn"],
            "recovered": recovered, "notices": sorted(kinds)}


def case_static_isolation() -> dict:
    files = ["tools/qq_bridge_watchdog.py", "tools/qq_bridge_control.py",
             "tools/qq_bridge_service.py", "tools/qq_bridge_p2_stub_bridge.py"]
    hits: dict[str, list] = {}
    for rel in files:
        text = (_ROOT / rel).read_text(encoding="utf-8")
        found = [f"{i}:{ln.strip()[:100]}" for i, ln in
                 enumerate(text.splitlines(), 1) if FORBIDDEN.search(ln)]
        if found:
            hits[rel] = found
    return {"pass": not hits, "forbidden_refs": hits}


def main() -> int:
    ap = argparse.ArgumentParser()
    run_id = time.strftime("p2_%Y%m%dT%H%M%S")
    ap.add_argument("--out", default=str(_ROOT / "artifacts" / "qq_lite" / run_id))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    for name, fn in (("crash_recover", case_crash_recover),
                     ("two_attempts_lost", case_two_attempts_lost),
                     ("manual_stop_start", case_manual_stop_start),
                     ("pid_reuse_refusal", case_pid_reuse_refusal),
                     ("real_spawn_recover", case_real_spawn_recover)):
        base = out / name
        base.mkdir(parents=True, exist_ok=True)
        try:
            cases[name] = fn(base)
        except Exception as exc:  # noqa: BLE001
            cases[name] = {"pass": False, "error": f"{type(exc).__name__}: {exc}"}
    cases["static_isolation"] = case_static_isolation()
    report = {"run_id": out.name, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "profile": "lite", "pass": all(c.get("pass") for c in cases.values()),
              "cases": cases}
    (out / "restart_matrix.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[p2] out={out} pass={report['pass']}")
    for name, case in cases.items():
        print(f"[p2] {name} = {case.get('pass')}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
