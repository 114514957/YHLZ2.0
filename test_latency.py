"""
YHLZ 2.0 延迟测试 — 端到端链路 + 模型间运动延迟
路径: 输入文本 → LLM推理 → TTS合成 → 音频就绪
"""
import requests, json, time, sys

BASE = "http://127.0.0.1:8000"

def sep(title):
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}")

def ms(t):
    return f"{t*1000:.0f}ms"

# ============================================================
# 预检
# ============================================================
try:
    r = requests.get(f"{BASE}/health", timeout=5)
    assert r.status_code == 200
except:
    print("❌ 后端未启动")
    sys.exit(1)

# ============================================================
# 测试文本
# ============================================================
test_texts = [
    "你好，请介绍一下你自己",           # 短句
    "请用三句话总结一下人工智能的发展历史",  # 中等
    "请用一句话回复：今天天气怎么样？",    # 极短
]

# ============================================================
# 测试1: LLM 延迟 (TTFT + 完整生成时间)
# ============================================================
sep("测试1: LLM 推理延迟 (首Token + 总Token)")

llm_results = []
for text in test_texts:
    print(f"\n  输入: {text}")
    
    t_start = time.time()
    t_first_token = None
    total_chars = 0
    chunk_count = 0
    chunk_times = []
    
    r = requests.post(f"{BASE}/chat", json={
        "text": text,
        "tts_enabled": False
    }, timeout=60, stream=True)
    
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            now = time.time()
            if t_first_token is None:
                t_first_token = now
            try:
                chunk = json.loads(line[5:].strip())
                if "content" in chunk:
                    total_chars += len(chunk["content"])
                    chunk_count += 1
                    chunk_times.append(now)
            except:
                pass
    
    t_end = time.time()
    
    # 计算指标
    ttft = (t_first_token - t_start) if t_first_token else 0
    total_time = t_end - t_start
    gen_time = (t_end - t_first_token) if t_first_token else 0
    chars_per_sec = total_chars / gen_time if gen_time > 0 else 0
    
    # 计算chunk间隔
    if len(chunk_times) > 1:
        intervals = [chunk_times[i] - chunk_times[i-1] for i in range(1, len(chunk_times))]
        avg_interval = sum(intervals) / len(intervals) * 1000
        max_interval = max(intervals) * 1000
    else:
        avg_interval = max_interval = 0
    
    print(f"  TTFT(首Token):     {ms(ttft)}")
    print(f"  总生成时间:         {ms(total_time)}")
    print(f"  纯生成时间:         {ms(gen_time)}")
    print(f"  输出字符数:         {total_chars}")
    print(f"  生成速度:           {chars_per_sec:.1f} 字/秒")
    print(f"  Chunk数:            {chunk_count}")
    print(f"  平均Chunk间隔:      {avg_interval:.0f}ms")
    print(f"  最大Chunk间隔:      {max_interval:.0f}ms")
    
    llm_results.append({
        "text": text[:20],
        "ttft_ms": ttft * 1000,
        "total_ms": total_time * 1000,
        "gen_ms": gen_time * 1000,
        "chars": total_chars,
        "speed": chars_per_sec,
        "chunks": chunk_count,
        "avg_interval_ms": avg_interval,
        "max_interval_ms": max_interval
    })

# ============================================================
# 测试2: TTS 合成延迟
# ============================================================
sep("测试2: TTS 合成延迟")

tts_texts = {
    "短(10字)": "你好我是元亨助手",
    "中(20字)": "你好我是元亨助手很高兴认识你",
    "长(40字)": "你好我是元亨助手很高兴认识你，请问有什么可以帮助你的吗？",
}

for label, text in tts_texts.items():
    t0 = time.time()
    r = requests.post(f"{BASE}/synthesize", json={
        "text": text,
        "voice": "zh-CN-XiaoxiaoNeural"
    }, timeout=30)
    t1 = time.time()
    
    data = r.json()
    audio_len = len(data.get("audio", ""))
    sr = data.get("sample_rate", 0)
    
    print(f"\n  {label}: {text}")
    print(f"  合成耗时:           {ms(t1 - t0)}")
    print(f"  Base64输出:         {audio_len} 字节")
    print(f"  采样率:             {sr} Hz")

# ============================================================
# 测试3: 端到端链路 (LLM → TTS)
# ============================================================
sep("测试3: 端到端链路 (输入第一个字 → 最后一个TTS字节)")

for text in test_texts[:2]:
    print(f"\n  输入: {text}")
    
    # 阶段1: LLM
    t_llm_start = time.time()
    t_llm_first = None
    full_response = ""
    
    r = requests.post(f"{BASE}/chat", json={
        "text": text,
        "tts_enabled": False
    }, timeout=60, stream=True)
    
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            if t_llm_first is None:
                t_llm_first = time.time()
            try:
                chunk = json.loads(line[5:].strip())
                if "content" in chunk:
                    full_response += chunk["content"]
            except:
                pass
    
    t_llm_end = time.time()
    
    # 阶段2: TTS
    t_tts_start = time.time()
    r2 = requests.post(f"{BASE}/synthesize", json={
        "text": full_response,
        "voice": "zh-CN-XiaoxiaoNeural"
    }, timeout=30)
    t_tts_end = time.time()
    
    t_total = t_tts_end - t_llm_start
    
    print(f"  LLM首Token:        {ms(t_llm_first - t_llm_start) if t_llm_first else 'N/A'}")
    print(f"  LLM全部完成:        {ms(t_llm_end - t_llm_start)}")
    print(f"  生成文本:           {full_response[:50]}...")
    print(f"  TTS合成:            {ms(t_tts_end - t_tts_start)}")
    print(f"  ─────────────────────────────")
    print(f"  端到端总延迟:        {ms(t_total)}")
    print(f"  其中LLM占比:         {((t_llm_end - t_llm_start) / t_total * 100):.0f}%")
    print(f"  其中TTS占比:         {((t_tts_end - t_tts_start) / t_total * 100):.0f}%")

# ============================================================
# 测试4: 后端API纯响应延迟 (无模型)
# ============================================================
sep("测试4: 后端纯API延迟 (无模型推理)")

n = 10
times = []
for _ in range(n):
    t0 = time.time()
    requests.get(f"{BASE}/health", timeout=5)
    times.append((time.time() - t0) * 1000)

avg = sum(times) / n
print(f"  /health 请求 ({n}次):")
print(f"  平均:               {avg:.1f}ms")
print(f"  最小:               {min(times):.1f}ms")
print(f"  最大:               {max(times):.1f}ms")

# 缓存统计
t0 = time.time()
requests.get(f"{BASE}/cache-stats", timeout=5)
tcs = (time.time() - t0) * 1000
print(f"  /cache-stats:        {tcs:.1f}ms")

# 模块状态
t0 = time.time()
requests.get(f"{BASE}/modules/status", timeout=5)
tms = (time.time() - t0) * 1000
print(f"  /modules/status:     {tms:.1f}ms")

# ============================================================
# 汇总
# ============================================================
sep("延迟测试汇总")

if llm_results:
    avg_ttft = sum(r["ttft_ms"] for r in llm_results) / len(llm_results)
    avg_total = sum(r["total_ms"] for r in llm_results) / len(llm_results)
    avg_speed = sum(r["speed"] for r in llm_results) / len(llm_results)
    
    print(f"\n  LLM 平均指标 ({len(llm_results)} 次测试):")
    print(f"    TTFT(首Token):     {avg_ttft:.0f}ms")
    print(f"    总生成时间:         {avg_total:.0f}ms")
    print(f"    生成速度:           {avg_speed:.1f} 字/秒")
    print(f"    纯API延迟:          {avg:.1f}ms")

print(f"\n  延迟分解 (典型短句):")
print(f"    输入→首Token:       ~{avg_ttft:.0f}ms  (LLM首响应)")
print(f"    首Token→末Token:    ~{avg_total - avg_ttft:.0f}ms  (LLM流式生成)")
print(f"    末Token→TTS完成:    ~{avg_total:.0f}ms  (TTS合成)")
print(f"    ───────────────────────────────")
print(f"    端到端总计:         ~{avg_total * 2:.0f}ms  (LLM + TTS)")
print(f"    纯API开销:          {avg:.1f}ms  (网络+框架)")

print(f"\n{'='*55}")
print(f"  测试完成")
print(f"{'='*55}")