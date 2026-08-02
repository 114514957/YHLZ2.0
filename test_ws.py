"""测试 WebSocket /ws/avatar 端点"""
import websocket
import json
import time

print("=== 测试 WebSocket /ws/avatar ===")

try:
    ws = websocket.create_connection("ws://127.0.0.1:8000/ws/avatar", timeout=5)
    print("OK 连接成功")

    # 接收连接确认
    ws.settimeout(3)
    data = ws.recv()
    msg = json.loads(data)
    print(f"  收到: type={msg.get('type')}, version={msg.get('data', {}).get('version')}")

    # 发送心跳
    ws.send(json.dumps({"type": "ping", "ts": time.time()}))
    ws.settimeout(3)
    data = ws.recv()
    msg = json.loads(data)
    print(f"  心跳响应: type={msg.get('type')}")

    ws.close()
    print("OK WebSocket 测试通过")
except ImportError:
    print("FAIL websocket-client 未安装")
except Exception as e:
    print(f"FAIL WebSocket 连接失败: {e}")