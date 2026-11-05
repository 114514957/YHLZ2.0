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
    """Daemon PIDs (hardened 2026-10-12: python interpreter whose argv
    element ends with `target_daemon`; shells that merely mention the name
    are ignored — F2 must never kill innocent processes)."""
    try:
        import psutil
    except Exception:
        return []
    out: list[int] = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            nm = str(p.info.get("name") or "").lower()
            cl = [str(x).replace("\\", "/").lower()
                  for x in (p.info.get("cmdline") or [])]
        except Exception:
            continue
        if nm.startswith("python") and any(
                x.endswith("target_daemon") for x in cl):
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


BACKUP_STAMP = _ROOT / "cache" / "backup_last.json"
BACKUP_HOUR = int(os.getenv("YHLZ_BACKUP_HOUR", "9"))
# 2026-11-05（台账 1097）：ollama 是可选项（launcher 里 YHLZ_START_OLLAMA 默认关）。
# 老逻辑把它算进 all(status.values())，于是每个 tick 都判"掉线"，每 10 个 tick 记一行
# "仍掉线"，还每轮多跑一次 ensure_stack —— watchdog.log 累计 2,600 行、launcher.log
# 9,042 行 'ollama': False 全是这么来的。健康判定只看必选项。
OPTIONAL_CHECKS = {"ollama"}


def _down_keys(st: dict) -> list[str]:
    return [k for k, v in st.items() if not v and k not in OPTIONAL_CHECKS]


def _healthy(st: dict) -> bool:
    return not _down_keys(st)


def _daily_backup() -> None:
    """Daily slim snapshot — deliberately NOT gated by the autonomy flag.

    2026-10-24 关掉自主后，daemon 的每周维护（连带快照）一起停了，于是
    10/24~11/05 没有任何备份（台账 1096）。备份是纯 I/O，不是自主思考，
    所以放进 supervisor：每天过一次，排除可重建的 kw_index（约 117 MB）。
    """
    try:
        if time.localtime().tm_hour < BACKUP_HOUR:
            return
        today = time.strftime("%Y-%m-%d")
        last = ""
        try:
            last = str(json.loads(
                BACKUP_STAMP.read_text(encoding="utf-8")).get("date", ""))
        except Exception:
            last = ""
        if last == today:
            return
        from backend import snapshots

        dest = snapshots.create("daily", exclude=("kw_index",))
        BACKUP_STAMP.parent.mkdir(parents=True, exist_ok=True)
        BACKUP_STAMP.write_text(json.dumps(
            {"date": today, "snapshot": dest, "ts": time.time()},
            ensure_ascii=False), encoding="utf-8")
        _log(f"每日备份完成: {pathlib.Path(dest).name if dest else '失败'}")
    except Exception as exc:  # noqa: BLE001
        _log(f"每日备份失败 {type(exc).__name__}: {exc}")


def tick() -> dict:
    from yhlz_launcher import (ensure_stack, napcat_status, qq_management,
                               qqbot_status, status, _port_open, _proc_alive,
                               _reap_legacy_qq, _spawn_napcat)

    before = status()
    down = _down_keys(before)
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
    # 2026-10-07: qq_management=external — QQ 由独立 Lite 链负责，
    # Full 看门狗不再启动/重启 NapCat、QQ 桥或发送 QQ 通知。
    if qq_management() == "external":
        if not getattr(tick, "_qq_external_logged", False):
            _log("QQ 管理=external：跳过 NapCat/QQ桥/napcat_watch（Lite 链负责）")
            tick._qq_external_logged = True
        # 0830：旧链不一定会等到某个服务掉线才出现（老快捷方式/老脚本随时
        # 拉起 qq_bot.py / napcat_watch.py）。每个 tick 都收一遍，保证同一个
        # QQ 号只有 Lite 一个消费者。
        try:
            reaped = _reap_legacy_qq()
            if reaped:
                _log(f"external：收掉旧 QQ 链残留 {reaped}")
        except Exception as exc:  # noqa: BLE001
            _log(f"旧链清理异常 {type(exc).__name__}: {exc}")
        return after
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
        return 0 if _healthy(st) else 1
    _log(f"看门狗启动，每 {a.interval:.0f}s 巡检一次（单实例锁已持有）")
    bad_streak = 0
    while True:
        try:
            st = tick()
            if not _healthy(st):
                bad_streak += 1
                if bad_streak <= 3 or bad_streak % 10 == 0:
                    _log(f"仍掉线: {_down_keys(st)}（连续 {bad_streak} 次）")
            else:
                bad_streak = 0
        except Exception as exc:  # noqa: BLE001
            _log(f"巡检异常 {type(exc).__name__}: {exc}")
        _daily_backup()
        time.sleep(max(10.0, a.interval))


if __name__ == "__main__":
    raise SystemExit(main())
