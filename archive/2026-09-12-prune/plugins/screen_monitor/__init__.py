from backend.plugin_sdk import NekoPluginBase, neko_plugin, plugin_entry, lifecycle, timer_interval, Ok, Err
from backend.vision_engine import vision_engine
from backend.llm_engine import llm_engine
from datetime import datetime, timedelta
import asyncio
import base64


@neko_plugin
class ScreenMonitorPlugin(NekoPluginBase):

    def __init__(self, ctx):
        super().__init__(ctx)
        self._last_capture_time = None
        self._last_analysis_time = None
        self._last_chat_time = None
        self._analysis_results = []
        self._capture_interval = 30
        self._analysis_interval = 120
        self._auto_chat_enabled = True
        self._chat_cooldown = 300
        self._is_monitoring = False
        self._load_config()

    def _load_config(self):
        try:
            self._capture_interval = int(self.metadata.get("config", {}).get("screen_monitor", {}).get("capture_interval", 30))
            self._analysis_interval = int(self.metadata.get("config", {}).get("screen_monitor", {}).get("analysis_interval", 120))
            self._auto_chat_enabled = bool(self.metadata.get("config", {}).get("screen_monitor", {}).get("auto_chat_enabled", True))
            self._chat_cooldown = int(self.metadata.get("config", {}).get("screen_monitor", {}).get("chat_cooldown", 300))
            self.logger.info(f"屏幕监控配置: 捕获间隔={self._capture_interval}s, 分析间隔={self._analysis_interval}s")
        except Exception as e:
            self.logger.warning(f"加载配置失败，使用默认值: {e}")

    @lifecycle(id="startup")
    def on_startup(self, **_):
        self.logger.info("屏幕监控插件启动")
        return Ok({"status": "started"})

    @lifecycle(id="shutdown")
    def on_shutdown(self, **_):
        self._is_monitoring = False
        self.logger.info("屏幕监控插件停止")
        return Ok({"status": "stopped"})

    @timer_interval(id="screen_capture", seconds=30, name="屏幕捕获")
    def capture_screen(self, **_):
        if not self._is_monitoring:
            return Ok(None)

        try:
            if not vision_engine.get_state().get("is_running", False):
                vision_engine.start_screen_capture(1)

            frame = vision_engine.capture_frame()
            if frame is not None:
                base64_image = vision_engine.frame_to_base64(frame)
                self._last_capture_time = datetime.now()
                self.logger.debug(f"屏幕捕获成功，图像大小: {len(base64_image)}")
                return Ok({"captured": True, "timestamp": self._last_capture_time.isoformat()})
            else:
                return Ok({"captured": False, "message": "无法捕获帧"})
        except Exception as e:
            self.logger.error(f"屏幕捕获失败: {e}")
            return Err(str(e))

    @timer_interval(id="screen_analysis", seconds=120, name="屏幕分析")
    async def analyze_screen(self, **_):
        if not self._is_monitoring or not self._auto_chat_enabled:
            return Ok(None)

        try:
            if not vision_engine.get_state().get("is_running", False):
                vision_engine.start_screen_capture(1)

            frame = vision_engine.capture_frame()
            if frame is None:
                return Ok({"analyzed": False, "message": "无法捕获帧"})

            base64_image = vision_engine.frame_to_base64(frame)

            prompt = "请分析这张屏幕截图，描述当前屏幕上显示的内容，包括窗口标题、应用程序、文档内容等。如果有网页内容，请总结主要内容。"
            analysis = await llm_engine.generate_with_image(prompt, base64_image)

            self._last_analysis_time = datetime.now()
            self._analysis_results.append({
                "timestamp": self._last_analysis_time.isoformat(),
                "analysis": analysis[:500]
            })

            if len(self._analysis_results) > 20:
                self._analysis_results = self._analysis_results[-20:]

            self.logger.info(f"屏幕分析完成: {analysis[:100]}...")

            await self._check_auto_chat(analysis)

            return Ok({"analyzed": True, "summary": analysis[:200]})

        except Exception as e:
            self.logger.error(f"屏幕分析失败: {e}")
            return Err(str(e))

    async def _check_auto_chat(self, analysis):
        if self._last_chat_time is None:
            self._last_chat_time = datetime.now()
            return

        now = datetime.now()
        time_since_last_chat = (now - self._last_chat_time).total_seconds()

        if time_since_last_chat < self._chat_cooldown:
            return

        if "视频" in analysis or "游戏" in analysis or "娱乐" in analysis:
            message = f"看起来你正在{'看视频' if '视频' in analysis else '玩游戏'}，需要我帮忙吗？"
            await self.push_message(message_type="text", content=message, priority=5)
            self._last_chat_time = now
            self.logger.info(f"主动搭话: {message}")

        elif "文档" in analysis or "文档编辑" in analysis or "表格" in analysis:
            message = f"看到你在处理文档，需要我帮你整理思路或者总结内容吗？"
            await self.push_message(message_type="text", content=message, priority=5)
            self._last_chat_time = now
            self.logger.info(f"主动搭话: {message}")

        elif "网页" in analysis or "浏览器" in analysis:
            message = f"你正在浏览网页，看到了什么有趣的内容吗？"
            await self.push_message(message_type="text", content=message, priority=5)
            self._last_chat_time = now
            self.logger.info(f"主动搭话: {message}")

    @plugin_entry(
        id="start_monitor",
        name="启动监控",
        description="启动屏幕监控和分析",
        parameters={}
    )
    def start_monitor(self, **_):
        self._is_monitoring = True
        if not vision_engine.get_state().get("is_running", False):
            vision_engine.start_screen_capture(1)
        self.start_timers()
        self.logger.info("屏幕监控已启动")
        return Ok({"status": "monitoring"})

    @plugin_entry(
        id="stop_monitor",
        name="停止监控",
        description="停止屏幕监控和分析",
        parameters={}
    )
    def stop_monitor(self, **_):
        self._is_monitoring = False
        vision_engine.stop_capture()
        self.stop_timers()
        self.logger.info("屏幕监控已停止")
        return Ok({"status": "stopped"})

    @plugin_entry(
        id="capture_now",
        name="立即捕获",
        description="立即捕获一帧屏幕",
        parameters={}
    )
    def capture_now(self, **_):
        try:
            if not vision_engine.get_state().get("is_running", False):
                vision_engine.start_screen_capture(1)

            frame = vision_engine.capture_frame()
            if frame is not None:
                base64_image = vision_engine.frame_to_base64(frame)
                return Ok({
                    "success": True,
                    "image": base64_image,
                    "width": frame.shape[1],
                    "height": frame.shape[0],
                    "timestamp": datetime.now().isoformat()
                })
            else:
                return Err("无法捕获帧")
        except Exception as e:
            return Err(str(e))

    @plugin_entry(
        id="analyze_now",
        name="立即分析",
        description="立即捕获并分析屏幕内容",
        parameters={"prompt": {"type": "str", "description": "分析提示词，默认为\"请描述屏幕上的内容\""}}
    )
    async def analyze_now(self, prompt: str = "请描述屏幕上的内容", **_):
        try:
            if not vision_engine.get_state().get("is_running", False):
                vision_engine.start_screen_capture(1)

            frame = vision_engine.capture_frame()
            if frame is None:
                return Err("无法捕获帧")

            base64_image = vision_engine.frame_to_base64(frame)
            analysis = await llm_engine.generate_with_image(prompt, base64_image)

            return Ok({
                "success": True,
                "analysis": analysis,
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            return Err(str(e))

    @plugin_entry(
        id="get_status",
        name="获取状态",
        description="获取屏幕监控状态",
        parameters={}
    )
    def get_status(self, **_):
        return Ok({
            "is_monitoring": self._is_monitoring,
            "last_capture_time": self._last_capture_time.isoformat() if self._last_capture_time else None,
            "last_analysis_time": self._last_analysis_time.isoformat() if self._last_analysis_time else None,
            "last_chat_time": self._last_chat_time.isoformat() if self._last_chat_time else None,
            "analysis_results_count": len(self._analysis_results),
            "capture_interval": self._capture_interval,
            "analysis_interval": self._analysis_interval,
            "auto_chat_enabled": self._auto_chat_enabled,
            "vision_running": vision_engine.get_state().get("is_running", False)
        })

    @plugin_entry(
        id="get_analysis_history",
        name="获取分析历史",
        description="获取最近的屏幕分析历史",
        parameters={"limit": {"type": "int", "description": "返回记录数量，默认10条"}}
    )
    def get_analysis_history(self, limit: int = 10, **_):
        return Ok({"history": self._analysis_results[-limit:]})

    @plugin_entry(
        id="set_config",
        name="设置配置",
        description="设置屏幕监控配置",
        parameters={
            "capture_interval": {"type": "int", "description": "捕获间隔（秒）"},
            "analysis_interval": {"type": "int", "description": "分析间隔（秒）"},
            "auto_chat_enabled": {"type": "bool", "description": "是否启用自动搭话"},
            "chat_cooldown": {"type": "int", "description": "搭话冷却时间（秒）"}
        }
    )
    def set_config(self, capture_interval: int = None, analysis_interval: int = None, 
                   auto_chat_enabled: bool = None, chat_cooldown: int = None, **_):
        if capture_interval:
            self._capture_interval = capture_interval
        if analysis_interval:
            self._analysis_interval = analysis_interval
        if auto_chat_enabled is not None:
            self._auto_chat_enabled = auto_chat_enabled
        if chat_cooldown:
            self._chat_cooldown = chat_cooldown

        return Ok({
            "capture_interval": self._capture_interval,
            "analysis_interval": self._analysis_interval,
            "auto_chat_enabled": self._auto_chat_enabled,
            "chat_cooldown": self._chat_cooldown
        })