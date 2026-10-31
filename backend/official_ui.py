"""官方 SoulX-Singer SVC UI（webui_svc.py / Gradio 7861）工作台托管（台账 0792）。

工作台入口：/control {official_ui_start|official_ui_stop} + GET /official-ui/status。
与聊天共用 GPU 互锁（backend.gpu_lock）与唱窗（backend.gpu_window）：

- start：卸本地 TTS → 停 llama/看护（唱窗）→ WSL 前台拉起官方 UI（进程句柄
  常驻本模块，随关闭而终止）→ 探测端口就绪；
- running：聊天/TTS 被 409 拒绝（与翻唱 SVC 唱窗一致），直到手动停止；
- stop：杀 UI 进程 → 恢复 llama/看护 → 释放互锁；UI 进程意外退出/被外部停止
  时，status() 自动收尾（best effort）。

若官方 UI 已在跑（如 tools/official_ui.py CLI 启动），start() 直接**接住**
现有实例（不重复开窗）；两者用同一端口探测与 `pkill -f [w]ebui_svc.py` 停止，
可以互相接住/停止对方启动的实例。
"""
from __future__ import annotations

import socket
import subprocess
import threading
import time
from pathlib import Path

from backend import gpu_lock, gpu_window

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 7861
_WSL_DISTRO = "Ubuntu-22.04"

_SETTLE_S = 2.0          # sing v3.1 (0745)：开窗前等显存回收落定
_PORT_WAIT_S = 240.0     # torch/gradio 冷启动慢，最多等 4 分钟
_PORT_POLL_S = 2.0
_OPEN_FREE_MB = 6500     # 与翻唱唱窗同阈值

_lock = threading.Lock()
_STATE: dict = {
    "status": "idle",    # idle | starting | running | stopping | error
    "step": "", "error": "", "port": DEFAULT_PORT,
    "started": 0.0, "finished": 0.0, "attached": False,
}
_proc: "subprocess.Popen | None" = None
_owns_lock = False       # 本模块是否持有（可释放）GPU 互锁


def _set(**kw) -> None:
    with _lock:
        _STATE.update(kw)


def _url(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}"


def _port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)),
                                      timeout=timeout):
            return True
    except OSError:
        return False


def _ui_alive() -> bool:
    """WSL 里是否已有 webui_svc.py 进程（可能是 CLI 启动的）。"""
    try:
        r = subprocess.run(
            ["wsl.exe", "-d", _WSL_DISTRO, "--", "bash", "-lc",
             "pgrep -f '[w]ebui_svc.py'"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=15)
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:
        return False


def state() -> dict:
    with _lock:
        d = dict(_STATE)
    d["url"] = _url(d.get("port") or DEFAULT_PORT)
    return d


def status() -> dict:
    """工作台状态：running 但 UI 已消失时自动收尾（释放互锁、恢复服务）。"""
    reap()
    with _lock:
        d = dict(_STATE)
    d.update(ok=True, url=_url(d.get("port") or DEFAULT_PORT))
    return d


def reap() -> None:
    """UI 在外部被停掉/崩溃（端口关且进程不在）→ 自动恢复聊天服务。"""
    with _lock:
        st = str(_STATE["status"])
        attached = bool(_STATE.get("attached"))
        port = int(_STATE.get("port") or DEFAULT_PORT)
    if st != "running":
        return
    if _port_open(port, timeout=0.3):
        return
    if _proc is not None and _proc.poll() is None:
        return
    if attached and _ui_alive():
        return          # 外部实例进程还在（可能仍在加载模型），不要动它
    try:
        stop(reason="external-stop")
    except Exception:
        pass


def start(port: int = DEFAULT_PORT) -> dict:
    """开唱窗并拉起官方 UI（后台线程）；已在跑则接住现有实例。"""
    global _proc, _owns_lock
    port = int(port or DEFAULT_PORT)
    with _lock:
        st = str(_STATE["status"])
        if st in ("starting", "running", "stopping"):
            return {"ok": False, "error": f"官方 UI 已在用（{st}）"}
        _proc = None
        _owns_lock = False
        _STATE.update(status="starting", step="检查现有实例", error="",
                      port=port, started=time.time(), finished=0.0,
                      attached=False)
    # 已在跑（CLI 等）→ 接住，不重复开唱窗
    if _port_open(port, timeout=0.5) or _ui_alive():
        owned = bool(gpu_lock.acquire_sing())
        if owned:
            gpu_lock.enter_window()   # 聊天互锁：与翻唱唱窗一致
        with _lock:
            _owns_lock = owned
            _STATE.update(status="running", step="运行中（接住现有实例）",
                          attached=True, started=time.time())
        return {"ok": True, "status": "running", "attached": True,
                "url": _url(port),
                "note": "官方 UI 已在运行（外部启动）→ 已接住，"
                        "关闭/恢复由本入口负责"}
    if not gpu_lock.acquire_sing():
        _set(status="idle", step="", error="")
        return {"ok": False, "error": "GPU 任务互锁：翻唱/官方 UI 已在跑"}
    with _lock:
        _owns_lock = True
    threading.Thread(target=_job, daemon=True, name="official-ui").start()
    return {"ok": True, "status": "starting", "port": port,
            "url": _url(port)}


def _kill_ui() -> None:
    """关掉 Gradio 进程（WSL 侧 + 包装进程），幂等。"""
    global _proc
    try:
        subprocess.run(
            ["wsl.exe", "-d", _WSL_DISTRO, "--", "bash", "-lc",
             "pkill -f '[w]ebui_svc.py' || true"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
    except Exception:
        pass
    try:
        if _proc is not None and _proc.poll() is None:
            _proc.terminate()
    except Exception:
        pass


def _restore() -> None:
    """关 UI + 恢复 llama/看护 + 释放互锁（best effort、幂等）。"""
    global _proc, _owns_lock
    _kill_ui()
    if _owns_lock:
        try:
            gpu_window.close_window()
        except Exception:
            pass
        try:
            gpu_lock.release_sing()
        except Exception:
            pass
        _owns_lock = False
    _proc = None


def stop(reason: str = "manual") -> dict:
    with _lock:
        st = str(_STATE["status"])
        if st == "starting":
            return {"ok": False,
                    "error": "启动中：请等就绪（或失败）后再关闭"}
        if st == "stopping":
            return {"ok": True, "status": "stopping", "note": "正在关闭…"}
        if st == "idle":
            return {"ok": True, "status": "idle", "note": "官方 UI 未在运行"}
        _STATE.update(status="stopping", step="关闭官方 UI 并恢复服务")
    _restore()
    with _lock:
        _STATE.update(status="idle", step="", error="", finished=time.time(),
                      attached=False)
    return {"ok": True, "status": "idle",
            "note": f"官方 UI 已关闭，聊天服务已恢复（{reason}）"}


def _job() -> None:
    global _proc
    from backend.console_server import _unload_tts

    try:
        port = int(state()["port"])
        _set(step="卸载本地 TTS，腾显存")
        _unload_tts()
        _set(step="等待聊天结束（GPU 互锁）")
        if not gpu_lock.enter_window():
            raise RuntimeError("互锁状态异常（无法进入唱窗）")
        gpu_lock.wait_chat_idle(timeout=120)
        _unload_tts()
        time.sleep(_SETTLE_S)
        _set(step="唱窗：暂停 LLM 与看护")
        win = gpu_window.open_window(require_free_mb=_OPEN_FREE_MB)
        if not win.get("ok"):
            _unload_tts()
            time.sleep(_SETTLE_S)
            win = gpu_window.open_window(require_free_mb=_OPEN_FREE_MB)
        if not win.get("ok"):
            raise RuntimeError(f"显存不足（free={win.get('free_mb')}MB）")
        _set(step=f"启动官方 UI（端口 {port}），首次加载约 1-2 分钟")
        # 2026-10-12 实测（另一会话定位）：WSL 直连 huggingface.co 不可达，
        # 官方 UI 起服务时会卡在模型元数据重试 → 固定走 hf-mirror（与
        # wsl_soulx_setup.sh 的镜像口径一致；已缓存模型则秒过）。
        inner = ("cd ~/soulx/SoulX-Singer && "
                 "export HF_ENDPOINT=${HF_ENDPOINT:-https://hf-mirror.com} "
                 "HF_HUB_DOWNLOAD_TIMEOUT=${HF_HUB_DOWNLOAD_TIMEOUT:-60} && "
                 "exec ~/soulx/venv/bin/python "
                 f"webui_svc.py --port {port}")
        _proc = subprocess.Popen(
            ["wsl.exe", "-d", _WSL_DISTRO, "--", "bash", "-lc", inner],
            cwd=str(_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t0 = time.time()
        while time.time() - t0 < _PORT_WAIT_S:
            if _port_open(port, timeout=0.5):
                _set(status="running", step="运行中", started=t0)
                return
            if _proc.poll() is not None:
                raise RuntimeError("webui_svc 进程退出（详见 WSL 日志）")
            time.sleep(_PORT_POLL_S)
        raise RuntimeError(f"官方 UI 端口 {port} 超时未就绪")
    except Exception as exc:  # noqa: BLE001
        _set(status="error", step="失败",
             error=f"{type(exc).__name__}: {exc}"[:280])
        _restore()
