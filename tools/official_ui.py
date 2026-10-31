#!/usr/bin/env python3
"""官方 SoulX-Singer SVC UI 时段管理（start/stop，2026-10-12 实测定稿）。

用法:
  python tools/official_ui.py start [--port 7861] [--free-mb 6000]
      # 会一直前台挂到 UI 退出；建议以后台任务方式运行（本仓工作流用法）
  python tools/official_ui.py stop
      # 关 UI（pkill webui_svc.py）+ 恢复 llama/看护

说明: 官方 UI = ~/soulx/SoulX-Singer/webui_svc.py（与工作台同引擎；单轨交互换声）。
UI 会话期间聊天不可用（独占显存）。start 必须保持进程存活——UI 是它的子进程；
stop 通过 pkill 结束 UI，start 侧自动走恢复。
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WSL = ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc"]


def _bash(inner: str, timeout: float = 120):
    return subprocess.run(WSL + [inner], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _release_daemon_vram() -> None:
    try:
        import json

        req = urllib.request.Request(
            "http://127.0.0.1:8321/control",
            data=json.dumps({"action": "release_vram"}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
        print("[ui] daemon TTS/ASR 显存已请求释放", flush=True)
    except Exception as exc:  # noqa: BLE001
        print("[ui] release_vram 跳过:", type(exc).__name__, flush=True)


def _http_ok(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=4):
            return True
    except Exception:
        return False


def start(port: int, free_mb: int) -> int:
    from backend import gpu_window

    print("[ui] 1/3 腾显存（daemon 释放 + 停 llama/看护 + WSL 缓存回收）…",
          flush=True)
    _release_daemon_vram()
    win = gpu_window.open_window(require_free_mb=free_mb)
    print("[ui] window:", win, flush=True)
    if not win.get("ok"):
        print("[ui] 显存仍不足，放弃并恢复服务。", flush=True)
        gpu_window.close_window()
        return 1

    print(f"[ui] 2/3 启动官方 UI（前台子进程，端口 {port}）…", flush=True)
    proc = subprocess.Popen(
        WSL + [f"cd ~/soulx/SoulX-Singer && "
               f"export HF_ENDPOINT=https://hf-mirror.com "
               f"HF_HUB_DOWNLOAD_TIMEOUT=60 && "
               f"exec ~/soulx/venv/bin/python "
               f"webui_svc.py --port {port}"], cwd=str(ROOT))
    try:
        print("[ui] 3/3 健康检查（最多 180s，模型加载中）…", flush=True)
        t0 = time.time()
        ok = False
        while time.time() - t0 < 180:
            if _http_ok(port):
                ok = True
                break
            if proc.poll() is not None:
                print("[ui] ❌ UI 进程已退出 rc=", proc.returncode, flush=True)
                break
            time.sleep(4)
        if ok:
            print(f"[ui] ✅ 已就绪：http://127.0.0.1:{port}", flush=True)
            print("[ui] 保持中……（结束用 official_ui.py stop）", flush=True)
        else:
            print("[ui] ⚠️ 未见 HTTP 响应；可看上方输出排错。", flush=True)
        proc.wait()   # 保持生命周期：UI 活着 = 本任务活着
    except KeyboardInterrupt:
        pass
    finally:
        print("[ui] UI 退出，恢复服务…", flush=True)
        try:
            _bash("pkill -f webui_svc.py || true", timeout=30)
        except Exception:
            pass
        print("[ui] restore:", gpu_window.close_window(), flush=True)
    return 0


def stop() -> int:
    from backend import gpu_window

    print("[ui] 关闭 UI…", flush=True)
    try:
        _bash("pkill -f webui_svc.py || true", timeout=30)
    except Exception as exc:  # noqa: BLE001
        print("[ui] pkill:", type(exc).__name__, flush=True)
    print("[ui] 恢复 llama/看护:", gpu_window.close_window(), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("start", "stop"))
    ap.add_argument("--port", type=int, default=7861)
    ap.add_argument("--free-mb", type=int, default=6000)
    a = ap.parse_args()
    return start(a.port, a.free_mb) if a.cmd == "start" else stop()


if __name__ == "__main__":
    raise SystemExit(main())
