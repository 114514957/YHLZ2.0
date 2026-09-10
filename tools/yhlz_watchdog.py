"""YHLZ watchdog (ledger 0226): keep the stack alive.

Every interval: check ollama(11434) / gemma(8081) / daemon(8321); restart any
that died. Meant to run at logon (startup folder shortcut, pythonw = no window)
so Yuanheng is "always there" (autonomy cadence / weekly report depend on it).

Usage: python tools/yhlz_watchdog.py [--interval 60] [--once]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

LOG = _ROOT / "cache" / "watchdog.log"
NOTIFY_FILE = _ROOT / "cache" / "qqwatch" / "notifications.json"


def _notify(text: str) -> None:
    """Push a notice into the same bounded queue the workbench reads."""
    try:
        NOTIFY_FILE.parent.mkdir(parents=True, exist_ok=True)
        entries = []
        if NOTIFY_FILE.exists():
            try:
                entries = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
            except Exception:
                entries = []
        entries.append({"ts": time.time(), "text": str(text)[:600]})
        del entries[:-8]
        NOTIFY_FILE.write_text(json.dumps(entries, ensure_ascii=False),
                               encoding="utf-8")
    except Exception:
        pass


def _log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def tick() -> dict:
    from yhlz_launcher import (ensure_stack, napcat_status, qqbot_status,
                               status, _port_open, _proc_alive, _spawn_napcat)

    before = status()
    down = [k for k, v in before.items() if not v]
    if down:
        _log(f"检测到掉线 {down} -> 拉起")
        ensure_stack()
        time.sleep(3)
    after = status()

    # --- NapCat / 元亨 online watchdog ---
    ns = napcat_status()
    online = bool(ns.get("online"))
    ws_up = bool(ns.get("ws"))
    if not ws_up and not _proc_alive("NapCat"):
        if time.time() - getattr(tick, "_napcat_try", 0) > 600:
            _log("NapCat 未运行 -> 尝试拉起")
            _spawn_napcat()
            tick._napcat_try = time.time()
    if ws_up and not online:
        since = float(ns.get("since") or 0)
        tries = getattr(tick, "_relogin_tries", 0)
        if (since and time.time() - since > 120 and tries < 3
                and time.time() - getattr(tick, "_relogin_try", 0) > 900):
            _log(f"元亨掉线>2min -> 尝试重启 NapCat 自动登录(第{tries + 1}次)")
            _spawn_napcat()
            tick._relogin_try = time.time()
            tick._relogin_tries = tries + 1
    elif online:
        tick._relogin_tries = 0
    state = (online, ws_up)
    if state != getattr(tick, "_napcat", None):
        msg = ("元亨在线" if online else
               ("NapCat/OneBot 未监听" if not ws_up else
                "元亨 QQ 掉线，需在 NapCat 重新登录"))
        _log("NapCat状态: " + msg)
        _notify("【YHLZ】" + msg)
        tick._napcat = state

    qb = qqbot_status()
    if qb != getattr(tick, "_last_qb", None):
        _log(f"QQ桥: {'在线' if qb else '未运行/未登录'}")
        tick._last_qb = qb
    return after


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    if a.once:
        st = tick()
        _log(f"once: {st}")
        return 0 if all(st.values()) else 1
    _log(f"看门狗启动，每 {a.interval:.0f}s 巡检一次")
    while True:
        try:
            st = tick()
            if not all(st.values()):
                _log(f"仍掉线: {st}")
        except Exception as exc:  # noqa: BLE001
            _log(f"巡检异常 {type(exc).__name__}: {exc}")
        time.sleep(max(10.0, a.interval))


if __name__ == "__main__":
    raise SystemExit(main())
