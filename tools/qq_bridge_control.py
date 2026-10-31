"""QQ Bridge Lite control: status / stop / start / restart (P2/P5).

Owns the whole Lite chain: NapCat (owned instances only), watchdog and
bridge. Only touches processes whose recorded pid + create_time + entry
match; never touches daemon/models or a NapCat it did not start/adopt.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import socket
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

from backend.qq_bridge_lock import (  # noqa: E402
    make_info, owner_matches, proc_create_time, read_info, terminate_owned,
)
from backend.qq_bridge_notices import NoticeStore  # noqa: E402
from backend.qq_bridge_state import path as _bridge_path  # noqa: E402

from qq_bridge_service import (  # noqa: E402
    DEFAULT_CONFIG, ProfileError, load_profile, read_desired, resolve,
    write_desired,
)

BRIDGE_ENTRY = str((_ROOT / "tools" / "qq_bridge_service.py").resolve())
WATCHDOG_ENTRY = str((_ROOT / "tools" / "qq_bridge_watchdog.py").resolve())
NAPCAT_ENTRY = "NapCatWinBootMain.exe"


def _role_info(state_dir: pathlib.Path, role: str, entry: str) -> dict:
    if role == "bridge":
        info = read_info(state_dir / "bridge.pid")
        if info:
            return info
        info = read_info(state_dir / "bridge.lock")
    else:
        info = read_info(state_dir / "watchdog.lock")
    info = dict(info)
    info.setdefault("entry", entry)
    return info


def _read_json(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: pathlib.Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)


# ---- NapCat (owned) ---------------------------------------------------------
def _onebot_target(resolved: dict) -> tuple[str, int]:
    try:
        import qq_bot

        cfg = pathlib.Path(resolved["onebot_config"]) \
            if resolved.get("onebot_config") else \
            qq_bot._find_onebot_config(resolved.get("uin"))
        s = qq_bot._ws_settings(cfg) or {}
        return str(s.get("host") or "127.0.0.1"), int(s.get("port") or 3001)
    except Exception:
        return "127.0.0.1", 3001


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _napcat_info(state_dir: pathlib.Path) -> dict:
    return read_info(state_dir / "napcat.pid")


def _newest_napcat(since: float = 0.0) -> dict | None:
    try:
        import psutil

        best = None
        for proc in psutil.process_iter(["pid", "name", "create_time"]):
            if proc.info["name"] != NAPCAT_ENTRY:
                continue
            created = float(proc.info["create_time"] or 0)
            if created + 1 < since:
                continue
            if best is None or created > best["create_time"]:
                best = {"pid": proc.info["pid"], "create_time": created}
        return best
    except Exception:
        return None


def ensure_napcat(resolved: dict, *, wait_s: float = 90.0,
                  log=print) -> dict:
    state_dir = pathlib.Path(resolved["state_dir"])
    host, port = _onebot_target(resolved)
    if _port_open(host, port):
        info = _napcat_info(state_dir)
        alive = False
        if info:
            alive, _reason = owner_matches(info)
        if not alive:
            found = _newest_napcat()
            if found:
                info = make_info(resolved["profile"], entry=NAPCAT_ENTRY,
                                 role="napcat")
                info.update(found, adopted=True)
                _write_json(state_dir / "napcat.pid", info)
            else:
                info = None
        return {"port_open": True, "started": False,
                "adopted": bool(info), "pid": (info or {}).get("pid")}
    # A process still loading or waiting for login must not be duplicated.
    existing = _newest_napcat()
    if existing:
        return {"port_open": False, "started": False, "pid": existing["pid"],
                "awaiting_login": True, "error": "NapCat 已运行，正在等待登录"}
    started_at = time.time()
    try:
        from backend.napcat_launcher import launch_napcat

        launch_napcat(str(resolved.get("uin") or "3655185302"))
    except Exception as exc:  # noqa: BLE001
        return {"port_open": False, "started": False,
                "error": f"NapCat 启动失败: {type(exc).__name__}: {exc}"}
    deadline = time.time() + max(10.0, float(wait_s))
    while time.time() < deadline:
        if _port_open(host, port):
            found = _newest_napcat(since=started_at) or {}
            info = make_info(resolved["profile"], entry=NAPCAT_ENTRY,
                             role="napcat")
            if found:
                info.update(found)
            _write_json(state_dir / "napcat.pid", info)
            return {"port_open": True, "started": True,
                    "pid": info.get("pid")}
        time.sleep(3)
    return {"port_open": False, "started": True,
            "error": f"NapCat 已拉起但 {host}:{port} 在 {wait_s:.0f}s 内未监听"
                     "（可能需要在窗口里登录）"}


def _napcat_pipe_pids() -> list[int]:
    r"""\\.\pipe\NapCat_<pid> —— NapCat 注入后的进程会挂这根管道（识别特征）。"""
    pids: list[int] = []
    try:
        for name in os.listdir("\\\\.\\pipe\\"):
            if name.startswith("NapCat_"):
                try:
                    pids.append(int(name.split("_", 1)[1]))
                except Exception:
                    pass
    except Exception:
        pass
    return pids


def _port_owner_pid(host: str | None, port: int | None) -> int | None:
    if not port:
        return None
    try:
        import psutil

        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_LISTEN and c.laddr \
                    and int(c.laddr.port) == int(port):
                if c.pid:
                    return int(c.pid)
    except Exception:
        return None
    return None


def _napcat_leftover_pids(host: str | None = None,
                          port: int | None = None) -> list[int]:
    """无有效归属记录时的兜底识别（2026-10-11 重复实例事故后新增）。

    只认 NapCat 特征 —— 命名管道 / NapCatWinBootMain 树 / 已知端口属主链；
    不碰普通 QQ，用户自己的 QQ 不受影响。
    """
    try:
        import psutil

        table: dict[int, dict] = {}
        for p in psutil.process_iter(["pid", "name", "ppid"]):
            table[int(p.info["pid"])] = {
                "name": str(p.info.get("name") or ""),
                "ppid": int(p.info.get("ppid") or 0)}
    except Exception:
        return []

    def is_napcat_name(name: str) -> bool:
        return name.lower() in ("qq.exe", "napcatwinbootmain.exe")

    seeds: set[int] = set()
    for pid in _napcat_pipe_pids():
        if pid in table:
            seeds.add(pid)
    for pid, info in table.items():
        if info["name"].lower() == "napcatwinbootmain.exe":
            seeds.add(pid)
    owner = _port_owner_pid(host, port)
    if owner and owner in table:
        seeds.add(owner)

    children: dict[int, list[int]] = {}
    for pid, info in table.items():
        children.setdefault(info["ppid"], []).append(pid)

    selected: set[int] = set()
    stack = list(seeds)
    while stack:  # 后代全收（QQ 子进程都挂在自己树下）
        pid = stack.pop()
        if pid in selected:
            continue
        selected.add(pid)
        stack.extend(children.get(pid, []))
    for pid in seeds:  # 祖先只沿着 NapCat 命名的进程往上收
        cur = table.get(pid, {}).get("ppid", 0)
        while cur and cur in table and is_napcat_name(table[cur]["name"]):
            selected.add(cur)
            cur = table[cur]["ppid"]
    # start-napcat.bat 的 cmd 宿主（按命令行精确匹配，避免误伤普通 cmd）
    for pid, info in table.items():
        if info["name"].lower() == "cmd.exe":
            try:
                cl = " ".join(psutil.Process(pid).cmdline() or []).lower()
            except Exception:
                continue
            if "start-napcat" in cl:
                selected.add(pid)

    def is_killable(pid: int) -> bool:
        return table[pid]["name"].lower() in (
            "qq.exe", "qqex.exe", "napcatwinbootmain.exe", "cmd.exe")

    return sorted(p for p in selected if p in table and is_killable(p))


def _kill_pids(pids: list[int]) -> tuple[bool, list[int]]:
    """结束给定进程集合：返回（是否全部结束, 残余 pid）。"""
    try:
        import psutil

        procs = []
        seen: set[int] = set()
        for pid in pids:
            if pid in seen:
                continue
            seen.add(pid)
            try:
                procs.append(psutil.Process(pid))
            except Exception:
                pass
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        _, alive = psutil.wait_procs(procs, timeout=8)
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass
        _, alive = psutil.wait_procs(alive, timeout=5)
        alive = [p for p in alive if p.is_running()]
        return (not alive), [int(p.pid) for p in alive]
    except Exception:
        return False, list(pids)


def stop_napcat(state_dir: pathlib.Path, *, host: str | None = None,
                port: int | None = None) -> dict:
    # v2（2026-10-11）：无有效记录也要清场——旧实例没杀干净就重启，
    # 会与新实例互挤抢号（重复实例事故教训）。
    info = _napcat_info(state_dir)
    if info:
        ok, reason = owner_matches(info)
        if ok:
            pid = int(info.get("pid") or 0)
            try:
                import psutil

                proc = psutil.Process(pid)
            except Exception:
                (state_dir / "napcat.pid").unlink(missing_ok=True)
                return {"stopped": True, "reason": "进程已不存在"}
            try:
                children = proc.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except Exception:
                        pass
                proc.terminate()
                gone, alive = psutil.wait_procs([proc, *children], timeout=8)
                for p in alive:
                    try:
                        p.kill()
                    except Exception:
                        pass
                psutil.wait_procs(alive, timeout=5)
            except Exception as exc:  # noqa: BLE001
                return {"stopped": False, "reason": f"{type(exc).__name__}"}
            (state_dir / "napcat.pid").unlink(missing_ok=True)
            # 记录树可能留有 cmd/boot 残留，兜底再清一次（幂等）
            extra = _napcat_leftover_pids(host, port)
            swept, survivors = _kill_pids(extra) if extra else (True, [])
            return {"stopped": bool(swept), "pid": pid, "via": "record",
                    "swept": len(extra) if extra else 0,
                    "survivors": survivors}
        # 记录过期/不符：清掉记录，继续走兜底识别
        (state_dir / "napcat.pid").unlink(missing_ok=True)

    leftovers = _napcat_leftover_pids(host, port)
    if not leftovers:
        return {"stopped": True, "killed": 0,
                "reason": "未发现可识别的 NapCat 实例（无需清理）"}
    ok, survivors = _kill_pids(leftovers)
    if ok:
        return {"stopped": True, "via": "fallback",
                "killed": len(leftovers), "pids": leftovers}
    return {"stopped": False, "via": "fallback",
            "killed": len(leftovers) - len(survivors),
            "survivors": survivors}


# ---- watchdog / bridge ------------------------------------------------------
def ensure_watchdog(resolved: dict) -> dict:
    state_dir = pathlib.Path(resolved["state_dir"])
    watchdog = _role_info(state_dir, "watchdog", WATCHDOG_ENTRY)
    w_ok, _ = owner_matches(watchdog) if watchdog else (False, "missing")
    if w_ok:
        return {"started": False, "pid": watchdog.get("pid")}
    cmd = [sys.executable, WATCHDOG_ENTRY, "--profile", resolved["profile"],
           "--config", str(resolved.get("config_path") or DEFAULT_CONFIG),
           "--state-dir", str(state_dir)]
    flags = 0x08000000 if sys.platform == "win32" else 0
    proc = subprocess.Popen(cmd, cwd=str(_ROOT), creationflags=flags,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, close_fds=True)
    return {"started": True, "pid": proc.pid}


def wait_ready(state_dir: pathlib.Path, *, timeout: float = 60.0) -> dict:
    deadline = time.time() + max(5.0, float(timeout))
    last: dict = {}
    while time.time() < deadline:
        last = _read_json(state_dir / "bridge_status.json")
        info = _role_info(state_dir, "bridge", BRIDGE_ENTRY)
        alive, _ = owner_matches(info) if info else (False, "missing")
        fresh = time.time() - float(last.get("event_loop_ts") or 0) < 30
        same = bool(info.get("instance_id") and info.get("instance_id") == last.get("instance_id"))
        if alive and fresh and same and last.get("state") == "connected" \
                and last.get("account_online") is True:
            return {"ready": True, "ws_state": "connected",
                    "account_online": True}
        time.sleep(2)
    return {"ready": False, "ws_state": last.get("state"),
            "account_online": last.get("account_online")}


def cmd_status(state_dir: pathlib.Path, resolved: dict) -> dict:
    bridge = _role_info(state_dir, "bridge", BRIDGE_ENTRY)
    watchdog = _role_info(state_dir, "watchdog", WATCHDOG_ENTRY)
    napcat = _napcat_info(state_dir)
    b_ok, b_reason = owner_matches(bridge) if bridge else (False, "missing")
    w_ok, w_reason = owner_matches(watchdog) if watchdog else (False, "missing")
    n_ok, n_reason = owner_matches(napcat) if napcat else (False, "missing")
    host, port = _onebot_target(resolved)
    status = _read_json(state_dir / "bridge_status.json")
    notices = NoticeStore(state_dir / "notices.jsonl",
                          bot_uin=str(resolved.get("uin") or "")).summary()
    return {
        "ok": True,
        "state_dir": str(state_dir),
        "desired": read_desired(state_dir),
        "napcat": {"pid": napcat.get("pid"), "alive": n_ok,
                   "reason": n_reason, "port_open": _port_open(host, port),
                   "adopted": bool(napcat.get("adopted"))},
        "bridge": {"pid": bridge.get("pid"), "alive": b_ok,
                   "reason": b_reason, "profile": bridge.get("profile"),
                   "instance_id": bridge.get("instance_id"),
                   "ws_state": status.get("state"),
                   "event_loop_ts": status.get("event_loop_ts"),
                   "account_online": status.get("account_online"),
                   "inbox": status.get("inbox")},
        "watchdog": {"pid": watchdog.get("pid"), "alive": w_ok,
                     "reason": w_reason,
                     "state": _read_json(state_dir / "watchdog_state.json")},
        "notices": notices,
    }


def cmd_stop(state_dir: pathlib.Path, *, with_napcat: bool = True,
             resolved: dict | None = None) -> dict:
    write_desired(state_dir, "stopped")
    # 给看门狗一个 tick 观察计划停机，然后清掉 outage 痕迹，
    # 避免下次 start 被当成故障恢复而误发「已接续」。
    time.sleep(2.5)
    state_path = state_dir / "watchdog_state.json"
    st = _read_json(state_path)
    if st:
        st.update({"phase": "stopped", "outage_id": "", "lost_created": False,
                   "outage_seen_bridge": False, "seen_bridge": False,
                   "attempt": 0, "consecutive_failures": 0})
        try:
            _write_json(state_path, st)
        except Exception:
            pass
    result = {"ok": True, "desired": "stopped", "bridge": None,
              "watchdog": None, "napcat": None}
    bridge = _role_info(state_dir, "bridge", BRIDGE_ENTRY)
    if bridge:
        ok, reason = terminate_owned(bridge, entry=BRIDGE_ENTRY)
        result["bridge"] = {"pid": bridge.get("pid"), "stopped": ok,
                            "reason": reason}
        if not ok and reason in ("pid_reused", "entry_mismatch"):
            result["ok"] = False
            result["conflict"] = f"bridge 归属不符({reason})，拒绝结束"
    watchdog = _role_info(state_dir, "watchdog", WATCHDOG_ENTRY)
    if watchdog:
        ok, reason = terminate_owned(watchdog, entry=WATCHDOG_ENTRY)
        result["watchdog"] = {"pid": watchdog.get("pid"), "stopped": ok,
                              "reason": reason}
        if not ok and reason in ("pid_reused", "entry_mismatch"):
            result["ok"] = False
            result["conflict"] = f"watchdog 归属不符({reason})，拒绝结束"
    if with_napcat:
        host = port = None
        if resolved:
            host, port = _onebot_target(resolved)
        result["napcat"] = stop_napcat(state_dir, host=host, port=port)
    return result


def cmd_start(resolved: dict, *, with_napcat: bool = True,
              wait_napcat: float = 90.0, wait_bridge: float = 60.0,
              reset_attempts: bool = True) -> dict:
    state_dir = pathlib.Path(resolved["state_dir"])
    write_desired(state_dir, "running")
    state_path = state_dir / "watchdog_state.json"
    state = _read_json(state_path)
    if reset_attempts and state:
        state.update(napcat_launch_count=0, napcat_last_launch_at=0.0,
                     account_attempts=0, account_blocked_until=0.0,
                     account_requires_login=False, account_scan_noticed=False)
        _write_json(state_path, state)
    result: dict = {"ok": True}
    if with_napcat:
        maximum = int((resolved.get("config", {}).get("supervision") or {}).get(
            "napcat_max_attempts", 3))
        state = _read_json(state_path)
        if not reset_attempts and int(state.get("napcat_launch_count", 0)) >= maximum:
            result["napcat"] = {"port_open": False, "started": False,
                                "error": "自动启动已达上限，请手动启动QQ桥"}
        else:
            result["napcat"] = ensure_napcat(resolved, wait_s=wait_napcat)
        if not result["napcat"].get("port_open"):
            result["ok"] = False
            if result["napcat"].get("started"):
                state = _read_json(state_path)
                state["napcat_launch_count"] = int(state.get("napcat_launch_count", 0)) + 1
                state["napcat_last_launch_at"] = time.time()
                _write_json(state_path, state)
    result["watchdog"] = ensure_watchdog(resolved)
    result["ready"] = wait_ready(state_dir, timeout=wait_bridge)
    if not result["ready"].get("ready"):
        result["ok"] = False
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="QQ Bridge Lite control (P2/P5)")
    ap.add_argument("command",
                    choices=("status", "stop", "start", "restart", "resume"))
    ap.add_argument("--profile", default=None)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--master", action="append", default=None)
    ap.add_argument("--state-dir", default=None)
    ap.add_argument("--no-napcat", action="store_true",
                    help="不改动 NapCat（只管理 watchdog/bridge）")
    ap.add_argument("--wait-napcat", type=float, default=90.0)
    ap.add_argument("--wait-bridge", type=float, default=60.0)
    args = ap.parse_args(argv)
    try:
        cfg = load_profile(pathlib.Path(args.config))
        resolved = resolve(args, cfg)
        resolved["config_path"] = args.config
    except ProfileError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    state_dir = pathlib.Path(resolved["state_dir"])
    if args.command == "status":
        out = cmd_status(state_dir, resolved)
    elif args.command == "stop":
        out = cmd_stop(state_dir, with_napcat=not args.no_napcat,
                       resolved=resolved)
    elif args.command == "resume":
        if not cfg.get("auto_resume", False) or read_desired(state_dir) == "stopped":
            out = {"ok": True, "desired": read_desired(state_dir),
                   "skipped": "auto_resume_disabled" if not cfg.get("auto_resume", False) else "manual_stop"}
        else:
            out = cmd_start(resolved, with_napcat=not args.no_napcat,
                            wait_napcat=args.wait_napcat,
                            wait_bridge=args.wait_bridge, reset_attempts=False)
    elif args.command == "start":
        out = cmd_start(resolved, with_napcat=not args.no_napcat,
                        wait_napcat=args.wait_napcat,
                        wait_bridge=args.wait_bridge)
    else:
        stopped = cmd_stop(state_dir, with_napcat=not args.no_napcat,
                           resolved=resolved)
        time.sleep(1.0)
        started = cmd_start(resolved, with_napcat=not args.no_napcat,
                            wait_napcat=args.wait_napcat,
                            wait_bridge=args.wait_bridge)
        out = {"ok": stopped.get("ok") and started.get("ok"),
               "stop": stopped, "start": started}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
