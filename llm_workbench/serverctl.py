"""llama-server 进程管理：工作台只碰自己起的那个实例。

边界（写死，别越线）：
  · 工作台只启动/停止 **自己起的** 进程（state 里记着 pid + 启动时间 + 端口）。
  · 别人的实例（老爹的 8081、历史测试的 8082）只**发现和展示**；
    要停必须由人在界面上点「停止外部实例」并确认，接口层面也要求显式的
    allow_external=True，不给自己留后门。
  · 显存不够就**如实报错**，不偷偷去杀别人的进程腾地方。

状态落盘 data/server.json，字段：pid / port / version / id / started_at / log。
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # YH/
LLAMA_DIR = os.path.join(ROOT, "models", "llama-cuda")
LLAMA_EXE = os.path.join(LLAMA_DIR, "llama-server.exe")
DATA_DIR = os.path.join(HERE, "data")
LOG_DIR = os.path.join(DATA_DIR, "logs")
STATE_JSON = os.path.join(DATA_DIR, "server.json")

DEFAULT_PORT = 8091
# 这些端口上常见的既有实例，只用于发现
CANDIDATE_PORTS = (8081, 8082, 8091, 8092, 8093, 8000)

_PROC = None  # 当前自管实例的 Popen 句柄（停实例时最可靠的一条路）


def _http_json(url: str, timeout: float = 2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _pid_alive(pid: int) -> bool:
    """进程还在不在。

    不用 `tasklist`：低完整性令牌下它会直接返回 `ERROR: Access denied`
    （2026-11-02 在沙箱里实撞：服务明明活着，状态页说没活）。
    先 psutil（带创建时间，能识别 PID 复用），退路是 kernel32.OpenProcess。
    """
    if not pid:
        return False
    try:
        import psutil
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except Exception:  # noqa: BLE001
        pass
    try:
        import ctypes
        STILL_ACTIVE = 259
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and code.value == STILL_ACTIVE
    except Exception:  # noqa: BLE001
        return False


def _read_state() -> dict:
    try:
        with open(STATE_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _write_state(d: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = STATE_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_JSON)


def _log_tail(path: str, n: int = 20000) -> str:
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - n))
            return f.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


# 启动是慢动作（加载 4.8 GB 要 20~60 秒），所以做成后台线程 + 轮询，
# 不让 HTTP 请求挂在那儿——页面也不会转圈转到超时。
_START = {"running": False, "error": "", "version": "", "started_at": 0, "result": None}
_START_LOCK = threading.Lock()


def _set_start(**kw) -> None:
    with _START_LOCK:
        _START.update(kw)


def start_async(version_id: str, gguf_path: str, base: str, mmproj: str,
                port: int = DEFAULT_PORT, ctx: int = 8192, ngl: int = 99,
                force: bool = False) -> dict:
    with _START_LOCK:
        if _START.get("running"):
            return {"ok": False, "error": "上一个实例还在启动中，等它结束"}
        _START.update({"running": True, "error": "", "version": version_id,
                       "started_at": time.time(), "result": None})

    def worker() -> None:
        try:
            r = start(version_id, gguf_path, base, mmproj, port, ctx, ngl, force)
            _set_start(running=False, result=r,
                       error="" if r.get("ok") else str(r.get("error", "")))
        except Exception as ex:  # noqa: BLE001
            _set_start(running=False, error="%s: %s" % (type(ex).__name__, ex))

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "starting": True, "version": version_id, "port": port}


MIN_FREE_MB = 5000  # 老爹 2026-11-08：模型按 5 GB 显存预算（本机 8 GB）


def gpu_mem() -> dict | None:
    """总/已用/空闲（MB），给工作台显示；拿不到就 None。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
        if not out:
            return None
        total, used, free = [int(x.strip()) for x in out[0].split(",")]
        return {"total_mb": total, "used_mb": used, "free_mb": free}
    except Exception:  # noqa: BLE001
        return None


def gpu_free_mb() -> int | None:
    m = gpu_mem()
    return m["free_mb"] if m else None


def probe_port(port: int) -> dict | None:
    """端口上有没有 llama-server，有就报它是什么。"""
    try:
        p = _http_json("http://127.0.0.1:%d/props" % port, timeout=1.5)
    except Exception:  # noqa: BLE001
        return None
    return {
        "port": port,
        "alias": p.get("model_alias") or "",
        "path": p.get("model_path") or "",
        "n_ctx": (p.get("default_generation_settings") or {}).get("n_ctx"),
    }


def _listening_map() -> dict[int, int]:
    """一次 netstat 拿到 {端口: pid}。

    原来每个端口各跑一次 netstat，六个候选端口就是 7.6 秒（2026-11-02 实测），
    整个 /api/state 卡在这儿。一次就够。
    """
    out: dict[int, int] = {}
    try:
        txt = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=20).stdout.splitlines()
    except Exception:  # noqa: BLE001
        return out
    for ln in txt:
        if "LISTENING" not in ln:
            continue
        parts = ln.split()
        if len(parts) < 5:
            continue
        try:
            port = int(parts[1].rsplit(":", 1)[-1])
            out[port] = int(parts[-1])
        except Exception:  # noqa: BLE001
            continue
    return out


_EXT_CACHE: dict = {"at": 0.0, "data": []}
EXT_TTL = 3.0


def discover_externals(own_port: int | None = None) -> list[dict]:
    now = time.time()
    if now - _EXT_CACHE["at"] < EXT_TTL:
        return [e for e in _EXT_CACHE["data"] if e["port"] != own_port]
    ports = _listening_map()
    out = []
    for port in CANDIDATE_PORTS:
        if port not in ports:
            continue
        info = probe_port(port)
        if info:
            info["pid"] = ports.get(port)
            out.append(info)
    _EXT_CACHE["at"] = now
    _EXT_CACHE["data"] = out
    return [e for e in out if e["port"] != own_port]


def _port_pid(port: int) -> int | None:
    return _listening_map().get(port)


def status(debug: bool = False) -> dict:
    t0 = time.time()
    st = _read_state()
    pid = int(st.get("pid") or 0)
    alive = _pid_alive(pid)
    t1 = time.time()
    own = {"running": alive, **st}
    if alive and st.get("port"):
        info = probe_port(int(st["port"]))
        own["healthy"] = bool(info)
        own["alias"] = (info or {}).get("alias", "")
        if st.get("started_at"):
            own["uptime_s"] = int(time.time() - float(st["started_at"]))
    else:
        own["healthy"] = False
    t2 = time.time()
    with _START_LOCK:
        starting = dict(_START)
    ext = discover_externals(own_port=st.get("port") if alive else None)
    t3 = time.time()
    free = gpu_free_mb()
    t4 = time.time()
    out = {
        "own": own,
        "starting": starting,
        "externals": ext,
        "gpu": gpu_mem(),
        "gpu_free_mb": free,
        "log_tail": _log_tail(st.get("log", ""), 6000) if alive else "",
    }
    if debug:
        out["timing_ms"] = {"alive": round((t1 - t0) * 1000),
                            "probe_own": round((t2 - t1) * 1000),
                            "externals": round((t3 - t2) * 1000),
                            "gpu": round((t4 - t3) * 1000),
                            "total": round((time.time() - t0) * 1000)}
    return out


def start(version_id: str, gguf_path: str, base: str, mmproj: str,
          port: int = DEFAULT_PORT, ctx: int = 8192, ngl: int = 99,
          force: bool = False) -> dict:
    """起一个实例。已经有一个在跑就先停掉（工作台自己的实例，等价于「切版本」）。"""
    if not os.path.exists(LLAMA_EXE):
        return {"ok": False, "error": "找不到 llama-server.exe：%s" % LLAMA_EXE}
    if not os.path.exists(gguf_path):
        return {"ok": False, "error": "找不到 LoRA：%s" % gguf_path}

    cur = status()
    if cur["own"]["running"]:
        stop()
    elif _port_pid(port):
        return {"ok": False, "error": "端口 %d 已被别的进程占用，换个端口或先停它" % port}

    free = gpu_free_mb()
    externals = discover_externals()
    if ngl > 0 and free is not None and free < MIN_FREE_MB and not force:
        names = "、".join("%s(:%d pid %s)" % (e["alias"] or "?", e["port"], e["pid"])
                         for e in externals) or "无"
        return {"ok": False, "error":
                "显存只剩 %d MB，起不来（模型预算 %d MB）。"
                "当前占着的实例：%s。先停一个，或加 force 硬起（可能 OOM）。"
                % (free, MIN_FREE_MB, names)}

    os.makedirs(LOG_DIR, exist_ok=True)
    log = os.path.join(LOG_DIR, "llama_%s_%d.log"
                       % (version_id.split(":")[-1].replace(".gguf", ""), int(time.time())))
    cmd = [LLAMA_EXE, "-m", base]
    if mmproj and os.path.exists(mmproj):
        cmd += ["--mmproj", mmproj, "--no-mmproj-offload"]
    cmd += ["--lora", gguf_path, "-ngl", str(ngl), "-c", str(ctx),
            "--parallel", "1", "-rea", "off", "--jinja",
            "--alias", version_id.split(":")[-1].replace(".gguf", ""),
            "--host", "127.0.0.1", "--port", str(port)]

    lf = open(log, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=LLAMA_DIR,
                            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    global _PROC
    _PROC = proc
    t0 = time.time()
    ok = False
    for i in range(120):                      # 最多 4 分钟，4.8 GB 模型通常 20~60 秒
        time.sleep(2)
        if proc.poll() is not None:
            return {"ok": False, "error": "进程退出（code=%s）" % proc.returncode,
                    "log": _log_tail(log, 4000)}
        try:
            h = _http_json("http://127.0.0.1:%d/health" % port, timeout=2)
            if h.get("status") == "ok":
                ok = True
                break
        except Exception:  # noqa: BLE001
            if i % 10 == 9:
                pass
    if not ok:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error": "等了 %d 秒没就绪" % (time.time() - t0),
                "log": _log_tail(log, 4000)}

    _write_state({"pid": proc.pid, "port": port, "version": version_id,
                  "started_at": time.time(), "log": log, "cmd": cmd,
                  "load_s": round(time.time() - t0, 1)})
    return {"ok": True, "pid": proc.pid, "port": port, "load_s": round(time.time() - t0, 1),
            "alias": version_id.split(":")[-1].replace(".gguf", "")}


def _kill(pid: int) -> tuple[bool, str]:
    """按三级退路杀进程，返回 (成功, 最后一条错误)。

    ① 自己起的子进程 → 直接用 Popen 句柄，最可靠；
    ② psutil → 先收子进程再收本体；
    ③ taskkill /T /F → 兜底（低完整性令牌下可能静默失败）。
    """
    err = ""
    if _PROC is not None and _PROC.pid == pid:
        try:
            if _PROC.poll() is None:
                _PROC.kill()
                _PROC.wait(timeout=10)
            return True, ""
        except Exception as ex:  # noqa: BLE001
            err = "handle: %s" % ex
    try:
        import psutil
        p = psutil.Process(pid)
        for ch in p.children(recursive=True):
            try:
                ch.kill()
            except Exception:  # noqa: BLE001
                pass
        p.kill()
        return True, ""
    except Exception as ex:  # noqa: BLE001
        err = (err + " | " if err else "") + "psutil: %s" % ex
    try:
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0, (r.stdout + r.stderr).strip()[:200]
    except Exception as ex:  # noqa: BLE001
        return False, (err + " | taskkill: %s" % ex)[:300]


def stop() -> dict:
    st = _read_state()
    pid = int(st.get("pid") or 0)
    if not pid or not _pid_alive(pid):
        _write_state({})
        return {"ok": True, "stopped": False, "why": "没有在跑的实例"}
    ok, err = _kill(pid)
    # 杀完必须核实：`taskkill` 在低完整性令牌下会静默失败（返回码看着正常，
    # 进程还在）。2026-11-02 实撞：API 说 stop 成功，8091 还在监听。
    for _ in range(20):
        if not _pid_alive(pid):
            break
        time.sleep(0.5)
    if _pid_alive(pid):
        return {"ok": False, "stopped": False, "pid": pid,
                "error": "进程 %d 没杀掉（%s）" % (pid, err or "权限不足")}
    _write_state({})
    return {"ok": True, "stopped": True, "pid": pid}


def stop_external(port: int) -> dict:
    """停别人的实例。只允许界面上明确确认后调用。"""
    pid = _port_pid(port)
    if not pid:
        return {"ok": False, "error": "端口 %d 上没有监听进程" % port}
    ok, err = _kill(pid)
    for _ in range(20):
        if not _pid_alive(pid):
            break
        time.sleep(0.5)
    alive = _pid_alive(pid)
    return {"ok": not alive, "pid": pid, "port": port, "still_up": bool(probe_port(port)),
            "error": "" if not alive else "没杀掉：%s" % (err or "权限不足")}
