"""YHLZ watchdog (ledger 0226): keep the stack alive.

Every interval: check ollama(11434) / gemma(8081) / daemon(8321); restart any
that died. Meant to run at logon (startup folder shortcut, pythonw = no window)
so Yuanheng is "always there" (autonomy cadence / weekly report depend on it).

Usage: python tools/yhlz_watchdog.py [--interval 60] [--once]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

LOG = _ROOT / "cache" / "watchdog.log"
NOTIFY_FILE = _ROOT / "cache" / "qqwatch" / "notifications.json"
STATE_FILE = _ROOT / "cache" / "tmp" / "watchdog_state.json"
LOCK_FILE = _ROOT / "cache" / "tmp" / "watchdog.lock"
QQ_SILENT_FLAG = _ROOT / "cache" / "tmp" / "qq_silent.flag"
_LOCK_FD: int | None = None


def _qq_silent() -> bool:
    """Dev-mode QQ silence (0469): skip NapCat auto-start / auto-login.

    Enabled by env YHLZ_QQ_SILENT=1 or by the flag file
    cache/tmp/qq_silent.flag (exists = silent). While silent the watchdog
    never launches NapCat windows and never notifies about QQ being offline;
    it still logs state changes once.
    """
    if str(os.getenv("YHLZ_QQ_SILENT", "")).strip().lower() in ("1", "true", "yes", "on"):
        return True
    return QQ_SILENT_FLAG.exists()


def _acquire_singleton() -> bool:
    """F2 (ledger 0436): only one watchdog may respawn services.

    Two instances raced on 09-19 and each spawned/killed on its own rhythm.
    Fail-open: if locking is unavailable we still run (never lose the guard).
    """
    global _LOCK_FD
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR)
        try:
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except Exception:
            os.close(fd)
            return False
        _LOCK_FD = fd
        return True
    except Exception:
        return True


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False),
                              encoding="utf-8")
    except Exception:
        pass


def _daemon_pids() -> list[int]:
    try:
        import psutil
    except Exception:
        return []
    out: list[int] = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = p.info.get("cmdline") or []
        except Exception:
            continue
        if any("target_daemon" in str(x) for x in cl):
            out.append(int(p.info["pid"]))
    return out


def _kill_daemon() -> int:
    try:
        import psutil
    except Exception:
        return 0
    killed = 0
    for pid in _daemon_pids():
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            killed += 1
        except Exception:
            pass
    return killed


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
    state = _load_state()
    # F2: /health can time out while the daemon is alive (busy turn/DB). Only
    # after 3 consecutive bad ticks AND with the process still alive do we
    # kill+restart; otherwise ensure_stack is self-guarded (process/port).
    if before.get("daemon", True):
        state["daemon_bad"] = 0
    else:
        state["daemon_bad"] = int(state.get("daemon_bad") or 0) + 1
        bad = state["daemon_bad"]
        pids = _daemon_pids()
        if (bad >= 3 and pids
                and time.time() - float(state.get("daemon_kill_ts") or 0) > 600):
            _log(f"daemon 连续 {bad} 次不健康且进程存活 -> 重启（F2）")
            n = _kill_daemon()
            state["daemon_kill_ts"] = time.time()
            state["daemon_bad"] = 0
            time.sleep(3)
            ensure_stack()
            _log(f"daemon 已重启（清理旧进程 {n} 个）")
        elif bad <= 3 or bad % 30 == 0:
            _log(f"daemon 不健康（第 {bad} 次，存活进程 {len(pids)} 个）")
    _save_state(state)
    if down:
        ensure_stack()  # F2: self-guarded — alive process/port is left alone
        time.sleep(3)
    after = status()

    # --- NapCat / 元亨 online watchdog ---
    # 0469: dev-mode silence — never auto-start NapCat / auto-login / notify.
    silent = _qq_silent()
    ns = napcat_status()
    online = bool(ns.get("online"))
    ws_up = bool(ns.get("ws"))
    if silent:
        if not getattr(tick, "_qq_silent_logged", False):
            _log("QQ 静默中（开发模式）：跳过 NapCat 拉起/自动登录（flag=cache/tmp/qq_silent.flag）")
            tick._qq_silent_logged = True
    else:
        tick._qq_silent_logged = False
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
        if not silent:
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
    if not _acquire_singleton():
        _log("已有看门狗实例在运行，本实例退出（F2 单实例锁）")
        return 0
    if a.once:
        st = tick()
        _log(f"once: {st}")
        return 0 if all(st.values()) else 1
    _log(f"看门狗启动，每 {a.interval:.0f}s 巡检一次（单实例锁已持有）")
    bad_streak = 0
    while True:
        try:
            st = tick()
            if not all(st.values()):
                bad_streak += 1
                if bad_streak <= 3 or bad_streak % 10 == 0:
                    _log(f"仍掉线: {st}（连续 {bad_streak} 次）")
            else:
                bad_streak = 0
        except Exception as exc:  # noqa: BLE001
            _log(f"巡检异常 {type(exc).__name__}: {exc}")
        time.sleep(max(10.0, a.interval))


if __name__ == "__main__":
    raise SystemExit(main())
