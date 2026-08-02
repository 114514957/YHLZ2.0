"""
YHLZ 2.0 综合测试脚本 — 覆盖端口通信、模型间链路、全部核心功能
"""
import requests, json, time, sys, os, threading, queue
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "http://127.0.0.1:8000"
results = []

def check(name, ok, detail=""):
    status = "✅" if ok else "❌"
    msg = f"  {status} {name}"
    if detail:
        msg += f"  ({detail})"
    results.append((name, ok, detail))
    print(msg)
    return ok

def sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ============================================================
# 测试1: 后端核心服务健康检查 + 模块状态
# ============================================================
def test_1_health():
    sep("测试1: 后端核心服务 + 模块状态")
    
    # 1.1 健康检查
    r = requests.get(f"{BASE}/health", timeout=10)
    data = r.json()
    check("后端可达", r.status_code == 200)
    check("LLM已就绪", data.get("llm") == True)
    check("TTS已就绪", data.get("tts") == True)
    check("VAD已就绪", data.get("vad") == True)
    check("ASR模型", data.get("asr_model", "").startswith("Qwen3-ASR"), f"asr_model={data.get('asr_model')}")
    check("TTS模型", data.get("tts_model") == "edge-tts")
    check("AEC已启用", data.get("aec_enabled") == True)
    check("降噪已启用", data.get("noise_suppression_enabled") == True)
    check("WS统计正常", "active_connections" in data.get("websocket_stats", {}))
    
    # 1.2 模块状态
    r = requests.get(f"{BASE}/modules/status", timeout=10)
    modules = r.json().get("modules", {})
    check("模块状态接口可达", r.status_code == 200)
    check("asr模块存在", "asr" in modules)
    check("tts模块存在", "tts" in modules)
    check("llm模块存在", "llm" in modules)
    
    # 1.3 缓存状态
    r = requests.get(f"{BASE}/cache-stats", timeout=10)
    data = r.json()
    check("缓存状态接口", "context" in data)
    check("Token计数正常", isinstance(data["context"].get("token_count"), (int, float)))
    
    # 1.4 同步管理器状态
    r = requests.get(f"{BASE}/sync/status", timeout=10)
    data = r.json()
    check("同步管理器状态", r.status_code == 200)


# ============================================================
# 测试2: LLM → TTS → 播放 模型间链路
# ============================================================
def test_2_chat_tts_chain():
    sep("测试2: LLM → TTS → 播放 模型间链路")
    
    # 2.1 纯文本对话
    r = requests.post(f"{BASE}/chat", json={
        "text": "请用一句话回复：1+1等于几？",
        "tts_enabled": False
    }, timeout=30, stream=True)
    check("LLM SSE连接", r.status_code == 200)
    full = ""
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            try:
                chunk = json.loads(line[5:].strip())
                if "content" in chunk:
                    full += chunk["content"]
            except:
                pass
    check("LLM有回复", len(full) > 0, f"回复={len(full)}字")
    check("LLM回复含数字", any(c.isdigit() for c in full), f"内容: {full[:50]}")
    
    # 2.2 TTS合成
    r = requests.post(f"{BASE}/synthesize", json={
        "text": "你好，我是元亨助手",
        "voice": "vivian"
    }, timeout=30)
    data = r.json()
    check("TTS合成成功", data.get("success") == True)
    check("TTS有音频数据", len(data.get("audio", "")) > 0, f"base64长度={len(data.get('audio', ''))}")
    check("TTS采样率有效", data.get("sample_rate", 0) in (16000, 24000, 44100), f"sr={data.get('sample_rate')}")
    
    # 2.3 流式TTS
    r = requests.post(f"{BASE}/synthesize/stream", json={
        "text": "测试流式语音合成",
        "voice": "vivian"
    }, timeout=30, stream=True)
    check("流式TTS连接", r.status_code == 200)
    
    # 2.4 中断功能
    r = requests.post(f"{BASE}/interrupt", timeout=5)
    data = r.json()
    check("中断接口", data.get("success") == True)


# ============================================================
# 测试3: WebSocket 双端点
# ============================================================
def test_3_websocket():
    sep("测试3: WebSocket /ws/avatar + /ws/stream")
    
    try:
        import websocket
        
        # 3.1 /ws/avatar
        ws = websocket.create_connection("ws://127.0.0.1:8000/ws/avatar", timeout=5)
        check("ws/avatar 连接", True)
        ws.settimeout(3)
        data = ws.recv()
        msg = json.loads(data)
        check("ws/avatar 收到确认", msg.get("type") == "avatar_connected", f"type={msg.get('type')}")
        
        # 心跳
        ws.send(json.dumps({"type": "ping", "ts": time.time()}))
        ws.settimeout(3)
        data = ws.recv()
        msg = json.loads(data)
        check("ws/avatar 心跳响应", msg.get("type") == "pong" or msg.get("type") == "heartbeat", f"type={msg.get('type')}")
        ws.close()
        
        # 3.2 /ws/stream
        ws = websocket.create_connection("ws://127.0.0.1:8000/ws/stream", timeout=5)
        check("ws/stream 连接", True)
        ws.settimeout(3)
        data = ws.recv()
        msg = json.loads(data)
        check("ws/stream 收到确认", msg.get("type") in ("stream_connected", "connected"), f"type={msg.get('type')}")
        ws.close()
        
    except ImportError:
        check("websocket-client", False, "未安装 websocket-client 库")
    except Exception as e:
        check("WebSocket测试", False, str(e)[:60])


# ============================================================
# 测试4: Live2D 模型加载 + 表情控制
# ============================================================
def test_4_live2d():
    sep("测试4: Live2D 模型加载 + 表情控制")
    
    # 4.1 Live2D 状态
    r = requests.get(f"{BASE}/live2d/status", timeout=10)
    data = r.json()
    check("Live2D状态接口", r.status_code == 200)
    check("Live2D有模型列表", "available_models" in data or "models" in data)
    
    # 4.2 表情控制
    r = requests.post(f"{BASE}/live2d/emotion", json={
        "emotion": "happy",
        "intensity": 0.8
    }, timeout=10)
    data = r.json()
    check("Live2D表情控制", r.status_code == 200, f"返回: {data.get('message', '')[:40]}")
    
    # 4.3 口型测试
    r = requests.post(f"{BASE}/live2d/mouth", json={
        "value": 0.5
    }, timeout=10)
    check("Live2D口型控制", r.status_code in (200, 404, 503), f"状态码={r.status_code}")
    
    # 4.4 情绪强度
    r = requests.post(f"{BASE}/live2d/emotion-intensity", json={
        "emotion": "neutral",
        "intensity": 0.5
    }, timeout=10)
    check("Live2D情绪强度", r.status_code == 200)


# ============================================================
# 测试5: 端口间通信
# ============================================================
def test_5_port_comms():
    sep("测试5: 端口间通信")
    
    # 5.1 后端8000端口监听
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 8000))
    sock.close()
    check("端口8000监听", result == 0, f"connect_ex={result}")
    
    # 5.2 跨端口代理测试 (如果webui在8765)
    # 检查webui端口
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 8765))
    sock.close()
    webui_running = result == 0
    check("端口8765(WebUI)", webui_running, "运行中" if webui_running else "未启动(不影响核心)")
    
    # 5.3 后端API响应时间
    times = []
    for _ in range(3):
        start = time.time()
        r = requests.get(f"{BASE}/health", timeout=5)
        times.append((time.time() - start) * 1000)
    avg = sum(times) / len(times)
    check("后端响应时间<100ms", avg < 100, f"平均={avg:.1f}ms")
    
    # 5.4 并发请求
    def concurrent_get():
        try:
            r = requests.get(f"{BASE}/health", timeout=10)
            return r.status_code == 200
        except:
            return False
    
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(concurrent_get) for _ in range(5)]
        all_ok = all(f.result() for f in futures)
    check("并发5请求", all_ok)


# ============================================================
# 测试6: ASR模块 + 应急重置
# ============================================================
def test_6_asr_reset():
    sep("测试6: ASR模块 + 应急重置")
    
    # 6.1 ASR模块状态
    r = requests.get(f"{BASE}/modules/status", timeout=10)
    modules = r.json().get("modules", {})
    asr_info = modules.get("asr", {})
    check("ASR模块状态可查", "asr" in modules, f"状态={asr_info.get('status', 'unknown')}")
    
    # 6.2 应急重置
    r = requests.post(f"{BASE}/clear-history", timeout=10)
    data = r.json()
    check("应急重置成功", data.get("success") == True)
    
    # 验证重置效果
    r = requests.get(f"{BASE}/cache-stats", timeout=10)
    data = r.json()
    ctx = data["context"]
    check("重置后Token=0", ctx["token_count"] == 0, f"token_count={ctx['token_count']}")
    check("重置后历史=0", ctx["history_count"] == 0, f"history_count={ctx['history_count']}")
    
    # 6.3 性格配置
    try:
        r = requests.get(f"{BASE}/personality", timeout=10)
        data = r.json()
        check("性格配置接口", r.status_code == 200, f"name={data.get('config', {}).get('name', '')}")
    except Exception as e:
        check("性格配置接口", False, str(e)[:50])


# ============================================================
# 主流程
# ============================================================
def main():
    print("=" * 60)
    print("  YHLZ 2.0 综合测试")
    print("  范围: 端口通信 | 模型链路 | 全部核心功能")
    print("=" * 60)
    
    start = time.time()
    
    # 快速预检
    try:
        r = requests.get(f"{BASE}/health", timeout=5)
    except:
        print("\n❌ 后端未启动，请先运行: python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000")
        sys.exit(1)
    
    # 顺序执行测试（避免相互干扰）
    test_1_health()
    test_2_chat_tts_chain()
    test_6_asr_reset()
    test_3_websocket()
    test_4_live2d()
    test_5_port_comms()
    
    # 汇总
    elapsed = time.time() - start
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    
    print(f"\n{'='*60}")
    print(f"  测试汇总: {passed}/{len(results)} 通过, {failed} 失败")
    print(f"  耗时: {elapsed:.1f}s")
    print(f"{'='*60}")
    
    if failed > 0:
        print("\n  失败项:")
        for name, ok, detail in results:
            if not ok:
                print(f"    ❌ {name}: {detail}")
    
    if passed == len(results):
        print("\n  🎉 所有测试通过！")
    
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())