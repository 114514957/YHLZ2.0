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
import time
import urllib.request
import webbrowser
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backend.yhlz_paths import (  # noqa: E402
    BOT_UIN, GEMMA_GGUF, LLAMA_EXE, MASTER_UIN, MMPROJ_GGUF,
    NAPCAT_LAUNCHER, OLLAMA_EXE, YH_BASE_GGUF, YH_LLAMA_EXE, YH_LORA_GGUF,
    YH_MMPROJ_GGUF,
)

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

# 2026-10-21 P0：Ollama 在本机长期 500，却仍被当必选服务每 60 秒等待/刷日志。
# 只把 gemma/daemon 当关键服务；Ollama 要显式 YHLZ_START_OLLAMA=1 才尝试。
CRITICAL_SERVICES = ("gemma", "daemon")
GPU_WINDOW_FLAG = _ROOT / "cache" / "gpu_window.lock"
GPU_WINDOW_MAX_AGE = 1200.0


def ready(st: dict) -> bool:
    return all(bool(st.get(k)) for k in CRITICAL_SERVICES)


def gpu_window_active() -> bool:
    """True while a singing/Seed-VC window owns the GPU.

    The watchdog must keep running (it is the independent supervisor), but it
    must not respawn llama during the window.  A stale flag expires so a
    crashed job cannot leave the stack down forever.
    """
    try:
        if not GPU_WINDOW_FLAG.exists():
            return False
        if time.time() - GPU_WINDOW_FLAG.stat().st_mtime > GPU_WINDOW_MAX_AGE:
            GPU_WINDOW_FLAG.unlink(missing_ok=True)
            return False
        return True
    except Exception:
        return False


def _open_log(path: pathlib.Path, max_bytes: int = 8 * 1024 * 1024):
    """Rotate before spawn (never while a process holds the file open)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > max_bytes:
            backup = path.with_name(path.name + ".1")
            backup.unlink(missing_ok=True)
            path.replace(backup)
    except Exception:
        pass
    return open(path, "ab")

# 0832: 启动器从 pythonw 跑（开机自启/桌面入口）时没有控制台，出问题只能靠
# 这份日志定位。每次 spawn / 失败都落一行，别让"只起来一半"再静默发生。
LAUNCHER_LOG = _ROOT / "cache" / "logs" / "launcher.log"


def _log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LAUNCHER_LOG.parent.mkdir(parents=True, exist_ok=True)
        with LAUNCHER_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _try_spawn(name: str, fn) -> bool:
    """One broken spawn must not abort the rest of the stack (0832)."""
    try:
        fn()
        _log(f"spawn {name}: requested")
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"spawn {name} FAILED: {type(exc).__name__}: {exc}")
        return False

# QQ bridge (optional): kept alive only when NapCat's OneBot WS is up.
QQBOT_UIN = BOT_UIN
QQBOT_MASTER = MASTER_UIN
QQBOT_PORT = 3001
QQBOT_LOCK = _ROOT / "cache" / "tmp" / "qqbot.lock"
NAPCAT_WATCH_LOCK = _ROOT / "cache" / "tmp" / "napcat_watch.lock"
QQ_MANAGEMENT_FILE = _ROOT / "config" / "qq_management.json"


_QQ_MGMT_WARNED = False


def qq_management() -> str:
    """full | external (default **external**, fail-closed since 0831).

    external: another bridge build owns the QQ account (Lite chain); the Full
    launcher/watchdog must not start/stop the QQ bridge, NapCat or
    napcat_watch. Env YHLZ_QQ_MANAGEMENT wins, then config file.

    缺文件/坏 JSON 时不再回落 full——那会自动拉起旧 qq_bot/napcat_watch，
    和 Lite 抢同一个 QQ 号。要回滚旧链：设 YHLZ_QQ_MANAGEMENT=full 或把
    config/qq_management.json 改成 full。
    """
    global _QQ_MGMT_WARNED
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
    if not _QQ_MGMT_WARNED:
        _QQ_MGMT_WARNED = True
        print("[launcher] qq_management 配置缺失/损坏 → fail-closed 按 external"
              "（回滚旧链：config/qq_management.json 或 YHLZ_QQ_MANAGEMENT=full）",
              flush=True)
    return "external"


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
                     stdout=_open_log(log), stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     close_fds=True)


def _allow_no_lora() -> bool:
    return str(os.getenv("YHLZ_ALLOW_BASE_NO_LORA", "")).strip().lower() in (
        "1", "true", "yes", "on")


def _spawn_llama():
    """v6 生产链（记录 0398/0426）：QAT-Q4 + mmproj(CPU) + v7b LoRA。

    旧 gemma-aggr 配置只在 v6 资产缺失时兜底——此前 watchdog 会用它抢占
    8081，导致项目调用到的不是元亨。
    0831：v6 资产在、但 LoRA 缺失时不再静默起基座（人格消失但 /health 正常，
    排查成本极高）；默认拒绝启动，YHLZ_ALLOW_BASE_NO_LORA=1 才放行。
    """
    if YH_LLAMA_EXE.exists() and YH_BASE_GGUF.exists():
        if not YH_LORA_GGUF.exists() and not _allow_no_lora():
            _log(f"生产 LoRA 缺失：{YH_LORA_GGUF}；拒绝用无 LoRA 基座冒充元亨"
                 "（YHLZ_ALLOW_BASE_NO_LORA=1 可强制）")
            return
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
    # 2026-10-20（ledger 0893）：服务子进程必须**脱离父进程**——否则父命令结束
    # （例如我在一次 exec 里起 llama）就会把 llama 一起带走，表现为"模型刚 ready 就掉"。
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | \
        getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(argv, cwd=str(_ROOT), stdout=_open_log(log, 12 * 1024 * 1024),
                     stderr=subprocess.STDOUT, creationflags=flags,
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
                     stdout=_open_log(log), stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     close_fds=True)


def _spawn_qqbot():
    pyw = PY.with_name("pythonw.exe")
    subprocess.Popen([str(pyw), "-B", str(_ROOT / "tools" / "qq_bot.py"),
                      "--uin", QQBOT_UIN, "--master", QQBOT_MASTER],
                     cwd=str(_ROOT), close_fds=True)


NAPCAT_BAT = NAPCAT_LAUNCHER

# 旧 QQ 链脚本（0830）：qq_management=external 时这些进程和 Lite 链抢同一个
# 账号/同一条 OneBot WS，必须收掉。只按「python 解释器的 argv 以脚本名结尾」
# 精确匹配，不碰别的 python，也不碰 Lite 的 qq_bridge_service.py。
LEGACY_QQ_MARKERS = ("tools/qq_bot.py", "tools/napcat_watch.py",
                     "tools/qq_bot_restart.py")


def _reap_legacy_qq() -> list[str]:
    """Kill leftover legacy Full-chain QQ consumers (external mode only).

    旧方式没删干净：``tools/qq_bot_start.bat``、手搓 ``pythonw qq_bot.py``、
    ``napcat_watch.py`` 仍可能被老快捷方式/老脚本拉起来，和 Lite 链一起连
    OneBot WS、写旧状态文件，工作台就同时看到"新旧都启动了"。每个 tick
    把它们收掉，保证同一个 QQ 号只有一个消费者。qq_management=full 时不调用
    （想回滚旧链改回 full 即可）。
    """
    try:
        import psutil
    except Exception:
        return []
    me = os.getpid()
    killed: list[str] = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            pid = int(p.info["pid"])
            nm = str(p.info.get("name") or "").lower()
            cl = [str(x).replace("\\", "/").lower()
                  for x in (p.info.get("cmdline") or [])]
        except Exception:
            continue
        if pid == me or not nm.startswith("python"):
            continue
        hit = ""
        for arg in cl:
            for marker in LEGACY_QQ_MARKERS:
                if arg.endswith(marker):
                    hit = marker
                    break
            if hit:
                break
        if not hit:
            continue
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
            killed.append(f"{pid}:{hit.rsplit('/', 1)[-1]}")
        except Exception:
            continue
    # 旧链的 pid 锁：进程已经没了就是僵尸锁（旧桥/旧看护自己会在下次启动时
    # 误判"已有实例"），清掉；Lite 用 state_dir/bridge.lock，互不影响。
    try:
        from backend.qq_bridge_lock import pid_alive

        for lock_path in (QQBOT_LOCK, NAPCAT_WATCH_LOCK):
            if not lock_path.exists():
                continue
            try:
                old = int(lock_path.read_text(encoding="utf-8").strip() or "0")
            except Exception:
                old = 0
            if not old or not pid_alive(old):
                lock_path.unlink(missing_ok=True)
                killed.append(f"stale:{lock_path.name}")
    except Exception:
        pass
    return killed


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
    window = gpu_window_active()
    _log(f"ensure_stack: {st} critical={ready(st)} "
         f"gpu_window={'exclusive' if window else 'off'} qq_management={qq_management()}")
    # P0: Ollama is optional.  Do not spawn/wait/log it every tick; it has been
    # returning 500 on this machine and was blocking boot for ~3 minutes.
    if os.getenv("YHLZ_START_OLLAMA", "").strip().lower() in ("1", "true", "yes", "on"):
        if (not st["ollama"] and not _proc_alive("ollama")
                and not _port_open("127.0.0.1", 11434)
                and _spawn_allowed("ollama", 180)):
            _try_spawn("ollama", _spawn_ollama)
    # During a singing/Seed-VC window the watchdog stays alive but must not
    # bring llama back until the window closes.
    if (not window and not st["gemma"] and not _port_open("127.0.0.1", 8081)
            and not _proc_alive("llama-server")
            and _spawn_allowed("llama", 180)):
        _try_spawn("llama", _spawn_llama)
    if (not st["daemon"] and not _port_open("127.0.0.1", 8321)
            and not _proc_alive("target_daemon")
            and _spawn_allowed("daemon", 120)):
        _try_spawn("daemon", _spawn_daemon)
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
    else:
        # 0830: QQ 归 Lite 链，旧链残留（老快捷方式/老脚本拉起的 qq_bot.py、
        # napcat_watch.py）当场收掉，否则新旧两条链同时吃同一个 QQ 号。
        reaped = _reap_legacy_qq()
        if reaped:
            print(f"[launcher] external: 收掉旧 QQ 链残留 {reaped}", flush=True)
    time.sleep(1)
    return status()


def _self_test() -> None:
    """Startup test: ensure the whole stack and verify the workbench UI is
    served on 8321 (no boot page anymore)."""
    import urllib.request as _u

    ensure_stack()
    for _ in range(60):
        st = status()
        if ready(st):
            break
        time.sleep(1)
    ok = ready(status())
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
    _log(f"launcher start pid={os.getpid()} args={sys.argv[1:]} "
         f"qq_management={qq_management()}")
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
        if st["daemon"] and (not a.no_browser or ready(st)):
            break
        time.sleep(1)
        st = status()
    if not ready(st):
        print("关键服务未就绪（gemma/daemon）:", st, flush=True)
    _log(f"launcher final services={st} critical={ready(st)}")
    if a.no_browser:
        print("services:", st, "critical:", ready(st), flush=True)
        return 0 if ready(st) else 1
    if not st["daemon"]:
        print("工作台服务未就绪，请查看 cache/logs/daemon.log", flush=True)
        return 1
    webbrowser.open("http://127.0.0.1:8321/")
    print("已打开工作台 http://127.0.0.1:8321", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
