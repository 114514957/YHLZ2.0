"""桌面快捷方式打开器：确保端口在听，再用 Edge 应用窗口打开页面。

为什么不用 .url：服务没起时 .url 只会给一个「无法连接」白页；这里会先等/拉起栈，
失败时弹窗说清楚，而不是让老爹对着一片白。

用法（快捷方式里）：
    pythonw -B tools\\shortcuts\\open_page.py --url http://127.0.0.1:8321/cover \
        --port 8321 --boot yh
    pythonw -B tools\\shortcuts\\open_page.py --url http://127.0.0.1:8090/ \
        --port 8090 --boot train

选项：
    --boot yh      端口没起时双击 YH_boot.bat（静默起服务，不弹浏览器）
    --boot train   端口没起时起 llm_workbench/server.py
    --wait 180     等端口的最长秒数
    --dry-run      只打印判定，不拉起、不开窗
"""
from __future__ import annotations

import argparse
import ctypes
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
EDGE_CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "Microsoft" / "Edge" / "Application" / "msedge.exe",
]


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _detached(cmd: list[str], cwd: Path) -> subprocess.Popen:
    flags = 0
    if os.name == "nt":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
    return subprocess.Popen(cmd, cwd=str(cwd), close_fds=True,
                            creationflags=flags, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def boot(kind: str) -> None:
    if kind == "yh":
        _detached(["cmd", "/c", str(ROOT / "YH_boot.bat")], ROOT)
    elif kind == "train":
        py = ROOT / ".venv" / "Scripts" / "python.exe"
        _detached([str(py), "-B", str(ROOT / "llm_workbench" / "server.py")], ROOT)


def message(text: str, title: str = "元亨工作台") -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:  # noqa: BLE001
        print(text, file=sys.stderr)


def edge_exe() -> Path | None:
    for p in EDGE_CANDIDATES:
        if p.is_file():
            return p
    return None


def open_page(url: str) -> str:
    edge = edge_exe()
    if edge:
        _detached([str(edge), f"--app={url}"], ROOT)
        return f"edge-app {edge}"
    import webbrowser

    webbrowser.open(url)
    return "default-browser"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--boot", choices=["none", "yh", "train"], default="none")
    ap.add_argument("--wait", type=float, default=180.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    up = port_open(args.port)
    if args.dry_run:
        print(f"url={args.url} port={args.port} up={up} boot={args.boot} "
              f"edge={edge_exe()}")
        return 0
    if not up and args.boot != "none":
        boot(args.boot)
        deadline = time.time() + args.wait
        while time.time() < deadline and not port_open(args.port):
            time.sleep(2)
        up = port_open(args.port)
    if not up:
        message(f"端口 {args.port} 没有起来，页面打不开。\n\n先手动启动元亨，再点这个快捷方式。",
                "启动失败")
        return 1
    how = open_page(args.url)
    print(f"{how} -> {args.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
