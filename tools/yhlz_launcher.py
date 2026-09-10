"""YHLZ desktop launcher (ledger 0223): bring up the stack, show a boot page
with the loading animation, then jump to the workbench.

Flow:
  ensure ollama(11434) / gemma llama-server(8081) / daemon+UI(8321) running
  -> serve a tiny boot page (8577) with loading.webp + per-service status
  -> when all /health are ok, boot page redirects to http://127.0.0.1:8321

Usage: python tools/yhlz_launcher.py [--no-browser]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

SRC_DIR = Path(r"C:\Users\ACE_WAN——PROJECT\Desktop\图片素材")
BOOT_PORT = 8577
OLLAMA = r"C:\Users\ACE_WAN——PROJECT\AppData\Local\Programs\Ollama\ollama.exe"
LLAMA = (r"C:\Users\ACE_WAN——PROJECT\AppData\Local\Microsoft\WinGet\Packages"
         r"\ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe\llama-server.exe")
GEMMA = _ROOT / "models" / "gemma4" / "gemma4-e4b-aggr-q4km.gguf"
MMPROJ = _ROOT / "models" / "gemma4" / "mmproj-gemma4-e4b.gguf"
PY = _ROOT / ".venv" / "Scripts" / "python.exe"

URLS = {
    "ollama": ("http://127.0.0.1:11434/api/tags", "GET"),
    "gemma": ("http://127.0.0.1:8081/health", "GET"),
    "daemon": ("http://127.0.0.1:8321/health", "GET"),
}

# QQ bridge (optional): kept alive only when NapCat's OneBot WS is up.
QQBOT_UIN = "3655185302"
QQBOT_MASTER = "2258374446"
QQBOT_PORT = 3001
QQBOT_LOCK = _ROOT / "cache" / "tmp" / "qqbot.lock"


def _up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def status() -> dict:
    return {name: _up(u) for name, (u, _m) in URLS.items()}


def _port_open(host: str, port: int) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except Exception:
        return False


def _qqbot_alive() -> bool:
    """True if a qq_bot process is running (robust: scan cmdlines, since the
    venv pythonw launcher spawns a child interpreter)."""
    try:
        import psutil
    except Exception:
        return QQBOT_LOCK.exists()
    for p in psutil.process_iter(["cmdline"]):
        try:
            cl = p.info.get("cmdline") or []
        except Exception:
            continue
        if any("qq_bot.py" in str(x) for x in cl):
            return True
    return False


def qqbot_status() -> bool:
    """QQ bridge healthy = NapCat WS up (3001) and bridge alive; when NapCat
    is not logged in this is simply 'not applicable' (False), never an error."""
    return _port_open("127.0.0.1", QQBOT_PORT) and _qqbot_alive()


def _spawn_ollama():
    subprocess.Popen([OLLAMA, "serve"], close_fds=True)


def _spawn_llama():
    subprocess.Popen(
        [LLAMA, "-m", str(GEMMA), "--mmproj", str(MMPROJ), "--jinja",
         "-ngl", "99", "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0",
         "-c", "8192", "--port", "8081", "--host", "127.0.0.1",
         "--temp", "1.0", "--top-p", "0.95", "--top-k", "64"],
        close_fds=True)


def _spawn_daemon():
    subprocess.Popen([str(PY), "-B", "-m", "backend.target_daemon",
                      "--port", "8321"], cwd=str(_ROOT), close_fds=True)


def _spawn_qqbot():
    pyw = PY.with_name("pythonw.exe")
    subprocess.Popen([str(pyw), "-B", str(_ROOT / "tools" / "qq_bot.py"),
                      "--uin", QQBOT_UIN, "--master", QQBOT_MASTER],
                     cwd=str(_ROOT), close_fds=True)


def ensure_stack() -> dict:
    st = status()
    if not st["ollama"]:
        _spawn_ollama()
    if not st["gemma"]:
        _spawn_llama()
    if not st["daemon"]:
        _spawn_daemon()
    # keep the QQ bridge alive, but only if NapCat's OneBot WS is up
    if _port_open("127.0.0.1", QQBOT_PORT) and not _qqbot_alive():
        _spawn_qqbot()
    time.sleep(1)
    return status()


def _boot_html() -> bytes:
    return (f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>YHLZ · 元 · 亨 · 利 · 贞 · 启动中</title>
<link rel="icon" href="/favicon.png">
<style>
html,body{{margin:0;height:100%;font:14px/1.7 "Segoe UI","Microsoft YaHei",sans-serif;
  color:#fff;overflow:hidden;
  background:#131318 url(/bg.png) center/cover no-repeat;}}
.wrap{{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;
  background:rgba(10,8,20,.25);backdrop-filter:blur(2px);}}
video{{width:min(64vh,420px);height:auto;border-radius:14px;
  box-shadow:0 18px 44px rgba(0,0,0,.45);}}
h1{{margin:0;font-size:22px;letter-spacing:2px;text-shadow:0 2px 8px #000}}
.rows{{display:flex;gap:22px;font-weight:600}}
.s{{padding:4px 14px;border-radius:14px;background:rgba(255,255,255,.14);}}
.s b{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;background:#888;}}
.s.ok b{{background:#4fd1a5;box-shadow:0 0 8px #4fd1a5}}
#st{{font-size:12px;opacity:.75;min-height:18px}}
</style></head><body>
<div class="wrap">
 <video src="/boot.mp4" autoplay muted loop playsinline></video>
 <h1>YHLZ · 元 · 亨 · 利 · 贞</h1>
 <div class="rows" id="rows"></div>
 <div id="st">正在唤醒服务…</div>
</div>
<script>
const names={{gemma:"Gemma",daemon:"daemon",ollama:"ollama"}};
const rows=document.getElementById('rows');
for(const k in names){{const s=document.createElement('div');s.className='s';s.id='s_'+k;
  s.innerHTML='<b></b>'+names[k];rows.appendChild(s);}}
setInterval(async()=>{{
 try{{const r=await fetch('/api/status');const d=await r.json();let all=true;
  for(const k in names){{const e=document.getElementById('s_'+k);if(d[k]){{e.classList.add('ok')}}
    else{{all=false;e.classList.remove('ok')}}}}
  if(all){{document.getElementById('st').textContent='全部就绪，即将进入工作台…';
    setTimeout(()=>location.href='http://127.0.0.1:8321/',2600);}}}}
 catch(e){{}}
}},700);
</script></body></html>""").encode("utf-8")


class BootHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p == "/":
            self._send(200, _boot_html(), "text/html; charset=utf-8")
        elif p == "/bg.png":
            blob = (SRC_DIR / "背景.png").read_bytes()
            self._send(200, blob, "image/png")
        elif p == "/boot.mp4":
            blob = (SRC_DIR / "加载动画.mp4").read_bytes()
            self._send(200, blob, "video/mp4")
        elif p == "/favicon.png":
            blob = (_ROOT / "assets" / "webui" / "favicon.png").read_bytes()
            self._send(200, blob, "image/png")
        elif p == "/api/status":
            self._send(200, json.dumps(status()).encode(),
                       "application/json")
        else:
            self._send(404, b"n/a", "text/plain")


def _self_test() -> None:
    """Startup test: ensure the whole stack and verify the workbench UI is
    served on 8321 (no boot page anymore)."""
    import urllib.request as _u

    ensure_stack()
    for _ in range(60):
        st = status()
        if all(st.values()):
            break
        time.sleep(1)
    ok = all(status().values())
    try:
        html = _u.urlopen("http://127.0.0.1:8321/", timeout=5).read()
        h = html.decode("utf-8", "replace")
        ok &= "YHLZ" in h
    except Exception as exc:  # noqa: BLE001
        print("SELFTEST FAIL workbench", type(exc).__name__, str(exc)[:100])
        ok = False
    print("SELFTEST OK services=", status() if ok else {}, flush=True)
    if not ok:
        raise SystemExit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-browser", action="store_true",
                    help="do not open browser/workbench")
    ap.add_argument("--self-test", action="store_true",
                    help="ensure services then exit (startup test)")
    a = ap.parse_args()
    if a.self_test:
        _self_test()
        return 0
    ensure_stack()
    # wait until the whole stack is ready, then open the workbench directly
    print("等待服务就绪…", flush=True)
    for _ in range(150):
        st = status()
        print("  ", st, flush=True)
        if all(st.values()):
            break
        time.sleep(1)
    if not all(status().values()):
        print("部分服务未就绪:", status(), flush=True)
        if not a.no_browser:
            return 1
    if a.no_browser:
        print("services:", status(), flush=True)
        return 0
    webbrowser.open("http://127.0.0.1:8321/")
    print("已打开工作台 http://127.0.0.1:8321", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
