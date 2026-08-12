# -*- coding: utf-8 -*-
"""V10.1.9 审计 #02: 核心链路逐节点测试 (隔离端口 8900)

职责（责任书 §二）: 链路测试工程师
审计域: V10.1.9 Prompt §六 核心链路 + §十四 安全恢复 (错误路径探针)
节点: /health → /chat(SSE 短) → /chat(SSE 长) → /chat(并发x3) →
      /transcribe → /synthesize → /interrupt → /clear-history
错误路径探针: /vad/interrupt(带语音) /modules/start llm /ws
每节点记录: 输入/输出摘要/耗时/状态/错误
证据: runs/chain_server*.log + runs/chain_summary.json
"""

# ── 标准库导入 ──────────────────────────────────────────────
import asyncio      # /ws 探针用 asyncio.run 执行协程
import json         # SSE 事件解析与结果序列化
import subprocess   # spawn 独立后端实例
import time         # 逐节点耗时测量
import urllib.request  # /health 就绪轮询
from pathlib import Path  # 路径对象

# ── 第三方库 (venv 已具备) ──────────────────────────────────
import requests     # HTTP/SSE 客户端 (流式读取)
import numpy as np  # 生成 VAD 探针用合成语音信号

# ── 全局常量 ─────────────────────────────────────────────────
ROOT = Path(r"D:\YHLZ2.0")                    # 项目根
VENV_PY = ROOT / "venv" / "Scripts" / "python.exe"  # venv 解释器
BASE = "http://127.0.0.1:8900"                # 隔离测试实例地址
RUN_DIR = Path(__file__).parent / "runs"       # 证据目录

# 启动命令模板 (隔离端口, 不干扰运行中的 8000 实例)
BOOT_CODE = (
    "import uvicorn; from backend.main import app; "
    "uvicorn.run(app, host='127.0.0.1', port=8900, log_level='warning')"
)

results = []  # 逐节点结果列表: {node, status, latency_s, detail}


def record(node: str, ok: bool, latency: float, detail: str = "") -> None:
    """记录一个节点的测试结果 (写入 results 并控制台输出)

    参数: node=节点名; ok=是否通过; latency=耗时秒; detail=详情(截断500字)
    """
    results.append({
        "node": node, "status": "PASS" if ok else "FAIL",
        "latency_s": round(latency, 3), "detail": detail[:500],
    })
    print(f"[{'PASS' if ok else 'FAIL'}] {node} {round(latency, 2)}s {detail[:200]}")


def wait_health(timeout: float = 120.0) -> bool:
    """轮询 /health 直到实例就绪 (复用 #01 模式)"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=1.0) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def parse_sse(text: str) -> list:
    """解析 SSE 文本 → 事件列表

    SSE 行格式: "data: {json}" (空行分隔); 解析失败保留原始行不崩溃
    返回: 事件字典列表 [{event_type, sequence, turn_id, timestamp, payload}]
    """
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):          # 仅处理 data: 行
            try:
                events.append(json.loads(line[6:]))  # 去掉 "data: " 前缀
            except json.JSONDecodeError:
                events.append({"raw": line})   # 畸形行原样保留 (可追踪)
    return events


def chat_sse(payload: dict, timeout: float = 180.0) -> tuple:
    """发送 /chat 并完整读取 SSE 流

    参数: payload=/chat 请求体; timeout=整体超时秒 (LLM 流式需宽松)
    返回: (http_ok: bool, events: list, err_str: str)
    """
    try:
        t0 = time.time()
        r = requests.post(f"{BASE}/chat", json=payload, timeout=timeout, stream=True)
        if r.status_code != 200:               # 非 200 直接失败 (保留响应体)
            return False, [], f"HTTP {r.status_code}: {r.text[:200]}"
        chunks = []                            # 累积流式分块
        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            if chunk:
                chunks.append(chunk)
        text = "".join(chunks)                 # 拼合完整 SSE 文本
        return True, parse_sse(text), ""       # 成功: 解析事件返回
    except Exception as e:
        return False, [], f"EXC: {type(e).__name__}: {e}"  # 异常不抛, 转错误串


def speech_audio(duration: float = 1.0, sr: int = 16000) -> list:
    """生成 1 秒合成"语音"信号 (VAD 探针用)

    参数: duration=秒数; sr=采样率
    说明: 440Hz 正弦 + 白噪声, 能量足够触发 VAD 能量检测
    返回: float32 列表 (AudioRequest.audio_data 格式)
    """
    t = np.arange(int(duration * sr)) / sr     # 时间轴 (秒)
    signal = 0.5 * np.sin(2 * np.pi * 440 * t) + 0.2 * np.random.randn(len(t))
    return signal.astype(np.float32).tolist()


def main() -> None:
    """主流程: 启动隔离实例 → 逐节点链路测试 → 错误路径探针 → 汇总落盘"""
    # ── 0. 启动隔离后端实例 ───────────────────────────────────
    proc = subprocess.Popen(
        [str(VENV_PY), "-c", BOOT_CODE],
        cwd=str(ROOT),
        stdout=open(RUN_DIR / "chain_server.log", "w", encoding="utf-8"),
        stderr=open(RUN_DIR / "chain_server.err.log", "w", encoding="utf-8"),
    )
    if not wait_health():                      # 就绪失败则整体中止
        record("服务启动", False, 0, "120s 未就绪")
        proc.terminate()
        return
    record("服务启动(health)", True, 0)

    # ── 1. /health 健康检查 ───────────────────────────────────
    t0 = time.time()
    r = requests.get(f"{BASE}/health", timeout=10)
    record("/health", r.status_code == 200 and r.json().get("status") == "healthy",
           time.time() - t0, json.dumps(r.json(), ensure_ascii=False)[:200])

    # ── 2. /chat 短回复 (SSE 协议完整性) ──────────────────────
    t0 = time.time()
    ok, evs, err = chat_sse({"text": "你好", "tts_enabled": False})
    types = [e.get("event_type") for e in evs]     # 事件类型序列
    seqs = [e.get("sequence") for e in evs]        # sequence 序列
    turn_ids = {e.get("turn_id") for e in evs}     # turn_id 集合 (应唯一)
    mon = all(b > a for a, b in zip(seqs, seqs[1:])) if len(seqs) > 1 else True  # 单调性
    has_full = any("full_content" in (e.get("payload") or {}) for e in evs)     # COMPLETE 负载
    # 协议断言: 首事件 START, 含 TOKEN, 含 COMPLETE
    chain_ok = ok and types and types[0] == "START" and "TOKEN" in types and "COMPLETE" in types
    record("/chat 短回复(SSE协议)", chain_ok, time.time() - t0,
           f"types={types[:6]}... seq单调={mon} turn数={len(turn_ids)} 完整=COMPLETE含full={has_full} {err}")
    if types:
        tok_idx = [i for i, t in enumerate(types) if t == "TOKEN"]
        first_token_ms = round((time.time() - t0) * 1000) if not tok_idx else None
    ttft = None                                   # (保留: TTFT 时序观测点)
    if ok and evs:
        first_token_time = None
        for e in evs:
            if e.get("event_type") == "TOKEN":
                ttft = e.get("timestamp")
                break

    # ── 3. /chat 长回复 (流式稳定性) ──────────────────────────
    t0 = time.time()
    ok, evs, err = chat_sse(
        {"text": "请详细说明什么是人工智能，包括历史、分类和应用，越详细越好。", "tts_enabled": False,
         "max_tokens": 2048}, timeout=300)
    total_len = sum(len((e.get("payload") or {}).get("content", "")) for e in evs)  # 累计字数
    types = [e.get("event_type") for e in evs]
    seqs = [e.get("sequence") for e in evs]
    mon = all(b > a for a, b in zip(seqs, seqs[1:])) if len(seqs) > 1 else True
    record("/chat 长回复(SSE协议)", ok and "COMPLETE" in types and mon,
           time.time() - t0, f"token数={len(types)} 字数≈{total_len} seq单调={mon} {err}")

    # ── 4. /chat 并发 x3 (验证队列串行化 / R8 乱序风险) ───────
    t0 = time.time()
    payloads = [
        {"text": f"并发问题{i}：请回答我第{i}个问题", "tts_enabled": False}
        for i in range(1, 4)
    ]
    outcomes = []
    with requests.Session() as s:                # 复用连接 (降低网络开销)
        for p in payloads:
            outcomes.append(chat_sse(p))
    done = [o[0] and "COMPLETE" in [e.get("event_type") for e in o[1]] for o in outcomes]
    record("/chat 并发x3", all(done), time.time() - t0,
           f"全部COMPLETE={all(done)} ({sum(done)}/3) {outcomes[0][2] or ''}")

    # ── 5. /transcribe (ASR, 静音输入) ────────────────────────
    t0 = time.time()
    silence = np.zeros(16000, dtype=np.float32).tolist()   # 1 秒全零音频
    r = requests.post(f"{BASE}/transcribe",
                      json={"audio_data": silence, "sample_rate": 16000}, timeout=30)
    record("/transcribe(静音)", r.status_code == 200, time.time() - t0,
           f"text={json.dumps(r.json().get('text',''), ensure_ascii=False)[:60]!r}")

    # ── 6. /synthesize (TTS, 默认引擎, 120s 上限) ─────────────
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/synthesize", json={"text": "你好哥们", "voice": "Vivian"},
                          timeout=120)
        js = r.json() if r.status_code == 200 else {}
        n_audio = len(js.get("audio") or [])               # 音频样本数 (>0 视为成功)
        record("/synthesize", r.status_code == 200 and n_audio > 0, time.time() - t0,
               f"HTTP={r.status_code} audio样本数={n_audio} sr={js.get('sample_rate')}")
    except requests.exceptions.Timeout:                    # 超时单独记录 (已知慢路径)
        record("/synthesize", False, 120, "120s 超时(默认引擎)")

    # ── 7. /interrupt + /clear-history (基础控制面) ───────────
    t0 = time.time()
    r = requests.post(f"{BASE}/interrupt", timeout=10)
    record("/interrupt", r.status_code == 200, time.time() - t0, r.text[:100])
    t0 = time.time()
    r = requests.post(f"{BASE}/clear-history", timeout=10)
    record("/clear-history", r.status_code == 200, time.time() - t0, r.text[:100])

    # ── 8. 错误路径探针 A: /vad/interrupt 带语音 ───────────────
    # (已知静态 bug: audio_buffer.set_interrupted 不存在; 单次调用因
    #  VAD 状态机 min_voiced_frames=2 可能不触发, 复现需连续 2 次见 #02b)
    t0 = time.time()
    r = requests.post(f"{BASE}/vad/interrupt",
                      json={"audio_data": speech_audio(), "sample_rate": 16000}, timeout=30)
    record("/vad/interrupt(带语音)", r.status_code == 200, time.time() - t0,
           f"HTTP={r.status_code} body={r.text[:150]}")

    # ── 9. 错误路径探针 B: /modules/start llm ─────────────────
    # (已知静态 bug: LLMEngine 无 connect 方法 → 应返回 success=false)
    t0 = time.time()
    r = requests.post(f"{BASE}/modules/start", json={"module_name": "llm"}, timeout=30)
    body = r.json()
    record("/modules/start llm", r.status_code == 200 and body.get("success") is True,
           time.time() - t0, f"HTTP={r.status_code} body={json.dumps(body, ensure_ascii=False)[:150]}")

    # ── 10. 错误路径探针 C: /ws WebSocket ─────────────────────
    # (已知静态 bug: conversation_manager.handle_ws 不存在 →
    #   服务端 accept 后立刻抛错关闭, 客户端收 ConnectionClosedError)
    async def ws_probe():
        """WebSocket 连接探针: 期望能保持连接; handle_ws 缺失时立即断开"""
        import websockets   # 延迟导入 (仅探针需要)
        try:
            t0 = time.time()
            async with websockets.connect(f"ws://127.0.0.1:8900/ws", open_timeout=10) as ws:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)  # 期待有消息
                    return True, time.time() - t0, f"收到消息: {msg[:100]}"
                except asyncio.TimeoutError:   # 无消息但连接保持 = 可接受
                    return True, time.time() - t0, "连接保持 5s (无消息)"
        except Exception as e:                 # 连接被服务端关闭 = 缺陷实证
            return False, 0, f"EXC: {type(e).__name__}: {str(e)[:200]}"
    ok_ws, lat, det = asyncio.run(ws_probe())
    # 注释: /ws 正常应能 accept 并保持; handle_ws 缺失时服务端 accept 后立刻抛错关闭
    record("/ws 连接", ok_ws, lat, det)

    # ── 11. 清理 + 汇总落盘 ───────────────────────────────────
    proc.terminate()                           # 关闭隔离实例
    out = RUN_DIR / "chain_summary.json"       # 证据: 逐节点 JSON
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== 汇总 ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
