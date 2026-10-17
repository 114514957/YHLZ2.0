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

from backend.yhlz_paths import (  # noqa: E402
    BOT_UIN, DESKTOP_DIR, GEMMA_GGUF, LLAMA_EXE, MASTER_UIN, MMPROJ_GGUF,
    NAPCAT_LAUNCHER, OLLAMA_EXE, YH_BASE_GGUF, YH_LLAMA_EXE, YH_LORA_GGUF,
    YH_MMPROJ_GGUF,
)

SRC_DIR = DESKTOP_DIR
BOOT_PORT = 8577
OLLAMA = OLLAMA_EXE
LLAMA = LLAMA_EXE
GEMMA = GEMMA_GGUF
MMPROJ = MMPROJ_GGUF
PY = _ROOT / ".venv" / "Scripts" / "python.exe"

URLS = {
    "ollama": ("http://127.0.0.1:11434/api/tags", "GET"),
    "gemma": ("http://127.0.0.1:8081/health", "GET"),
    "daemon": ("http://127.0.0.1:8321/health", "GET"),
}

# QQ bridge (optional): kept alive only when NapCat's OneBot WS is up.
QQBOT_UIN = BOT_UIN
QQBOT_MASTER = MASTER_UIN
QQBOT_PORT = 3001
QQBOT_LOCK = _ROOT / "cache" / "tmp" / "qqbot.lock"
QQ_MANAGEMENT_FILE = _ROOT / "config" / "qq_management.json"


def qq_management() -> str:
    """full (default) | external.

    external: another bridge build owns the QQ account (Lite chain); the Full
    launcher/watchdog must not start/stop the QQ bridge, NapCat or
    napcat_watch. Env YHLZ_QQ_MANAGEMENT wins, then config file.
    """
    env = os.getenv("YHLZ_QQ_MANAGEMENT", "").strip().lower()
    if env in ("full", "external"):
        return env
    try:
        cfg = json.loads(QQ_MANAGEMENT_FILE.read_text(encoding="utf-8-sig"))
        mode = str(cfg.get("mode") or "").strip().lower()
        if mode in ("full", "external"):
            return mode
    except Exception:
        pass
    return "full"


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
    """0699: hidden + logged (was: visible console window, no log)."""
    log = _ROOT / "cache" / "logs" / "ollama.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([OLLAMA, "serve"], cwd=str(_ROOT),
                     stdout=open(log, "ab"), stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     close_fds=True)


def _spawn_llama():
    """v6 生产链（记录 0398/0426）：QAT-Q4 + mmproj(CPU) + v6 LoRA。

    旧 gemma-aggr 配置只在 v6 资产缺失时兜底——此前 watchdog 会用它抢占
    8081，导致项目调用到的不是元亨。
    """
    if YH_LLAMA_EXE.exists() and YH_BASE_GGUF.exists():
        argv = [str(YH_LLAMA_EXE), "-m", str(YH_BASE_GGUF),
                "--mmproj", str(YH_MMPROJ_GGUF), "--no-mmproj-offload"]
        if YH_LORA_GGUF.exists():
            argv += ["--lora", str(YH_LORA_GGUF)]
        argv += ["-ngl", "99", "-c", "8192", "--parallel", "1",
                 "-rea", "off", "--alias", "gemma-4-e4b",
                 "--host", "127.0.0.1", "--port", "8081", "--jinja"]
    else:
        argv = [LLAMA, "-m", str(GEMMA), "--mmproj", str(MMPROJ), "--jinja",
                "-ngl", "99", "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0",
                "-c", "8192", "--port", "8081", "--host", "127.0.0.1",
                "--temp", "1.0", "--top-p", "0.95", "--top-k", "64"]
    log = _ROOT / "cache" / "logs" / "llama-server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(argv, cwd=str(_ROOT), stdout=open(log, "ab"),
                     stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     close_fds=True)


def _spawn_daemon():
    # F1 (ledger 0436): log stdout/stderr so crash/flap causes are visible
    # (previously the daemon was spawned with no redirect at all).
    # ledger 0815: 子进程不吃父进程的畸形 NO_PROXY（`[::1]` → httpx 全请求
    # InvalidURL，元亨 QQ 全哑）。
    log = _ROOT / "cache" / "logs" / "daemon.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    try:
        from backend.env_loader import sanitize_proxy_env

        for change in sanitize_proxy_env(env):
            print(f"[launcher] env: {change}", flush=True)
    except Exception:
        pass
    subprocess.Popen([str(PY), "-B", "-m", "backend.target_daemon",
                      "--port", "8321"], cwd=str(_ROOT), env=env,
                     stdout=open(log, "ab"), stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     close_fds=True)


def _spawn_qqbot():
    pyw = PY.with_name("pythonw.exe")
    subprocess.Popen([str(pyw), "-B", str(_ROOT / "tools" / "qq_bot.py"),
                      "--uin", QQBOT_UIN, "--master", QQBOT_MASTER],
                     cwd=str(_ROOT), close_fds=True)


NAPCAT_BAT = NAPCAT_LAUNCHER


def _proc_alive(script: str) -> bool:
    """True if the matching process is running (hardened 2026-10-12).

    - exe-like marker (`llama-server`, `ollama`): image-name prefix match;
    - script/module marker (`target_daemon`, `napcat_watch.py`): python
      interpreter whose argv element ends with the marker.

    Shells that merely *mention* the name no longer count — a PowerShell
    running `Get-Process llama-server` once fooled the llama check, so the
    watchdog skipped the respawn (llama stayed down after a GPU window).
    """
    try:
        import psutil
    except Exception:
        return False
    marker = script.lower()
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            nm = str(p.info.get("name") or "").lower()
            cl = [str(x).replace("\\", "/").lower()
                  for x in (p.info.get("cmdline") or [])]
        except Exception:
            continue
        if nm.startswith(marker):
            return True
        if nm.startswith("python") and any(
                x.endswith(marker) or x.endswith(marker + ".py")
                for x in cl):
            return True
    return False


def napcat_status() -> dict:
    p = _ROOT / "cache" / "tmp" / "napcat_status.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _spawn_napcat_watch():
    subprocess.Popen([str(PY), "-B", str(_ROOT / "tools" / "napcat_watch.py")],
                     cwd=str(_ROOT), close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _spawn_napcat():
    from backend.napcat_launcher import launch_napcat

    launch_napcat(QQBOT_UIN)


SPAWN_GUARD = _ROOT / "cache" / "tmp" / "spawn_guard.json"


def _spawn_allowed(key: str, cooldown: float) -> bool:
    """F2 (ledger 0436): respawn throttle — at most one attempt per cooldown.

    The 09-19 flap: /health timed out while the daemon was actually alive, so
    every watchdog tick spawned another process (which died on the busy port)
    or killed the good one via dupes. Process/port checks live in
    `ensure_stack`; this guard caps even legitimate-looking retries.
    """
    try:
        SPAWN_GUARD.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if SPAWN_GUARD.exists():
            try:
                data = json.loads(SPAWN_GUARD.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        now = time.time()
        if now - float(data.get(key) or 0) < float(cooldown):
            return False
        data[key] = now
        SPAWN_GUARD.write_text(json.dumps(data), encoding="utf-8")
        return True
    except Exception:
        return True


def _daemon_health() -> dict | None:
    try:
        import json as _j
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:8321/health", timeout=3) as r:
            return _j.loads(r.read())
    except Exception:
        return None


def _maybe_recycle_daemon() -> None:
    """0535: a long-running daemon accumulates state (a turn went 18s→4s after a
    restart).  Opt-in via YHLZ_DAEMON_MAX_UPTIME_S (default 0 = off): when the
    daemon has been up past the limit AND is idle, kill it so the next tick
    respawns a fresh one.  Never interrupts a busy turn."""
    import os

    try:
        max_s = float(os.getenv("YHLZ_DAEMON_MAX_UPTIME_S", "0") or 0)
    except Exception:
        max_s = 0.0
    if max_s <= 0:
        return
    h = _daemon_health()
    if not isinstance(h, dict):
        return
    try:
        if float(h.get("uptime_s", 0) or 0) < max_s:
            return
        if int(h.get("active_turns", 0) or 0) > 0:
            return
    except Exception:
        return
    if not _spawn_allowed("daemon_recycle", 1800):
        return
    try:
        import psutil

        killed = 0
        for p in psutil.process_iter(["cmdline"]):
            cl = p.info.get("cmdline") or []
            if any("target_daemon" in str(x) for x in cl):
                p.kill()
                killed += 1
        if killed:
            print("[launcher] daemon recycled (uptime guard)", flush=True)
    except Exception:
        pass


def ensure_stack() -> dict:
    st = status()
    # F2: never respawn something that is still there (process alive or port
    # bound) — a slow /health is not a dead service.
    if (not st["ollama"] and not _proc_alive("ollama")
            and not _port_open("127.0.0.1", 11434)
            and _spawn_allowed("ollama", 180)):
        _spawn_ollama()
    if (not st["gemma"] and not _port_open("127.0.0.1", 8081)
            and not _proc_alive("llama-server")
            and _spawn_allowed("llama", 180)):
        _spawn_llama()
    if (not st["daemon"] and not _port_open("127.0.0.1", 8321)
            and not _proc_alive("target_daemon")
            and _spawn_allowed("daemon", 120)):
        _spawn_daemon()
    # 0535: opt-in idle uptime recycle (prevents long-running slowdown).
    _maybe_recycle_daemon()
    # keep the QQ bridge alive, but only if NapCat's OneBot WS is up.
    # qq_management=external (2026-10-07): the Lite chain owns QQ; skip here.
    if qq_management() != "external":
        if _port_open("127.0.0.1", QQBOT_PORT) and not _qqbot_alive():
            _spawn_qqbot()
        # keep the NapCat online-watcher alive
        if not _proc_alive("napcat_watch.py"):
            _spawn_napcat_watch()
    time.sleep(1)
    return status()


def _boot_html() -> bytes:
    return (f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>YHLZ · 元 · 亨 · 利 · 贞 · 启动中</title>
<link rel="icon" href="/favicon.png?v=20261017">
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
    print("SELFTEST " + ("OK" if ok else "FAIL") + " services=",
          status(), flush=True)
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
    # The daemon serves the workbench and its service-status dashboard.
    # Open it while model processes load; --no-browser remains a full-stack check.
    print("等待服务就绪…", flush=True)
    st = status()
    for _ in range(150):
        print("  ", st, flush=True)
        if st["daemon"] and (not a.no_browser or all(st.values())):
            break
        time.sleep(1)
        st = status()
    if not all(st.values()):
        print("部分服务未就绪:", st, flush=True)
    if a.no_browser:
        print("services:", st, flush=True)
        return 0 if all(st.values()) else 1
    if not st["daemon"]:
        print("工作台服务未就绪，请查看 cache/logs/daemon.log", flush=True)
        return 1
    webbrowser.open("http://127.0.0.1:8321/")
    print("已打开工作台 http://127.0.0.1:8321", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
