"""
YHLZ 2.0 Demo WebUI 启动端
=========================
简单的 Flask 控制面板, 用于启动/停止 voice_chat_demo.py 子进程
支持: 引擎选择 / 语音对话启停 / 文本模式测试 / SSE 实时日志 / 延迟报告高亮

运行:
    python 对话DEMO/demo_webui.py
    浏览器访问 http://127.0.0.1:5050
"""

import os
import re
import sys
import json
import atexit
import signal
import threading
import subprocess
import time
from collections import deque
from pathlib import Path

# ── 统一 UTF-8 编码 (避免 Windows 下中文/emoji 乱码) ──
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from flask import Flask, render_template, request, jsonify, Response

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_SCRIPT = Path(__file__).parent / "voice_chat_demo.py"
PYTHON_EXE = sys.executable

app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))

# ── 全局状态 ──
_state = {
    "process": None,        # subprocess.Popen
    "mode": "idle",         # idle | voice | text
    "engine": "qwen3-tts-customvoice",
    "pid": None,
    "started_at": None,
}
_lock = threading.Lock()
_log_buffer = deque(maxlen=2000)  # 环形日志缓冲
_log_subscribers = []              # SSE 订阅者


def _push_log(line: str):
    """推入一条日志并通知所有 SSE 订阅者"""
    _log_buffer.append(line)
    for q in list(_log_subscribers):
        try:
            q.append(line)
        except Exception:
            pass


def _reader_thread(proc: subprocess.Popen):
    """后台读取子进程 stdout, 逐行推入日志缓冲"""
    try:
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip("\n\r")
            if line:
                _push_log(line)
    except Exception as e:
        _push_log(f"[WebUI] 读取日志出错: {e}")
    finally:
        with _lock:
            if _state["process"] is proc:
                _state["process"] = None
                _state["pid"] = None
                old_mode = _state["mode"]
                _state["mode"] = "idle"
                _push_log(f"[WebUI] Demo 进程已退出 (模式: {old_mode})")


def _start_process(args: list, mode: str):
    """启动 demo 子进程"""
    with _lock:
        if _state["process"] is not None:
            return False, "已有 Demo 进程在运行, 请先停止"

        cmd = [PYTHON_EXE, "-u", str(DEMO_SCRIPT)] + args
        _push_log(f"[WebUI] 启动: {' '.join(cmd)}")

        # 设置 UTF-8 环境, 避免 emoji 字符在 Windows GBK 编码下报 UnicodeEncodeError
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        _state["process"] = proc
        _state["mode"] = mode
        _state["pid"] = proc.pid
        _state["started_at"] = time.time()

    threading.Thread(target=_reader_thread, args=(proc,), daemon=True).start()
    return True, f"已启动 (PID={proc.pid})"


def _stop_process():
    """停止 demo 子进程"""
    with _lock:
        proc = _state["process"]
        if proc is None:
            return False, "没有运行中的 Demo 进程"
        _state["mode"] = "idle"

    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        _push_log("[WebUI] Demo 进程已停止")
    except Exception as e:
        _push_log(f"[WebUI] 停止失败: {e}")
        return False, str(e)

    with _lock:
        _state["process"] = None
        _state["pid"] = None
    return True, "已停止"


# ── 路由 ──
@app.route("/")
def index():
    return render_template("demo.html")


@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(force=True) or {}
    engine = data.get("engine", "qwen3-tts-customvoice")
    _state["engine"] = engine
    args = ["--engine", engine]
    ok, msg = _start_process(args, "voice")
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    ok, msg = _stop_process()
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/text", methods=["POST"])
def api_text():
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    engine = data.get("engine", "qwen3-tts-customvoice")
    if not text:
        return jsonify({"ok": False, "msg": "文本不能为空"})
    # 文本模式: 运行完自动退出, 复用 _start_process
    # 如果已有进程在跑, 先停掉
    with _lock:
        if _state["process"] is not None:
            return jsonify({"ok": False, "msg": "已有 Demo 进程在运行, 请先停止"})
    _state["engine"] = engine
    args = ["--engine", engine, "--text", text]
    ok, msg = _start_process(args, "text")
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/status")
def api_status():
    with _lock:
        proc = _state["process"]
        running = proc is not None and proc.poll() is None
        return jsonify({
            "running": running,
            "mode": _state["mode"] if running else "idle",
            "engine": _state["engine"],
            "pid": _state["pid"] if running else None,
        })


@app.route("/api/logs")
def api_logs():
    """SSE: 实时推送日志"""
    def stream():
        q = deque(maxlen=200)
        _log_subscribers.append(q)
        try:
            # 先推送历史日志
            for line in list(_log_buffer):
                yield f"data: {json.dumps(line, ensure_ascii=False)}\n\n"
            # 再实时推送新日志
            while True:
                if q:
                    line = q.popleft()
                    yield f"data: {json.dumps(line, ensure_ascii=False)}\n\n"
                else:
                    time.sleep(0.2)
                    yield ": keepalive\n\n"
        finally:
            try:
                _log_subscribers.remove(q)
            except ValueError:
                pass

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/logs/clear", methods=["POST"])
def api_logs_clear():
    _log_buffer.clear()
    return jsonify({"ok": True})


# ── 延迟追踪: 从日志解析最近的延迟报告 ──
# 报告行格式: "  语音段时长:       1500ms" 或 "  ★ 端到端(说完→听到): 2930ms" 或 "  ASR: N/A"
_LATENCY_PATTERN = re.compile(r"\s*(?:★\s*)?(.+?):\s+(?:(\d+)ms|N/A)")

def _parse_latency_report():
    """从日志缓冲中解析最近一次延迟追踪报告, 返回结构化数据"""
    lines = list(_log_buffer)
    # 倒序查找 "延迟追踪报告"
    report_start = -1
    for i in range(len(lines) - 1, -1, -1):
        if "延迟追踪报告" in lines[i]:
            report_start = i
            break
    if report_start == -1:
        return {"available": False}

    metrics = []
    key_metrics = {}  # 端到端/总响应
    for i in range(report_start + 1, min(report_start + 15, len(lines))):
        line = lines[i]
        if "════" in line or "────" in line:
            continue
        m = _LATENCY_PATTERN.match(line)
        if m:
            name = m.group(1).strip()
            value_str = m.group(2)
            value = int(value_str) if value_str else None
            is_key = "★" in line or "端到端" in name or "总响应" in name
            entry = {"name": name, "value": value, "is_key": is_key}
            if is_key:
                key_metrics[name] = value
            else:
                metrics.append(entry)

    # 找最大延迟项 (非 key 的)
    max_metric = None
    for m in metrics:
        if m["value"] is not None:
            if max_metric is None or m["value"] > max_metric["value"]:
                max_metric = m

    return {
        "available": True,
        "metrics": metrics,
        "key_metrics": key_metrics,
        "max_metric": max_metric,
        "timestamp": time.time(),
    }


@app.route("/api/latency")
def api_latency():
    return jsonify(_parse_latency_report())


# ── 退出清理: 确保 demo 子进程被杀掉 ──
def _cleanup():
    with _lock:
        proc = _state["process"]
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        print("[WebUI] 已清理 demo 子进程")

atexit.register(_cleanup)

def _signal_handler(signum, frame):
    _cleanup()
    sys.exit(0)

# Windows 下 SIGBREAK (Ctrl+Break) 和 SIGINT (Ctrl+C)
if os.name == "nt":
    signal.signal(signal.SIGBREAK, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


if __name__ == "__main__":
    print("=" * 50)
    print("  YHLZ 2.0 Demo WebUI")
    print("  访问: http://127.0.0.1:5050")
    print("  Ctrl+C 或关闭窗口退出 (自动清理子进程)")
    print("=" * 50)

    # 自动打开浏览器
    import webbrowser
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5050")).start()

    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
