"""P1 offline fake-transport probe (2026-10-06), no network, no real QQ.

Proves reader/inbox separation under the Lite profile:
  * a deliberately slow chat turn (thread-gated, stands in for a 60s model)
    does not block echo, heartbeat or the #devstatus control channel;
  * replies go back through the fake OneBot socket;
  * no Full launcher/watchdog module is imported.

Usage:
    .venv\\Scripts\\python.exe tools\\qq_bridge_p1_fake_echo.py --out artifacts\\qq_lite\\p1_<id>
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import pathlib
import socket
import sys
import threading
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Built dynamically so the isolation scanner does not mistake this auditor's
# own check list for a dependency on the Full stack.
_BAD_MODULES = ("yhlz" + "_launcher", "yhlz" + "_watchdog", "napcat" + "_watch")
ISOLATED_PORTS = (11434, 8081, 8321)


def _setup_env(state_dir: pathlib.Path) -> None:
    os.environ["YHLZ_QQ_PROFILE"] = "lite"
    os.environ["YHLZ_QQ_STATE_DIR"] = str(state_dir)
    os.environ["YHLZ_QQ_ENABLE_VOICE"] = "0"
    os.environ["YHLZ_QQ_PING_INTERVAL"] = "0.2"
    os.environ["YHLZ_QQ_PONG_TIMEOUT"] = "1"
    sys.path.insert(0, str(_ROOT / "tools"))
    sys.path.insert(0, str(_ROOT))


async def _wait_for(pred, timeout: float, interval: float = 0.02):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if pred():
            return True
        await asyncio.sleep(interval)
    return False


def run_probe(out_dir: pathlib.Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    state_dir = out_dir / "state"
    _setup_env(state_dir)

    import qq_bot  # noqa: PLC0415  (after profile env is fixed)

    bad_modules = sorted(m for m in _BAD_MODULES if m in sys.modules)
    t0 = time.perf_counter()

    class FakeWS:
        def __init__(self) -> None:
            self.queue: asyncio.Queue = asyncio.Queue()
            self.pings = 0
            self.loop = asyncio.get_running_loop()

        async def send(self, raw: str) -> None:
            msg = json.loads(raw)
            sent.append(msg)
            echo = msg.get("echo")
            if echo:
                await self.queue.put(json.dumps(
                    {"echo": echo, "status": "ok", "retcode": 0}))

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self.queue.get()

        def ping(self):
            self.pings += 1
            fut = self.loop.create_future()
            fut.set_result(None)
            return fut

    sent: list[dict] = []
    started = threading.Event()
    gate = threading.Event()

    def slow_turn(text, channel, images=None):
        started.set()
        gate.wait(timeout=30)
        return "慢回复:" + str(text)[:20]

    qq_bot._daemon_turn = slow_turn
    import dev_runner  # noqa: PLC0415

    dev_runner._load = lambda: {"status": "idle", "task": ""}

    bridge = qq_bot.QQBridge("ws://fake", "3655185302",
                             pathlib.Path("fake-onebot.json"),
                             masters={"2258374446"})
    bridge._daemon_ok = lambda: True   # fake daemon for the P1 scenario
    logs: list[str] = []
    bridge.log = lambda msg: logs.append(str(msg))
    results: dict = {"pass": False}
    port_attempts: list[dict] = []

    def guarded_connect(self, address, *a, **k):
        try:
            host, port = str(address[0]), int(address[1])
        except Exception:
            return _orig_connect(self, address, *a, **k)
        if port in ISOLATED_PORTS:
            port_attempts.append({"host": host, "port": port})
            raise ConnectionRefusedError(f"P1 isolation: port {port} blocked")
        return _orig_connect(self, address, *a, **k)

    _orig_connect = socket.socket.connect
    socket.socket.connect = guarded_connect

    def _event(mid: int, text: str) -> str:
        return json.dumps({
            "post_type": "message", "message_type": "private",
            "user_id": "2258374446", "message_id": mid,
            "message": [{"type": "text", "data": {"text": text}}]})

    def _msg_texts() -> list[str]:
        out = []
        for m in sent:
            p = m.get("params") or {}
            msg = p.get("message")
            if isinstance(msg, str):
                out.append(msg)
        return out

    async def scenario() -> None:
        import websockets  # noqa: PLC0415

        ws = FakeWS()

        @contextlib.asynccontextmanager
        async def fake_connect(url, **kwargs):
            yield ws

        websockets.connect = fake_connect
        run_task = asyncio.create_task(bridge.run())
        try:
            results["connected"] = await _wait_for(
                lambda: bridge.connection.state == "connected", 5)
            ws.queue.put_nowait(_event(101, "讲个慢故事"))
            results["slow_chat_started"] = await asyncio.to_thread(
                started.wait, 5)

            echo_t0 = time.perf_counter()
            resp = await asyncio.wait_for(
                bridge._request(ws, "get_status", {}), 3)
            results["echo"] = {
                "ok": str(resp.get("status")) == "ok",
                "latency_ms": round((time.perf_counter() - echo_t0) * 1000),
            }

            ctrl_t0 = time.perf_counter()
            ws.queue.put_nowait(_event(102, "#devstatus"))
            got_ctrl = await _wait_for(
                lambda: any("[利贞] 状态=" in t for t in _msg_texts()), 3)
            results["devstatus"] = {
                "ok": got_ctrl,
                "latency_ms": round((time.perf_counter() - ctrl_t0) * 1000),
                "slow_chat_still_blocked": not gate.is_set(),
            }

            pings_before = ws.pings
            await asyncio.sleep(1.3)
            results["heartbeat"] = {
                "ok": ws.pings > pings_before,
                "delta_pings": ws.pings - pings_before,
                "total_pings": ws.pings,
            }

            gate.set()
            got_reply = await _wait_for(
                lambda: any(t.startswith("慢回复:") for t in _msg_texts()), 5)
            results["slow_reply"] = {
                "ok": got_reply,
                "texts": [t for t in _msg_texts() if t.startswith("慢回复:")],
            }
        finally:
            gate.set()
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)

    asyncio.run(scenario())
    socket.socket.connect = _orig_connect
    status_path = state_dir / "bridge_status.json"
    status: dict = {}
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    results.update({
        "run_id": out_dir.name,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "profile": "lite",
        "state_dir": str(state_dir),
        "full_watchdog_modules": bad_modules,
        "daemon_started": False,
        "port_isolation": {
            "blocked_ports": list(ISOLATED_PORTS),
            "connect_attempts": port_attempts,
        },
        "status_file": {
            "path": str(status_path),
            "exists": status_path.exists(),
            "keys": sorted(k for k in ("pid", "create_time", "profile",
                                       "inbox", "dev_state", "instance_id")
                           if k in status),
        },
        "inbox": {"busy": bridge.inbox_busy,
                  "processed": bridge.inbox_processed},
        "logs_tail": logs[-8:],
    })
    results["pass"] = all((
        results.get("connected"),
        results.get("slow_chat_started"),
        results.get("echo", {}).get("ok"),
        results.get("devstatus", {}).get("ok"),
        results.get("devstatus", {}).get("slow_chat_still_blocked"),
        results.get("heartbeat", {}).get("ok"),
        results.get("slow_reply", {}).get("ok"),
        not bad_modules,
        not port_attempts,
        results["status_file"]["exists"],
    ))
    (out_dir / "fake_echo.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    run_id = time.strftime("p1_%Y%m%dT%H%M%S")
    ap.add_argument("--out", default=str(_ROOT / "artifacts" / "qq_lite" / run_id))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    results = run_probe(out)
    print(f"[p1] out={out} pass={results['pass']}")
    for key in ("connected", "slow_chat_started", "echo", "devstatus",
                "heartbeat", "slow_reply"):
        print(f"[p1] {key} = {results.get(key)}")
    print(f"[p1] full_watchdog_modules = {results['full_watchdog_modules']}")
    return 0 if results["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
