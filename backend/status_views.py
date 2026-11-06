"""只读状态视图（F-27 拆层第一刀，2026-11-06）。

从 `console_server.py` 拆出的只读 status 组装：内在因列表、QQ 桥状态、
Ollama 探活。都不写数据、不依赖 HTTP handler，方便单测和复用。
"""
from __future__ import annotations

import json
import os
import pathlib
import time

from backend.yhlz_paths import BOT_UIN

ROOT = pathlib.Path(__file__).resolve().parent.parent

_OLLAMA_CACHE = {"ts": 0.0, "state": "down"}
_OLLAMA_TTL = 30.0


def drives_list() -> list:
    try:
        from backend import intrinsic_drives

        ds = [d for d in intrinsic_drives.load() if d.get("status") == "active"]
        ds.sort(key=lambda d: (int(d.get("priority", 0)),
                               float(d.get("strength", 0))), reverse=True)
        return [{"id": d.get("id"), "name": d.get("name"),
                 "category": d.get("category"),
                 "strength": round(float(d.get("strength", 0)), 2),
                 "priority": d.get("priority"),
                 "note": str(d.get("note", ""))[:80]} for d in ds[:12]]
    except Exception:
        return []


def qq_management_external() -> bool:
    """True when QQ is owned by the Lite chain (fail-closed on bad config)."""
    try:
        cfg = json.loads((ROOT / "config" / "qq_management.json")
                         .read_text(encoding="utf-8-sig"))
        return str(cfg.get("mode") or "").strip().lower() == "external"
    except Exception:
        return True


def qq_status() -> dict:
    """元亨 QQ / NapCat / bridge status for the workbench.

    优先读 QQ 桥 Lite 的权威状态（cache/qq_bridge/lite/：bridge_status.json +
    bridge.pid 归属校验）；没有 Lite 记录时退回旧 napcat_status.json（Full）。
    """
    out = {"uin": BOT_UIN, "name": "元亨", "online": False,
           "ws": False, "bridge": False, "since": 0.0, "source": ""}
    state_dir = ROOT / "cache" / "qq_bridge" / "lite"
    status_file = state_dir / "bridge_status.json"
    if status_file.exists():
        out["source"] = "lite"
        try:
            st = json.loads(status_file.read_text(encoding="utf-8"))
            alive = False
            info: dict = {}
            try:
                from backend.qq_bridge_lock import owner_matches, read_info

                info = read_info(state_dir / "bridge.pid")
                if info:
                    alive = owner_matches(info)[0]
            except Exception:  # noqa: BLE001
                pass
            out["bridge"] = bool(alive)
            out["ws"] = bool(alive) and str(st.get("state")) == "connected"
            out["online"] = bool(alive) and bool(st.get("account_online"))
            out["since"] = float(st.get("started_at") or 0.0)
            out["bridge_pid"] = info.get("pid")
        except Exception:  # noqa: BLE001
            pass
        return out
    # 0831：external 下 QQ 归 Lite 独占，旧 napcat_status.json 是停更的僵尸
    if qq_management_external():
        out["source"] = "lite-missing"
        return out
    try:
        p = ROOT / "cache" / "tmp" / "napcat_status.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in ("online", "ws", "since"):
            if k in d:
                out[k] = d[k]
    except Exception:
        pass
    try:
        import psutil

        out["bridge"] = any(
            "qq_bot.py" in " ".join(pi.info.get("cmdline") or [])
            for pi in psutil.process_iter(["cmdline"]))
    except Exception:
        pass
    return out


def ollama_state(*, ttl: float = _OLLAMA_TTL, timeout: float = 1.0) -> str:
    """Ollama state: ``ok`` / ``down`` / ``off`` (ledger 1096, 2026-11-05).

    Ollama is optional — launcher only starts it when ``YHLZ_START_OLLAMA`` is
    set. Probing a refused loopback port costs ~2 s on this machine, and the
    workbench polls /state every 3 s, so when the option is off we report
    ``off`` without touching the socket. When it is on, probe at most once
    per ``ttl``.
    """
    enabled = str(os.getenv("YHLZ_START_OLLAMA", "")).strip().lower() in (
        "1", "true", "yes", "on")
    if not enabled:
        return "off"
    now = time.time()
    if _OLLAMA_CACHE["state"] and now - float(_OLLAMA_CACHE["ts"]) < ttl:
        return str(_OLLAMA_CACHE["state"])
    state = "down"
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",
                                    timeout=timeout) as resp:
            body = json.loads(resp.read())
        state = "ok" if "models" in body else "down"
    except Exception:
        state = "down"
    _OLLAMA_CACHE["ts"] = now
    _OLLAMA_CACHE["state"] = state
    return state
