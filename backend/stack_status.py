# -*- coding: utf-8 -*-
"""链路状态（工作站第一张卡的数据层，台账 1249）。

一屏回答今天反复要问的四件事：
  ① daemon 在不在、有没有**双实例**（今天踩过：系统 Python 那个杀不掉）
  ② NapCat 的 WS(3001) 通不通（不通 = QQ 私聊根本收不到消息）
  ③ 云端端点/模型/密钥是否就绪
  ④ llama(8081) 是否已按下线定论关闭

纯只读；任何一项探测失败都不抛异常，只把 ok 标 False 并把原因写进 detail。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:          # 直接 `python backend/stack_status.py` 时也能 import backend.*
    sys.path.insert(0, str(ROOT))
__all__ = ["snapshot", "warnings"]


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:  # noqa: BLE001
        return False


def _daemons() -> list[dict[str, Any]]:
    """列出 target_daemon 进程，并标出**是不是别人的子进程**。

    2026-11-15（台账 1251）：之前把"父进程也是 daemon"的那个也算成"双实例"，
    结果自愈脚本把 daemon 的子进程杀了、服务直接停摆。
    **只有"根 daemon"（父不是 daemon）才算实例。**
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match 'target_daemon' } | "
             "ForEach-Object { $_.ProcessId.ToString() + '|' + "
             "$_.ParentProcessId.ToString() + '|' + $_.CommandLine }"],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace")
        raw = []
        for ln in (out.stdout or "").splitlines():
            parts = ln.split("|", 2)
            if len(parts) < 3:
                continue
            pid, ppid, cmd = parts
            raw.append({"pid": int(pid.strip()), "ppid": int(ppid.strip()),
                        "venv": "\\.venv\\" in cmd or "/.venv/" in cmd,
                        "cmd": cmd.strip()[:160]})
        pids = {r["pid"] for r in raw}
        for r in raw:
            r["root"] = r["ppid"] not in pids
        return raw
    except Exception:  # noqa: BLE001
        return []


def _tail_jsonl(path: Path, n: int) -> list[dict]:
    try:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        out = []
        for ln in lines[-n:]:
            try:
                out.append(json.loads(ln))
            except Exception:  # noqa: BLE001
                continue
        return out
    except Exception:  # noqa: BLE001
        return []


def snapshot() -> dict[str, Any]:
    daemons = _daemons()
    roots = [d for d in daemons if d.get("root")]
    daemon_ok = _port_open(8321)
    napcat_ok = _port_open(3001)
    llama_ok = _port_open(8081)

    cloud: dict[str, Any] = {"ok": False, "model": "", "provider": ""}
    try:
        from backend.llm_endpoint import endpoint
        ep = endpoint()
        cloud = {"ok": bool(ep["api_key"]), "model": ep["model"],
                 "provider": ep["provider"], "base_url": ep["base_url"]}
    except Exception as ex:  # noqa: BLE001
        cloud = {"ok": False, "error": "%s: %s" % (type(ex).__name__, ex)}

    usage: dict[str, Any] = {}
    try:
        from backend.llm_usage import summary
        usage = summary()
    except Exception:  # noqa: BLE001
        pass

    return {
        "daemon": {"ok": daemon_ok, "port": 8321, "instances": len(roots),
                   "procs": roots, "children": [d for d in daemons
                                                if not d.get("root")]},
        "napcat": {"ok": napcat_ok, "port": 3001},
        "cloud": cloud,
        "llama": {"ok": llama_ok, "port": 8081,
                  "expected": "down（台账 1231：本地已下线）"},
        "usage": usage,
        "recent_turns": _tail_jsonl(ROOT / "cache" / "llm_usage.jsonl", 5),
        "recent_recall": _tail_jsonl(ROOT / "cache" / "recall_trace.jsonl", 5),
    }


def warnings(snap: dict[str, Any] | None = None) -> list[str]:
    """把"今天的坑"变成会自己喊的告警。"""
    s = snap or snapshot()
    out = []
    if s["daemon"]["instances"] > 1:
        pods = ", ".join(p["pid"] for p in s["daemon"]["procs"])
        out.append("⚠ daemon 有 %d 个实例（%s）——端口只有一个，另一个是旧代码，改完可能不生效"
                   % (s["daemon"]["instances"], pods))
    if not s["daemon"]["ok"]:
        out.append("❌ daemon 没在听 8321")
    if not s["napcat"]["ok"]:
        out.append("❌ NapCat WS(3001) 不通 —— QQ 私聊/群消息收不到（今天就栽在这）")
    if not s["cloud"].get("ok"):
        out.append("❌ 云端不可用：%s" % s["cloud"].get("error", "缺密钥"))
    if s["llama"]["ok"]:
        out.append("⚠ llama-server(8081) 在跑——按定论应当已下线")
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    snap = snapshot()
    print(json.dumps(snap, ensure_ascii=False, indent=1)[:1200])
    print("\n=== 告警 ===")
    for w in warnings(snap) or ["（无）"]:
        print("  " + w)
