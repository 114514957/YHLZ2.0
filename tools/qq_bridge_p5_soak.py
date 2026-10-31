"""P5 fault-injection / soak harness (offline).

Runs the real Lite watchdog + service against a local fake OneBot WebSocket:
faults (WS drop, bridge kill, watchdog kill, duplicate watchdog) are injected
on a schedule; instances, resources and notices are sampled. No real QQ, no
daemon, no models.

Usage:
    .venv\\Scripts\\python.exe tools\\qq_bridge_p5_soak.py --minutes 30 --out artifacts\\qq_lite\\fault_30min
    .venv\\Scripts\\python.exe tools\\qq_bridge_p5_soak.py --minutes 120 --out artifacts\\qq_lite\\soak_2h
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import socket
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backend.qq_bridge_lock import (  # noqa: E402
    owner_matches, read_info, terminate_owned,
)
from backend.qq_bridge_notices import NoticeStore  # noqa: E402

WATCHDOG = str((_ROOT / "tools" / "qq_bridge_watchdog.py").resolve())
SERVICE = str((_ROOT / "tools" / "qq_bridge_service.py").resolve())
FULL_PROCS = ("yhlz_launcher", "target_daemon", "llama-server", "ollama")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _write_env(base: pathlib.Path, uin: str, port: int) -> dict:
    state = base / "state"
    state.mkdir(parents=True, exist_ok=True)
    onebot = base / f"onebot11_{uin}.json"
    onebot.write_text(json.dumps({
        "network": {"websocketServers": [{
            "enable": True, "host": "127.0.0.1", "port": port, "token": ""}]}
    }), encoding="utf-8")
    profile = base / "qq_bridge_lite.json"
    profile.write_text(json.dumps({
        "profile": "lite", "uin": uin, "master_uins": ["2258374446"],
        "onebot_config": str(onebot), "manage_napcat": "owned",
        "dev_backend": "dsh", "heartbeat_seconds": 5,
        "pong_timeout_seconds": 3, "status_interval_seconds": 2,
        "recovery": {"check_interval_seconds": 1,
                     "attempt_timeout_seconds": 15,
                     "attempt2_delay_seconds": 2,
                     "stall_seconds": 30, "start_grace_seconds": 30,
                     "backoff_seconds": [5, 15, 30],
                     "blocked_after_failures": 5,
                     "blocked_retry_seconds": 60},
    }, ensure_ascii=False), encoding="utf-8")
    return {"state": state, "profile": profile, "onebot": onebot, "uin": uin}


class FakeOneBot:
    def __init__(self) -> None:
        self.clients: set = set()
        self.drops = 0

    async def handler(self, ws) -> None:
        self.clients.add(ws)
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                echo = msg.get("echo")
                if echo:
                    try:
                        await ws.send(json.dumps(
                            {"echo": echo, "status": "ok", "retcode": 0}))
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            self.clients.discard(ws)

    async def drop_all(self) -> None:
        self.drops += 1
        for ws in list(self.clients):
            try:
                await ws.close()
            except Exception:
                pass

    async def heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(3)
            for ws in list(self.clients):
                try:
                    await ws.send(json.dumps({
                        "post_type": "meta_event",
                        "meta_event_type": "heartbeat",
                        "status": {"online": True, "good": True}}))
                except Exception:
                    pass


def _spawn_watchdog(env: dict) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, WATCHDOG, "--profile", "lite",
         "--config", str(env["profile"]), "--state-dir", str(env["state"])],
        cwd=str(_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _proc_snapshot() -> set:
    out = set()
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "name"]):
            out.add((proc.info["pid"], proc.info["name"]))
    except Exception:
        pass
    return out


def _resource_sample(pid: int) -> dict:
    try:
        import psutil

        p = psutil.Process(pid)
        with p.oneshot():
            return {"rss_mb": round(p.memory_info().rss / 1048576, 1),
                    "cpu_pct": p.cpu_percent(interval=None)}
    except Exception:
        return {"rss_mb": 0.0, "cpu_pct": 0.0}


async def run_soak(minutes: float, out: pathlib.Path, uin: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    env = _write_env(out, uin, port)
    server = FakeOneBot()

    import websockets

    async with websockets.serve(server.handler, "127.0.0.1", port):
        hb = asyncio.create_task(server.heartbeat_loop())
        full_before = _proc_snapshot()
        watchdog = {"proc": None, "restarts": 0, "dup_rejected": 0}
        watchdog["proc"] = _spawn_watchdog(env)
        duration = max(60.0, float(minutes) * 60)
        interval = max(15.0, duration / 10)
        faults = []
        kinds = ["ws_drop", "kill_bridge", "kill_watchdog", "dup_watchdog",
                 "ws_drop", "kill_bridge"]
        for i, kind in enumerate(kinds):
            faults.append((interval * (i + 1), kind))
        samples = []
        resource_rows = []
        faults_done = []
        self_heals = 0
        recoveries = 0
        max_instances = 0
        start = time.time()
        next_fault = 0
        next_res = start
        last_bridge_pid = 0
        try:
            while time.time() - start < duration:
                await asyncio.sleep(1.0)
                elapsed = time.time() - start
                info = read_info(env["state"] / "bridge.pid")
                alive, _reason = owner_matches(info) if info else (False, "none")
                wd_alive = watchdog["proc"] is not None and \
                    watchdog["proc"].poll() is None
                # duplicate watchdog attempt as an injection
                while next_fault < len(faults) and elapsed >= faults[next_fault][0]:
                    kind = faults[next_fault][1]
                    next_fault += 1
                    faults_done.append({"t": round(elapsed, 1), "kind": kind})
                    if kind == "ws_drop":
                        await server.drop_all()
                    elif kind == "kill_bridge" and alive:
                        terminate_owned(info, entry=SERVICE)
                    elif kind == "kill_watchdog" and wd_alive:
                        wd_info = read_info(env["state"] / "watchdog.lock")
                        terminate_owned(wd_info, entry=WATCHDOG)
                        await asyncio.sleep(1)
                        watchdog["proc"] = _spawn_watchdog(env)
                        watchdog["restarts"] += 1
                    elif kind == "dup_watchdog":
                        dup = _spawn_watchdog(env)
                        try:
                            rc = dup.wait(timeout=10)
                        except Exception:
                            dup.kill()
                            rc = -1
                        if rc != 0:
                            watchdog["dup_rejected"] += 1
                info = read_info(env["state"] / "bridge.pid")
                alive, _ = owner_matches(info) if info else (False, "none")
                if alive and last_bridge_pid and info.get("pid") != last_bridge_pid:
                    recoveries += 1
                if alive:
                    last_bridge_pid = info.get("pid")
                instances = (1 if alive else 0) + (1 if wd_alive else 0)
                max_instances = max(max_instances, instances)
                if time.time() >= next_res:
                    next_res = time.time() + 10
                    row = {"t": round(elapsed, 1)}
                    if alive:
                        row.update(_resource_sample(int(info["pid"])))
                    if wd_alive:
                        wd_res = _resource_sample(watchdog["proc"].pid)
                        row["wd_rss_mb"] = wd_res["rss_mb"]
                    resource_rows.append(row)
                samples.append({"t": round(elapsed, 1), "bridge_alive": alive,
                                "watchdog_alive": wd_alive})
                # detect WS-only self-heal: bridge pid unchanged but reconnect
                if info and info.get("pid") == last_bridge_pid and alive:
                    status = {}
                    try:
                        status = json.loads(
                            (env["state"] / "bridge_status.json").read_text(
                                encoding="utf-8"))
                    except Exception:
                        pass
                    if status.get("state") == "connected":
                        self_heals += 1
        finally:
            if watchdog["proc"] is not None:
                terminate_owned(read_info(env["state"] / "watchdog.lock"),
                                entry=WATCHDOG)
                if watchdog["proc"].poll() is None:
                    watchdog["proc"].kill()
            info = read_info(env["state"] / "bridge.pid")
            if info:
                terminate_owned(info, entry=SERVICE)
            hb.cancel()
            await asyncio.gather(hb, return_exceptions=True)

        full_after = _proc_snapshot()
        new_full = [p for p in (full_after - full_before)
                    if any(k in str(p[1]) for k in FULL_PROCS)]
        notices = NoticeStore(env["state"] / "notices.jsonl",
                              bot_uin=uin).summary()
        report = {
            "run_id": out.name,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "minutes": minutes,
            "profile": "lite",
            "faults_injected": faults_done,
            "ws_drops": server.drops,
            "watchdog_restarts": watchdog["restarts"],
            "duplicate_watchdog_rejected": watchdog["dup_rejected"],
            "bridge_recoveries": recoveries,
            "max_managed_instances": max_instances,
            "full_service_processes_started": new_full,
            "notices": notices,
            "resource_samples": resource_rows,
            "samples": len(samples),
        }
        report["pass"] = all((
            max_instances <= 2,               # 1 bridge + 1 watchdog
            not new_full,
            server.drops >= 1,
            watchdog["dup_rejected"] >= 1,
            recoveries >= 1,
        ))
        name = "fault_30min.json" if minutes <= 31 else "soak_2h.json"
        if minutes <= 3:
            name = "smoke.json"
        (out / name).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        with (out / "resource.csv").open("w", encoding="utf-8") as f:
            f.write("t,rss_mb,cpu_pct,wd_rss_mb\n")
            for row in resource_rows:
                f.write(f"{row.get('t', '')},{row.get('rss_mb', '')},"
                        f"{row.get('cpu_pct', '')},{row.get('wd_rss_mb', '')}\n")
        return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--uin", default="3655185399")
    args = ap.parse_args()
    report = asyncio.run(run_soak(args.minutes, pathlib.Path(args.out),
                                  args.uin))
    print(f"[p5] out={args.out} pass={report['pass']} "
          f"faults={len(report['faults_injected'])} "
          f"recoveries={report['bridge_recoveries']} "
          f"dup_rejected={report['duplicate_watchdog_rejected']}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
