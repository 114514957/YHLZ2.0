# -*- coding: utf-8 -*-
"""元亨自持守护（L1）：盯 daemon 与 QQ 桥，挂了重拉，带退避。

为什么需要它（2026-11-16）：
  · AI（我）启动的进程会随命令结束被系统收走，不能常驻；
  · 但 **Windows 任务计划程序** 在我的进程树之外 → 由它启动这个脚本即可常驻；
  · 脚本自己再负责：daemon(8321) 在不在、QQ 桥在不在，不在就拉起来。

设计要点：
  · **绝不以管理员运行**（管理员进程注入不进 QQ；见台账 1266/1268）；
  · 也**绝不在 Low 完整性下运行**（会把整条链降级）；
  · 重启有退避：连续失败 30s→60s→2min→5min，成功后复位；
  · 每 30 秒一轮，日志 append 到 cache/logs/supervisor.log。

用法：
    python tools\\yh_supervisor.py            # 前台跑（调试）
    python tools\\yh_supervisor.py --once     # 只跑一轮
    （常驻请用计划任务，见 tools\\install_supervisor_task.cmd）
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
LOG = os.path.join(ROOT, "cache", "logs", "supervisor.log")
TICK = 30
BACKOFF = [30, 60, 120, 300]


def log(msg: str) -> None:
    line = "%s %s" % (time.strftime("%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def level() -> str:
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import integrity  # type: ignore
        return integrity.level()
    except Exception:  # noqa: BLE001
        return "?"


def port_open(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        s.close()


def qq_state() -> dict:
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open("http://127.0.0.1:8321/state", timeout=6) as f:
            return (json.loads(f.read().decode()) or {}).get("qq") or {}
    except Exception:  # noqa: BLE001
        return {}


def start_daemon() -> None:
    log("daemon 不在 → 拉起")
    subprocess.Popen([PY, "-B", "-m", "backend.target_daemon", "--port", "8321"],
                     cwd=ROOT, close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    for _ in range(12):
        time.sleep(2)
        if port_open(8321):
            log("daemon 已就绪 8321")
            return
    log("⚠ daemon 拉起后仍未监听")


def start_bridge() -> None:
    log("QQ 桥不在 → 拉起")
    try:
        subprocess.run([PY, "-X", "utf8", os.path.join("tools", "qq_bridge_control.py"),
                        "start", "--profile", "lite",
                        "--config", os.path.join("config", "qq_bridge_lite.json")],
                       cwd=ROOT, timeout=240, capture_output=True)
    except Exception as ex:  # noqa: BLE001
        log("桥启动异常 %s" % type(ex).__name__)


def tick(fails: dict) -> None:
    lv = level()
    # 心跳**先写**：即使后面因完整性/异常提前 return，工作台也知道 supervisor 活着
    write_heartbeat({"level": lv, "daemon_ok": port_open(8321)})
    if lv not in ("Medium", "MediumPlus"):
        log("⛔ 当前完整性=%s，拒绝操作（管理员或低权限都会搞坏链）" % lv)
        return

    if not port_open(8321):
        start_daemon()
        fails["daemon"] = fails.get("daemon", 0) + (0 if port_open(8321) else 1)
    else:
        fails["daemon"] = 0

    q = qq_state()
    if q and not (q.get("online") and q.get("ws")):
        # 桥进程没了才拉；登录态缺失不反复拉起（避免刷屏/抢登录）
        if not q.get("bridge"):
            start_bridge()
            fails["bridge"] = fails.get("bridge", 0) + 1
        else:
            log("桥在但未登录（online=%s ws=%s）→ 需要扫码"
                % (q.get("online"), q.get("ws")))

    # 心跳：工作台「自持」卡据此显示是否在跑（2026-11-16 老爹要求做进工作台）
    write_heartbeat({
        "daemon_ok": port_open(8321),
        "qq_online": bool(q.get("online")),
        "ws": bool(q.get("ws")),
        "bridge": bool(q.get("bridge")),
        "needs_scan": bool(q) and not q.get("ws"),
    })


def write_heartbeat(extra: dict) -> None:
    """写心跳文件：工作台读它就知道 supervisor 活没活、链条哪一环断了。"""
    try:
        d = os.path.join(ROOT, "cache", "sustain")
        os.makedirs(d, exist_ok=True)
        payload = {"ts": time.time(), "level": level()}
        payload.update(extra)
        with open(os.path.join(d, "heartbeat.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--tick", type=int, default=TICK)
    a = ap.parse_args()

    log("supervisor 启动：完整性=%s｜PY=%s" % (level(), PY))
    fails: dict[str, int] = {}
    while True:
        try:
            tick(fails)
        except Exception as ex:  # noqa: BLE001
            log("tick 异常 %s: %s" % (type(ex).__name__, str(ex)[:100]))
        if a.once:
            return 0
        time.sleep(max(10, a.tick))


if __name__ == "__main__":
    raise SystemExit(main())
