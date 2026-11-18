# -*- coding: utf-8 -*-
"""自持开关：一个信号决定"这些自动任务开不开"，供工作台滑块调用。

老爹 2026-11-17：**"我来决定开关"** —— 自动任务不该背着他跑。

管三样东西（全部可逆）：
  1. 计划任务 `YH-Sup-Keepalive`（每分钟保活 daemon/桥）
  2. 计划任务 `YH-Daily-Learn`（每天 04:30 学习）
  3. 「启动」文件夹里的 `YH-supervisor.cmd`（登录自启）

状态落盘 `cache/sustain/autostart.json`，工作台据此显示滑块。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "cache", "sustain", "autostart.json")
TASKS = ("YH-Sup-Keepalive", "YH-Daily-Learn", "YH-Sentinel")
STARTUP = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                       "Start Menu", "Programs", "Startup", "YH-supervisor.cmd")
SUPERVISOR_CMD = os.path.join(ROOT, "tools", "run_supervisor.cmd")

__all__ = ["status", "set_enabled"]


def _run(args: list[str]) -> tuple[int, str]:
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="mbcs", errors="replace")
    out = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    return r.returncode, (out[-1][:90] if out else "")


def _task_state(name: str) -> str:
    """只看「计划任务状态 / Scheduled Task State」这一行。

    坑（2026-11-17）：`schtasks /query /v` 的输出里**总是**含
    "Delete Task If Not Rescheduled: Disabled"，用它判断会把所有任务都当禁用。
    """
    rc, _ = _run(["schtasks", "/query", "/tn", name, "/fo", "list"])
    if rc != 0:
        return "missing"
    r = subprocess.run(["schtasks", "/query", "/tn", name, "/fo", "list", "/v"],
                       capture_output=True, text=True, encoding="mbcs",
                       errors="replace")
    for ln in (r.stdout or "").splitlines():
        low = ln.lower()
        if "scheduled task state" in low or "计划任务状态" in ln:
            if "disabled" in low or "已禁用" in ln:
                return "disabled"
            if "enabled" in low or "已启用" in ln:
                return "enabled"
    return "unknown"


def _save(d: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with io.open(STATE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def _load() -> dict:
    try:
        with io.open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def status() -> dict:
    tasks = {t: _task_state(t) for t in TASKS}
    startup = os.path.exists(STARTUP)
    enabled = any(v == "enabled" for v in tasks.values()) or startup
    return {"ok": True, "enabled": enabled, "tasks": tasks,
            "startup_file": startup,
            "saved": _load().get("enabled"),
            "checked_at": time.strftime("%H:%M:%S")}


def set_enabled(enabled: bool) -> dict:
    """开/关自持。开=启用任务+放启动项；关=禁用任务+删启动项。"""
    log = []
    for t in TASKS:
        rc, msg = _run(["schtasks", "/change", "/tn", t,
                        "/enable" if enabled else "/disable"])
        log.append("%s %s: %s" % (t, "enable" if enabled else "disable",
                                  "ok" if rc == 0 else msg))
    try:
        if enabled:
            if os.path.exists(SUPERVISOR_CMD):
                os.makedirs(os.path.dirname(STARTUP), exist_ok=True)
                shutil.copyfile(SUPERVISOR_CMD, STARTUP)
                log.append("启动项已放")
        else:
            if os.path.exists(STARTUP):
                os.remove(STARTUP)
                log.append("启动项已删")
    except Exception as e:  # noqa: BLE001
        log.append("启动项失败: %s" % type(e).__name__)

    _save({"enabled": bool(enabled), "at": time.time()})
    st = status()
    st["log"] = log
    return st
