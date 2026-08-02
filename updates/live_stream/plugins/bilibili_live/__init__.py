from backend.plugin_sdk import NekoPluginBase, neko_plugin, plugin_entry, Ok, Err
import asyncio
import json
import logging
import time
from typing import Dict, Optional, Set

from updates.live_stream.backend.events import create_event
from updates.live_stream.backend.models import LiveSettings
from updates.live_stream.backend.tts_service import enqueue_text, priority_from_event_type

logger = logging.getLogger(__name__)


@neko_plugin
class BilibiliLivePlugin(NekoPluginBase):

    def __init__(self):
        super().__init__()
        self.room_id = 0
        self.connected = False
        self.danmaku_history = []
        self.gift_history = []
        self.websocket = None
        self._running = False
        self._danmaku_callback = None
        self._gift_callback = None
        self._event_callback = None
        self._settings = LiveSettings()

    @plugin_entry(
        id="bilibili_connect",
        name="连接B站直播间",
        description="连接到指定的B站直播间，开始监听弹幕和礼物",
        metadata={"category": "live"},
        parameters={
            "room_id": {"type": "int", "description": "直播间ID"},
            "sessdata": {"type": "str", "description": "B站SESSDATA Cookie"},
            "bili_jct": {"type": "str", "description": "B站bili_jct Cookie"},
            "buvid3": {"type": "str", "description": "B站buvid3 Cookie"}
        }
    )
    async def connect_room(self, room_id: int = 0, sessdata: str = "", bili_jct: str = "", buvid3: str = "", **_):
        if not room_id:
            return Err("请提供直播间ID")
        
        self.room_id = room_id
        self.cookies = {
            "SESSDATA": sessdata,
            "bili_jct": bili_jct,
            "buvid3": buvid3
        }
        
        try:
            await self._connect_websocket()
            self.connected = True
            self._running = True
            asyncio.create_task(self._receive_loop())
            asyncio.create_task(self._heartbeat_loop())
            return Ok({"result": f"成功连接到直播间 {room_id}"})
        except Exception as e:
            return Err(f"连接失败: {str(e)}")

    @plugin_entry(
        id="bilibili_send_danmaku",
        name="发送B站弹幕",
        description="在直播间发送弹幕消息",
        metadata={"category": "live"},
        parameters={"content": {"type": "str", "description": "弹幕内容"}}
    )
    async def send_danmaku(self, content: str = "", **_):
        if not content:
            return Err("弹幕内容不能为空")
        if not self.connected:
            return Err("请先连接直播间")
        
        try:
            await self._send_danmaku(content)
            return Ok({"result": f"弹幕发送成功: {content}"})
        except Exception as e:
            return Err(f"发送失败: {str(e)}")

    @plugin_entry(
        id="bilibili_get_danmaku",
        name="获取弹幕历史",
        description="获取最近的弹幕记录",
        metadata={"category": "live"},
        parameters={"limit": {"type": "int", "description": "返回条数，默认10"}}
    )
    def get_danmaku_history(self, limit: int = 10, **_):
        return Ok({"result": self.danmaku_history[-limit:]})

    @plugin_entry(
        id="bilibili_get_gifts",
        name="获取礼物历史",
        description="获取最近的礼物记录",
        metadata={"category": "live"},
        parameters={"limit": {"type": "int", "description": "返回条数，默认10"}}
    )
    def get_gift_history(self, limit: int = 10, **_):
        return Ok({"result": self.gift_history[-limit:]})

    @plugin_entry(
        id="bilibili_disconnect",
        name="断开直播间连接",
        description="断开与B站直播间的连接",
        metadata={"category": "live"},
        parameters={}
    )
    async def disconnect(self, **_):
        self._running = False
        self.connected = False
        if self.websocket:
            try:
                await self.websocket.close()
            except:
                pass
        return Ok({"result": "已断开连接"})

    @plugin_entry(
        id="bilibili_set_settings",
        name="设置直播参数",
        description="设置直播相关参数，如消息类型开关、模板等",
        metadata={"category": "live"},
        parameters={
            "enable_danmaku": {"type": "bool", "description": "启用弹幕"},
            "enable_gift": {"type": "bool", "description": "启用礼物播报"},
            "enable_super_chat": {"type": "bool", "description": "启用SC播报"},
            "min_price_yuan": {"type": "float", "description": "最低播报价格"},
            "template_danmaku": {"type": "str", "description": "弹幕模板"},
            "template_gift": {"type": "str", "description": "礼物模板"},
            "tts_enabled": {"type": "bool", "description": "启用TTS"},
            "tts_volume": {"type": "float", "description": "TTS音量"},
            "gradio_server_url": {"type": "str", "description": "GPT-SoVITS地址"}
        }
    )
    def set_settings(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, value)
        
        from updates.live_stream.backend.tts_service import init as tts_init
        tts_init(self._settings)
        
        return Ok({"result": "设置已更新"})

    async def _connect_websocket(self):
        try:
            import websockets
            self.websocket = await websockets.connect(
                "wss://broadcastlv.chat.bilibili.com/sub"
            )
            auth_data = json.dumps({
                "roomid": self.room_id,
                "uid": 0,
                "protover": 2,
                "platform": "web",
                "clientver": "1.6.3"
            })
            await self.websocket.send(self._encode_packet(auth_data, 7))
        except ImportError:
            raise RuntimeError("请安装 websockets 库: pip install websockets")

    def _encode_packet(self, data, op):
        body = data.encode('utf-8')
        packet_len = 16 + len(body)
        header = [
            (packet_len >> 24) & 0xFF, (packet_len >> 16) & 0xFF,
            (packet_len >> 8) & 0xFF, packet_len & 0xFF,
            0x00, 0x10,
            0x00, 0x01,
            (op >> 24) & 0xFF, (op >> 16) & 0xFF,
            (op >> 8) & 0xFF, op & 0xFF,
            0x00, 0x00, 0x00, 0x01
        ]
        return bytes(header) + body

    async def _heartbeat_loop(self):
        while self._running:
            try:
                await self.websocket.send(self._encode_packet("", 2))
            except:
                break
            await asyncio.sleep(30)

    async def _receive_loop(self):
        while self._running and self.websocket:
            try:
                message = await self.websocket.recv()
                await self._process_message(message)
            except Exception:
                break

    async def _process_message(self, message):
        try:
            import zlib
            buffer = bytearray(message)
            packet_len = int.from_bytes(buffer[0:4], byteorder='big')
            header_len = int.from_bytes(buffer[4:6], byteorder='big')
            ver = int.from_bytes(buffer[6:8], byteorder='big')
            op = int.from_bytes(buffer[8:12], byteorder='big')
            body = buffer[header_len:packet_len]

            if op == 5:
                if ver == 2:
                    body = zlib.decompress(body)
                
                json_data = json.loads(body.decode('utf-8'))
                
                if isinstance(json_data, list):
                    json_data = json_data[0]
                
                live_event = create_event(json_data)
                payload = live_event.to_payload(self._settings)
                
                logger.info(f"Event: {live_event.event_type} - Allowed: {bool(payload)}")
                
                if payload:
                    tts_key = f"{int(time.time() * 1000)}-{id(payload)}"
                    payload["tts_key"] = tts_key
                    
                    if self._event_callback:
                        await self._event_callback(payload)
                    
                    try:
                        pr = priority_from_event_type(live_event.event_type)
                        enqueue_text(payload.get("text", ""), pr, key=tts_key, room_id=self.room_id)
                    except Exception:
                        pass

                cmd = json_data.get("cmd", "")
                
                if cmd == "DANMU_MSG":
                    username = json_data["info"][2][1]
                    content = json_data["info"][1]
                    danmaku = {"user": username, "content": content, "time": json_data["info"][0][4]}
                    self.danmaku_history.append(danmaku)
                    if len(self.danmaku_history) > 100:
                        self.danmaku_history = self.danmaku_history[-100:]
                    if self._danmaku_callback:
                        await self._danmaku_callback(danmaku)
                
                elif cmd == "SEND_GIFT":
                    data = json_data.get("data", {})
                    username = data.get("uname", "")
                    gift_name = data.get("giftName", "")
                    num = data.get("num", 1)
                    gift = {"user": username, "gift": gift_name, "num": num}
                    self.gift_history.append(gift)
                    if len(self.gift_history) > 50:
                        self.gift_history = self.gift_history[-50:]
                    if self._gift_callback:
                        await self._gift_callback(gift)

            elif op == 3:
                pass
            elif op == 8:
                logger.info("B站直播间连接成功")

        except Exception as e:
            logger.error(f"消息处理失败: {e}")

    async def _send_danmaku(self, content):
        try:
            import requests
            url = "https://api.live.bilibili.com/msg/send"
            params = {
                "roomid": self.room_id,
                "msg": content,
                "bili_jct": self.cookies.get("bili_jct", "")
            }
            headers = {
                "Cookie": f"SESSDATA={self.cookies.get('SESSDATA', '')}; bili_jct={self.cookies.get('bili_jct', '')}; buvid3={self.cookies.get('buvid3', '')}"
            }
            response = requests.post(url, data=params, headers=headers)
            if response.json().get("code") != 0:
                raise Exception(response.json().get("message", "发送失败"))
        except ImportError:
            raise RuntimeError("请安装 requests 库")

    def set_danmaku_callback(self, callback):
        self._danmaku_callback = callback

    def set_gift_callback(self, callback):
        self._gift_callback = callback

    def set_event_callback(self, callback):
        self._event_callback = callback

    def get_settings(self):
        return self._settings