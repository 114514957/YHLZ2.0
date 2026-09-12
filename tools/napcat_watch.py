"""NapCat / 元亨 online watcher.

Connects to the OneBot WS, tracks the heartbeat `status.online` flag, writes
cache/tmp/napcat_status.json, and when the account recovers from an offline
period sends the master a catch-up QQ message (since an offline bot cannot
notify anyone at the moment it goes down).

Started by the launcher/watchdog. Usage: python tools/napcat_watch.py
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
from backend.qq_token import ws_url  # noqa: E402
from backend.yhlz_paths import MASTER_UIN  # noqa: E402

STATUS = _ROOT / "cache" / "tmp" / "napcat_status.json"
LOCK = _ROOT / "cache" / "tmp" / "napcat_watch.lock"
URL = ws_url()
MASTER = int(MASTER_UIN)


def _acquire_lock() -> bool:
    import atexit

    def alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    if LOCK.exists():
        try:
            old = int(LOCK.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            old = 0
        if old and alive(old):
            return False
        LOCK.unlink(missing_ok=True)
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        return False
    atexit.register(lambda: LOCK.unlink(missing_ok=True))
    return True


def _write(online: bool, ws_up: bool) -> None:
    try:
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        prev = {}
        if STATUS.exists():
            try:
                prev = json.loads(STATUS.read_text(encoding="utf-8"))
            except Exception:
                prev = {}
        since = prev.get("since")
        if prev.get("online") != online or prev.get("ws") != ws_up:
            since = time.time()
        STATUS.write_text(json.dumps(
            {"online": online, "ws": ws_up, "ts": time.time(),
             "since": since or time.time()}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


async def main() -> int:
    import websockets

    if not _acquire_lock():
        print("[napcat_watch] 已有实例在运行，退出", flush=True)
        return 1
    was_offline = False
    offline_since = 0.0
    while True:
        try:
            async with websockets.connect(URL, open_timeout=5) as ws:
                _write(False, True)  # connected, online unknown yet
                async for raw in ws:
                    try:
                        ev = json.loads(raw)
                    except Exception:
                        continue
                    if (ev.get("post_type") == "meta_event"
                            and ev.get("meta_event_type") == "heartbeat"):
                        on = bool((ev.get("status") or {}).get("online"))
                        _write(on, True)
                        if not on:
                            was_offline = True
                            if not offline_since:
                                offline_since = time.time()
                        elif on and was_offline:
                            mins = int((time.time() - offline_since) / 60) \
                                if offline_since else 0
                            dur = f"（约 {mins} 分钟）" if mins >= 1 else ""
                            try:
                                await ws.send(json.dumps({
                                    "action": "send_msg",
                                    "params": {"message_type": "private",
                                               "user_id": MASTER,
                                               "message": f"（元亨）我刚才掉线了{dur}，"
                                                          "现在已经恢复上线啦。"},
                                    "echo": "napcatwatch"}))
                            except Exception:
                                pass
                            was_offline = False
                            offline_since = 0.0
        except Exception:
            _write(False, False)
        await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
