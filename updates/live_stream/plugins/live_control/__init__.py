from backend.plugin_sdk import NekoPluginBase, neko_plugin, plugin_entry, Ok, Err
import asyncio
import logging

logger = logging.getLogger(__name__)


@neko_plugin
class LiveControlPlugin(NekoPluginBase):

    def __init__(self):
        super().__init__()
        self.live_manager = None
        self.bilibili_plugin = None
        self.vtube_plugin = None
        self._stats_cache = {}

    def set_live_manager(self, live_manager):
        self.live_manager = live_manager

    def set_plugins(self, bilibili_plugin, vtube_plugin):
        self.bilibili_plugin = bilibili_plugin
        self.vtube_plugin = vtube_plugin

    @plugin_entry(
        id="live_start",
        name="开始直播",
        description="启动B站直播，连接弹幕和虚拟形象",
        metadata={"category": "live"},
        parameters={
            "room_id": {"type": "int", "description": "直播间ID"},
            "sessdata": {"type": "str", "description": "B站SESSDATA"},
            "bili_jct": {"type": "str", "description": "B站bili_jct"},
            "buvid3": {"type": "str", "description": "B站buvid3"}
        }
    )
    async def start_live(self, room_id: int = 0, sessdata: str = "", bili_jct: str = "", buvid3: str = "", **_):
        if not self.live_manager:
            return Err("直播管理器未初始化")
        
        cookies = {}
        if sessdata:
            cookies['sessdata'] = sessdata
        if bili_jct:
            cookies['bili_jct'] = bili_jct
        if buvid3:
            cookies['buvid3'] = buvid3
        
        result = await self.live_manager.start_stream(room_id, cookies)
        return Ok(result) if 'success' in result else Err(result.get('error', '未知错误'))

    @plugin_entry(
        id="live_end",
        name="结束直播",
        description="结束当前直播，保存直播记录",
        metadata={"category": "live"},
        parameters={}
    )
    async def end_live(self, **_):
        if not self.live_manager:
            return Err("直播管理器未初始化")
        
        result = await self.live_manager.end_stream()
        return Ok(result) if 'success' in result else Err(result.get('error', '未知错误'))

    @plugin_entry(
        id="live_break",
        name="休息",
        description="进入休息时间，恢复能量",
        metadata={"category": "live"},
        parameters={}
    )
    async def take_break(self, **_):
        if not self.live_manager:
            return Err("直播管理器未初始化")
        
        result = await self.live_manager.take_break()
        return Ok(result) if 'success' in result else Err(result.get('error', '未知错误'))

    @plugin_entry(
        id="live_resume",
        name="恢复直播",
        description="从休息恢复到直播状态",
        metadata={"category": "live"},
        parameters={}
    )
    async def resume_live(self, **_):
        if not self.live_manager:
            return Err("直播管理器未初始化")
        
        result = await self.live_manager.resume_stream()
        return Ok(result) if 'success' in result else Err(result.get('error', '未知错误'))

    @plugin_entry(
        id="live_send",
        name="发送消息",
        description="在直播间发送消息",
        metadata={"category": "live"},
        parameters={"content": {"type": "str", "description": "消息内容"}}
    )
    async def send_message(self, content: str = "", **_):
        if not self.live_manager:
            return Err("直播管理器未初始化")
        
        result = await self.live_manager.send_message(content)
        return Ok(result) if 'success' in result else Err(result.get('error', '未知错误'))

    @plugin_entry(
        id="live_get_status",
        name="获取状态",
        description="获取当前直播状态",
        metadata={"category": "live"},
        parameters={}
    )
    def get_status(self, **_):
        if not self.live_manager:
            return Err("直播管理器未初始化")
        
        return Ok({"result": self.live_manager.get_status()})

    @plugin_entry(
        id="live_get_stats",
        name="获取统计",
        description="获取当前直播统计数据",
        metadata={"category": "live"},
        parameters={}
    )
    def get_stats(self, **_):
        if not self.live_manager:
            return Err("直播管理器未初始化")
        
        return Ok({"result": self.live_manager.get_stats()})

    @plugin_entry(
        id="live_set_expression",
        name="设置表情",
        description="设置虚拟形象表情",
        metadata={"category": "live"},
        parameters={"expression": {"type": "str", "description": "表情名称"}}
    )
    async def set_expression(self, expression: str = "neutral", **_):
        if not self.live_manager:
            return Err("直播管理器未初始化")
        
        result = await self.live_manager.set_expression(expression)
        return Ok(result) if 'success' in result else Err(result.get('error', '未知错误'))

    @plugin_entry(
        id="live_config",
        name="配置直播",
        description="配置直播参数",
        metadata={"category": "live"},
        parameters={
            "cold_threshold": {"type": "int", "description": "冷场检测阈值(秒)"},
            "topic_interval": {"type": "int", "description": "话题生成间隔(秒)"},
            "break_interval": {"type": "int", "description": "自动休息间隔(秒)"},
            "response_delay": {"type": "int", "description": "回复延迟(秒)"}
        }
    )
    def config_live(self, cold_threshold: int = 30, topic_interval: int = 300, 
                    break_interval: int = 1800, response_delay: int = 2, **_):
        if not self.live_manager:
            return Err("直播管理器未初始化")
        
        self.live_manager._cold_detection_threshold = cold_threshold
        self.live_manager._topic_interval = topic_interval
        self.live_manager._break_interval = break_interval
        self.live_manager._response_delay = response_delay
        
        return Ok({"result": "配置已更新"})