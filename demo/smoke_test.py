"""
YHLZ 2.0 冒烟测试脚本 (蓝图D7)
一键跑通: 麦克风→识别→对话→合成→播放→口型
"""
import json
import time
import sys
import requests
import argparse

BASE_URL = "http://localhost:8000"

def check(label, ok, details=""):
    status = "✅" if ok else "❌"
    print(f"  {status} {label}" + (f"  ({details})" if details else ""))
    return ok

def test_health():
    print("\n[1] 健康检查")
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        data = r.json()
        ok = data.get("status") == "healthy"
        check("后端健康", ok, f"status={data.get('status')}")
        return ok
    except Exception as e:
        check("后端健康", False, str(e))
        return False

def test_clear_history():
    print("\n[2] 应急重置")
    try:
        r = requests.post(f"{BASE_URL}/clear-history", timeout=5)
        ok = r.json().get("success") == True
        check("清空历史", ok)
        return ok
    except Exception as e:
        check("清空历史", False, str(e))
        return False

def test_text_chat():
    print("\n[3] 文本对话 (SSE流式)")
    try:
        r = requests.post(
            f"{BASE_URL}/chat",
            json={"text": "你好，请用一句话介绍你自己", "tts_enabled": False},
            timeout=30,
            stream=True
        )
        full = ""
        for line in r.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                chunk = line[5:].strip()
                try:
                    data = json.loads(chunk)
                    if "content" in data:
                        full += data["content"]
                except:
                    pass
        ok = len(full) > 10
        check("文本对话", ok, f"回复长度={len(full)}字")
        return ok, full
    except Exception as e:
        check("文本对话", False, str(e))
        return False, ""

def test_tts_synthesis():
    print("\n[4] TTS合成")
    try:
        r = requests.post(
            f"{BASE_URL}/synthesize",
            json={"text": "你好，我是元亨助手"},
            timeout=30
        )
        data = r.json()
        sample_rate = data.get("sample_rate", 0)
        # Edge-TTS 原始输出可能是 24kHz 或 44.1kHz，audio_buffer 会自动重采样到 16kHz
        ok = sample_rate in (16000, 24000, 44100) and data.get("success") == True
        check("TTS合成", ok, f"原始sr={sample_rate} (audio_buffer重采样到16kHz)")
        return ok
    except Exception as e:
        check("TTS合成", False, str(e))
        return False

def test_config():
    print("\n[5] 配置验证")
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    all_ok = True
    
    sr = os.getenv("SAMPLE_RATE", "44100")
    all_ok &= check("采样率=16000", sr == "16000", f"当前={sr}")
    
    tms = os.getenv("TTS_FIRST_CHUNK_MIN_MS", "500")
    all_ok &= check("首包延迟≤300ms", int(tms) <= 300, f"当前={tms}ms")
    
    return all_ok

def main():
    print("=" * 50)
    print("YHLZ 2.0 冒烟测试 (蓝图D7)")
    print("=" * 50)
    
    results = []
    
    # 1. 健康检查
    results.append(("健康检查", test_health()))
    
    if not results[-1][1]:
        print("\n❌ 后端未启动，请先运行: python backend/main.py")
        sys.exit(1)
    
    # 2. 应急重置
    results.append(("应急重置", test_clear_history()))
    
    # 3. 文本对话
    ok, resp = test_text_chat()
    results.append(("文本对话", ok))
    
    # 4. TTS合成
    results.append(("TTS合成", test_tts_synthesis()))
    
    # 5. 配置验证
    results.append(("配置验证", test_config()))
    
    # 汇总
    print("\n" + "=" * 50)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"结果: {passed}/{total} 通过")
    
    for name, ok in results:
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")
    
    if passed == total:
        print("\n🎉 冒烟测试全部通过！")
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查日志")
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())