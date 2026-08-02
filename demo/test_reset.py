"""测试应急重置"""
import requests, json

print("=== 测试 对话历史 ===")
r = requests.get("http://localhost:8000/cache-stats", timeout=5)
data = r.json()
ctx = data["context"]
print(f"Token数: {ctx['token_count']}")
print(f"历史消息数: {ctx['history_count']}")
print(f"接近限制: {ctx['near_limit']}")

print()
print("=== 测试 应急重置 ===")
r = requests.post("http://localhost:8000/clear-history", timeout=5)
print(f"清空结果: {r.json()}")
r = requests.get("http://localhost:8000/cache-stats", timeout=5)
data = r.json()
ctx = data["context"]
print(f"重置后Token数: {ctx['token_count']}")
print(f"重置后历史消息数: {ctx['history_count']}")

print()
print("=== 测试 ASR 状态 ===")
r = requests.get("http://localhost:8000/modules/status", timeout=5)
data = r.json()
for name, mod in data["modules"].items():
    status = mod["status"]
    icon = "OK" if status == "running" else ("..." if status == "loading" else "  ")
    print(f"  {icon} {name}: {status}")