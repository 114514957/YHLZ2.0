# -*- coding: utf-8 -*-
"""无状态保活：由计划任务**每分钟**调用一次，检查并补齐整条链。

为什么改成无状态（2026-11-16 血泪）：
  · 之前靠一个长命 supervisor 常驻，它被各种原因弄死（控制台关闭、job 收走、崩溃），
    一死就没人管 → workbench 全部 ERR_CONNECTION_REFUSED。
  · 改成"每分钟看一眼，缺什么补什么"：没有长命进程可死，任务计划程序负责重复触发。

做三件事：
  1. 8321 没在听 → 起 daemon（DETACHED，无窗口）
  2. daemon 在但 QQ 桥没连 → 起 QQ 桥
  3. 写心跳文件，供工作台「自持」卡显示
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
HB = os.path.join(ROOT, "cache", "sustain", "heartbeat.json")
LOG = os.path.join(ROOT, "cache", "logs", "keepalive.log")
DETACHED = 0x00000008 | 0x00000200


def log(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), msg))
    except Exception:  # noqa: BLE001
        pass


def port_open(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1.2)
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
                     stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=DETACHED)
    for _ in range(15):
        time.sleep(2)
        if port_open(8321):
            log("daemon 就绪 8321")
            return
    log("⚠ daemon 拉起失败")


def start_bridge() -> None:
    log("QQ 桥 → 拉起")
    try:
        subprocess.run([PY, "-X", "utf8", os.path.join("tools", "qq_bridge_control.py"),
                        "start", "--profile", "lite",
                        "--config", os.path.join("config", "qq_bridge_lite.json")],
                       cwd=ROOT, timeout=200, capture_output=True)
    except Exception as ex:  # noqa: BLE001
        log("桥启动异常 %s" % type(ex).__name__)


def main() -> int:
    demo = "--once" in sys.argv
    daemon_ok = port_open(8321)
    if not daemon_ok:
        start_daemon()
        daemon_ok = port_open(8321)

    q = qq_state() if daemon_ok else {}
    if daemon_ok and q and not q.get("bridge"):
        start_bridge()
        time.sleep(3)
        q = qq_state()

    payload = {
        "ts": time.time(),
        "level": "Medium",
        "daemon_ok": daemon_ok,
        "qq_online": bool(q.get("online")),
        "ws": bool(q.get("ws")),
        "bridge": bool(q.get("bridge")),
        "needs_scan": bool(q) and not q.get("ws"),
    }
    try:
        os.makedirs(os.path.dirname(HB), exist_ok=True)
        with open(HB, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass
    if demo:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
