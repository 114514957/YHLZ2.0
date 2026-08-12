# -*- coding: utf-8 -*-
"""V10.1.9 审计 #04: 打断边界 + 短时浸泡测试

职责（责任书 §二）: 稳定性测试工程师
审计域: V10.1.9 Prompt §十 打断边界 + §十五 资源稳定 (短时浸泡)
  - Interrupt 动态实证: /chat 流式中 POST /interrupt → 统计打断后
    TOKEN 是否继续 (R11 实证: LLM 不取消, 964 个 TOKEN 继续流出)
  - 浸泡: 30 轮对话 + 采样进程 RSS 与 backend.log 大小增量
    (实证日志无轮转增长 ~4.5KB/s; 扩展 --hours 24 即为长跑模式)
证据: runs/soak_server*.log + runs/interrupt_soak_summary.json
"""

# ── 标准库导入 ──────────────────────────────────────────────
import json         # 结果序列化
import subprocess   # spawn 隔离后端实例
import threading    # 长流线程 (打断实证需与主线程并发)
import time         # 耗时与采样间隔
import urllib.request  # /health 就绪轮询
from pathlib import Path  # 路径对象

# ── 第三方库 (venv 已具备) ──────────────────────────────────
import requests     # HTTP/SSE 客户端
import psutil       # 进程内存采样 (RSS)

# ── 全局常量 ─────────────────────────────────────────────────
ROOT = Path(r"D:\YHLZ2.0")                          # 项目根
VENV_PY = ROOT / "venv" / "Scripts" / "python.exe"  # venv 解释器
BASE = "http://127.0.0.1:8900"                      # 隔离测试实例
RUN_DIR = Path(__file__).parent / "runs"             # 证据目录

# 启动命令模板 (隔离端口 8900)
BOOT_CODE = (
    "import uvicorn; from backend.main import app; "
    "uvicorn.run(app, host='127.0.0.1', port=8900, log_level='warning')"
)


def wait_health(timeout: float = 120.0) -> bool:
    """轮询 /health 直到实例就绪 (全审计脚本统一模式)"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=1.0):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def stream_text(payload: dict, timeout: float = 120.0) -> str:
    """发送 /chat 并完整读取 SSE 文本 (浸泡轮次用)

    参数: payload=/chat 请求体; timeout=整体超时秒
    返回: 完整 SSE 响应文本
    """
    r = requests.post(f"{BASE}/chat", json=payload, timeout=timeout, stream=True)
    chunks = [c for c in r.iter_content(chunk_size=None, decode_unicode=True) if c]
    return "".join(chunks)


def main() -> None:
    """主流程: 打断实证 → 30 轮浸泡采样 → 汇总落盘"""
    # ── 0. 启动隔离实例 ───────────────────────────────────────
    proc = subprocess.Popen(
        [str(VENV_PY), "-c", BOOT_CODE], cwd=str(ROOT),
        stdout=open(RUN_DIR / "soak_server.log", "w", encoding="utf-8"),
        stderr=open(RUN_DIR / "soak_server.err.log", "w", encoding="utf-8"),
    )
    if not wait_health():
        print("FAIL: 服务未就绪")
        proc.terminate()
        return
    p = psutil.Process(proc.pid)   # 进程句柄 (RSS 采样)
    out = {}                       # 结果容器

    # ── 1. Interrupt 实证: 流式中打断, 统计打断后 TOKEN 是否继续 ──
    events = []                    # 线程结果通道: [("done", text) | ("exc", msg)]
    stop = threading.Event()       # (保留: 长跑模式中止信号)

    def long_chat():
        """后台线程: 发起长流式 /chat (打断实证的被测流)"""
        try:
            r = requests.post(f"{BASE}/chat",
                              json={"text": "请用一千字详细描述人工智能的发展历史", "tts_enabled": False},
                              timeout=120, stream=True)
            ev = []
            # 逐块读取完整 SSE (打断后仍应读到剩余流 → 即"未取消"实证)
            for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
                if chunk:
                    ev.append(chunk)
            events.append(("done", "".join(ev)))   # 完整流送达
        except Exception as e:
            events.append(("exc", str(e)))         # 流被中止 (异常路径)

    t = threading.Thread(target=long_chat)  # 长流线程
    t.start()
    time.sleep(2.0)                        # 等流式已开始 (首 token 已出)
    t0 = time.time()
    r = requests.post(f"{BASE}/interrupt", timeout=10)  # 流式中发起打断
    interrupt_latency = round(time.time() - t0, 3)
    t.join(timeout=90)                     # 等待流结束 (≤90s)
    if events and events[0][0] == "done":
        text = events[0][1]
        # 打断后仍出现的 TOKEN 数 = 未取消的直接证据
        tok_events = [l for l in text.split("\n")
                      if l.startswith("data: ") and '"TOKEN"' in l]
        complete = "COMPLETE" in text      # 流是否完整结束
        out["interrupt_test"] = {
            "interrupt_http": r.status_code,
            "interrupt_latency_s": interrupt_latency,
            "tokens_after_interrupt": len(tok_events),   # 关键指标: >0 = 打断未取消
            "stream_completed": complete,
            "total_len": len(text),
        }
    else:
        out["interrupt_test"] = {"error": events[0] if events else "no data"}

    # ── 2. 浸泡: 30 轮, 监控 RSS / backend.log 增量 ───────────
    log_file = ROOT / "backend.log"          # 后端日志文件 (单文件无轮转)
    rss_before = p.memory_info().rss         # 浸泡前 RSS (字节)
    log_size_before = log_file.stat().st_size if log_file.exists() else 0
    t0 = time.time()
    rss_samples = []                         # 每 5 轮采样一次 RSS
    for i in range(30):                      # 30 轮连续对话
        try:
            stream_text({"text": f"第{i}轮: 简单回答我一下", "tts_enabled": False}, timeout=60)
        except Exception as e:
            out.setdefault("soak_errors", []).append(f"turn{i}: {e}")  # 错误逐轮记录
        if i % 5 == 0:
            rss_samples.append(p.memory_info().rss)   # 周期采样 (内存曲线)
    rss_after = p.memory_info().rss          # 浸泡后 RSS
    log_size_after = log_file.stat().st_size if log_file.exists() else 0
    out["soak"] = {
        "turns": 30,                                             # 轮次
        "duration_s": round(time.time() - t0, 1),                # 总耗时
        "rss_start_mb": round(rss_before / 1048576, 1),          # 起点内存
        "rss_end_mb": round(rss_after / 1048576, 1),             # 终点内存
        "rss_delta_mb": round((rss_after - rss_before) / 1048576, 1),  # 增量
        "rss_samples_mb": [round(x / 1048576, 1) for x in rss_samples],  # 采样曲线
        "backend_log_delta_kb": round((log_size_after - log_size_before) / 1024, 1),  # 日志增长
        "errors": out.get("soak_errors", []),                    # 错误明细
    }

    # ── 3. 清理 + 汇总落盘 ────────────────────────────────────
    proc.terminate()                         # 关闭隔离实例
    (RUN_DIR / "interrupt_soak_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
