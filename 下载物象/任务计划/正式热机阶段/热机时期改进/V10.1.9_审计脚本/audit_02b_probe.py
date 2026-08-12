# -*- coding: utf-8 -*-
"""V10.1.9 审计 #02b: 针对性探针 (VAD 打断 bug / TTS 引擎 / 模块状态 / SSE 中断恢复)

职责（责任书 §二）: 语音测试工程师
审计域: V10.1.9 Prompt §十 打断边界 + §十三 语音层 + §十六 安全恢复
  - VAD 打断 bug 复现: 连续 2 次 /vad/interrupt (状态机需 2 帧) 触发
    `audio_buffer.set_interrupted` AttributeError → HTTP 500
  - TTS 引擎链检查: /tts/engines 加载态 + 切换 edge 后合成音频 RMS 检测
    (RMS≈0 证明静音 mock, 即"播放无声"根因在 TTS 侧)
  - SSE 中断恢复: 流式中断开连接 → 新请求必须正常 (恢复不卡死)
证据: runs/probe_server*.log + runs/probe_summary.json
"""

# ── 标准库导入 ──────────────────────────────────────────────
import json         # 结果序列化与日志
import subprocess   # spawn 隔离后端实例
import time         # 耗时测量
import urllib.request  # /health 就绪轮询
from pathlib import Path  # 路径对象

# ── 第三方库 ─────────────────────────────────────────────────
import requests     # HTTP 客户端
import numpy as np  # 信号生成与 RMS 计算

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
    """轮询 /health 直到实例就绪 (与 #01/#02 同一模式)"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=1.0):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def speech_audio(duration: float = 1.0, sr: int = 16000) -> list:
    """生成高能量合成"语音" (VAD 探针用)

    说明: 振幅 0.9 的正弦 + 0.1 白噪声, RMS≈0.64 远超 VAD
    energy_threshold=0.015, 确保能量检测必触发
    """
    t = np.arange(int(duration * sr)) / sr
    signal = 0.9 * np.sin(2 * np.pi * 440 * t) + 0.1 * np.random.randn(len(t))
    return signal.astype(np.float32).tolist()


def main() -> None:
    """主流程: 四组针对性探针 → 汇总落盘"""
    # ── 0. 启动隔离实例 ───────────────────────────────────────
    proc = subprocess.Popen(
        [str(VENV_PY), "-c", BOOT_CODE], cwd=str(ROOT),
        stdout=open(RUN_DIR / "probe_server.log", "w", encoding="utf-8"),
        stderr=open(RUN_DIR / "probe_server.err.log", "w", encoding="utf-8"),
    )
    if not wait_health():
        print("FAIL: 服务未就绪")
        proc.terminate()
        return

    out = {}  # 探针结果容器

    # ── 1. VAD 打断 bug 复现: 连续两次 /vad/interrupt ─────────
    # (VAD 状态机 silence→speaking 需 min_voiced_frames=2 帧,
    #  单次调用只累计 1 帧; 第 2 次调用命中 has_speech=True 后
    #  执行 audio_buffer.set_interrupted(True) → AttributeError → 500)
    for i in (1, 2):
        r = requests.post(f"{BASE}/vad/interrupt",
                          json={"audio_data": speech_audio(), "sample_rate": 16000}, timeout=30)
        out[f"vad_interrupt_call{i}"] = {"http": r.status_code, "body": r.text[:300]}

    # ── 2. /modules/status: 各引擎加载态快照 ──────────────────
    # (对照审计: asr 应 stopped(按需加载), tts/vad/llm 应 running)
    r = requests.get(f"{BASE}/modules/status", timeout=10)
    out["modules_status"] = r.json()

    # ── 3. TTS 引擎链检查: 引擎列表 + 切换 edge + 合成 RMS ────
    r = requests.get(f"{BASE}/tts/engines", timeout=10)   # 引擎注册表快照
    out["tts_engines"] = r.json()
    r = requests.post(f"{BASE}/tts/engine", json={"engine": "edge-tts"}, timeout=30)
    out["tts_switch_edge"] = {"http": r.status_code, "body": r.text[:200]}
    t0 = time.time()
    r = requests.post(f"{BASE}/synthesize", json={"text": "测试声音是否正常", "voice": "Vivian"}, timeout=60)
    js = r.json() if r.status_code == 200 else {}
    audio = js.get("audio") or []
    if audio:
        # RMS 检测: 真实语音 RMS≈0.1~0.3; 静音 mock RMS≈0.01 量级
        arr = np.array(audio, dtype=np.float32)
        out["tts_synth_edge"] = {
            "http": r.status_code, "latency_s": round(time.time() - t0, 3),
            "samples": len(audio), "rms": round(float(np.sqrt(np.mean(arr ** 2))), 4),
            "sr": js.get("sample_rate"),
        }
    else:
        out["tts_synth_edge"] = {"http": r.status_code, "latency_s": round(time.time() - t0, 3),
                                 "body": r.text[:200]}

    # ── 4. SSE 中断恢复: 流式中断开 → 新请求必须正常 ──────────
    t0 = time.time()
    r1 = requests.post(f"{BASE}/chat", json={"text": "请用很长很长的话回答我", "tts_enabled": False},
                       timeout=10, stream=True)          # 短超时: 故意只取首块
    first_chunk = next(r1.iter_content(chunk_size=None, decode_unicode=True), "")
    r1.close()                                           # 主动断开 (模拟前端刷新)
    out["sse_abort"] = {"got_first_chunk_s": round(time.time() - t0, 2), "chunk_len": len(first_chunk)}
    t0 = time.time()
    r2 = requests.post(f"{BASE}/chat", json={"text": "你好", "tts_enabled": False}, timeout=60, stream=True)
    txt = "".join(c for c in r2.iter_content(chunk_size=None, decode_unicode=True) if c)
    out["sse_after_abort"] = {"http": r2.status_code, "complete": "COMPLETE" in txt,
                              "latency_s": round(time.time() - t0, 2), "len": len(txt)}

    # ── 5. 清理 + 汇总落盘 ────────────────────────────────────
    proc.terminate()
    (RUN_DIR / "probe_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
