from backend.plugin_sdk import NekoPluginBase, neko_plugin, plugin_entry, Ok, Err
import asyncio
import logging
import math
import time

logger = logging.getLogger(__name__)


class EasingType:
    LINEAR = 'linear'
    EASE_IN = 'easeIn'
    EASE_OUT = 'easeOut'
    EASE_BOTH = 'easeBoth'
    OVERSHOOT = 'overshoot'
    ZIP = 'zip'


class VTubeStudioPlugin(NekoPluginBase):

    def __init__(self):
        super().__init__()
        self.vts = None
        self.is_connected = False
        self.plugin_info = {
            "plugin_name": "YHLZ Virtual Assistant",
            "developer": "YHLZ Team",
            "authentication_token_path": "./config/vts_token.txt"
        }
        self._mouth_open_value = 0.0
        self._current_params = {}
        self._event_handlers = {}
        self._animation_tasks = []
        self._blink_task = None
        self._blink_interval = 3000
        self._auto_blink_enabled = True

    async def connect(self, **_):
        try:
            import pyvts
            self.vts = pyvts.vts(plugin_info=self.plugin_info)
            await self.vts.connect()
            await self.vts.request_authenticate_token()
            await self.vts.request_authenticate()
            self.is_connected = True
            
            await self._subscribe_events()
            
            if self._auto_blink_enabled:
                self._start_auto_blink()
            
            logger.info("VTube Studio连接成功")
            return Ok({"result": "VTube Studio连接成功"})
        except ImportError:
            return Err("请安装 pyvts 库: pip install pyvts")
        except Exception as e:
            return Err(f"连接失败: {str(e)}")

    async def disconnect(self, **_):
        self._stop_auto_blink()
        
        for task in self._animation_tasks:
            try:
                task.cancel()
            except:
                pass
        
        if self.vts:
            try:
                await self.vts.close()
            except:
                pass
        
        self.is_connected = False
        self.vts = None
        self._current_params = {}
        return Ok({"result": "已断开连接"})

    @plugin_entry(
        id="vts_set_expression",
        name="设置表情",
        description="设置虚拟形象的表情",
        metadata={"category": "avatar"},
        parameters={"expression": {"type": "str", "description": "表情名称"}}
    )
    async def set_expression(self, expression: str = "neutral", **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        
        expression_map = {
            "happy": "happy_expression",
            "sad": "sad_expression",
            "surprised": "surprised_expression",
            "neutral": "neutral_expression",
            "angry": "angry_expression",
            "shy": "shy_expression",
            "excited": "excited_expression",
            "sleepy": "sleepy_expression",
            "confused": "confused_expression",
            "laugh": "laugh_expression",
            "cry": "cry_expression"
        }
        
        hotkey_name = expression_map.get(expression, "neutral_expression")
        
        try:
            await self.vts.request(
                self.vts.vts_request.requestHotkeyTrigger(hotkey_name)
            )
            return Ok({"result": f"表情已设置为: {expression}"})
        except Exception as e:
            return Err(f"设置表情失败: {str(e)}")

    @plugin_entry(
        id="vts_set_mouth_open",
        name="设置嘴巴张开",
        description="设置虚拟形象嘴巴张开程度",
        metadata={"category": "avatar"},
        parameters={"value": {"type": "float", "description": "张开程度（0-1）"}}
    )
    async def set_mouth_open(self, value: float = 0.0, **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        
        value = max(0.0, min(1.0, value))
        self._mouth_open_value = value
        
        try:
            await self._inject_parameters([{"id": "MouthOpen", "value": value}])
            return Ok({"result": f"嘴巴张开程度已设置为: {value}"})
        except Exception as e:
            return Err(f"设置失败: {str(e)}")

    @plugin_entry(
        id="vts_set_vowel_params",
        name="设置元音参数",
        description="设置虚拟形象的元音参数（需要模型支持）",
        metadata={"category": "avatar"},
        parameters={
            "a": {"type": "float", "description": "元音a的权重（0-1）"},
            "e": {"type": "float", "description": "元音e的权重（0-1）"},
            "i": {"type": "float", "description": "元音i的权重（0-1）"},
            "o": {"type": "float", "description": "元音o的权重（0-1）"},
            "u": {"type": "float", "description": "元音u的权重（0-1）"}
        }
    )
    async def set_vowel_params(self, a: float = 0.0, e: float = 0.0, i: float = 0.0, o: float = 0.0, u: float = 0.0, **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        
        params = []
        if a > 0:
            params.append({"id": "MouthA", "value": min(1.0, a)})
        if e > 0:
            params.append({"id": "MouthE", "value": min(1.0, e)})
        if i > 0:
            params.append({"id": "MouthI", "value": min(1.0, i)})
        if o > 0:
            params.append({"id": "MouthO", "value": min(1.0, o)})
        if u > 0:
            params.append({"id": "MouthU", "value": min(1.0, u)})
        
        if not params:
            return Ok({"result": "无参数需要设置"})
        
        try:
            await self._inject_parameters(params)
            return Ok({"result": "元音参数已设置"})
        except Exception as e:
            return Err(f"设置失败: {str(e)}")

    @plugin_entry(
        id="vts_trigger_animation",
        name="触发动画",
        description="触发虚拟形象的指定动画",
        metadata={"category": "avatar"},
        parameters={"animation": {"type": "str", "description": "动画名称"}}
    )
    async def trigger_animation(self, animation: str = "", **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        if not animation:
            return Err("请提供动画名称")
        
        try:
            await self.vts.request(
                self.vts.vts_request.requestHotkeyTrigger(animation)
            )
            return Ok({"result": f"动画已触发: {animation}"})
        except Exception as e:
            return Err(f"触发失败: {str(e)}")

    @plugin_entry(
        id="vts_set_parameter",
        name="设置参数",
        description="设置Live2D模型的自定义参数",
        metadata={"category": "avatar"},
        parameters={
            "name": {"type": "str", "description": "参数名称"},
            "value": {"type": "float", "description": "参数值"}
        }
    )
    async def set_parameter(self, name: str = "", value: float = 0.0, **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        if not name:
            return Err("请提供参数名称")
        
        try:
            await self._inject_parameters([{"id": name, "value": value}])
            return Ok({"result": f"参数 {name} 已设置为: {value}"})
        except Exception as e:
            return Err(f"设置失败: {str(e)}")

    @plugin_entry(
        id="vts_set_parameter_with_easing",
        name="设置参数（带缓动）",
        description="使用缓动曲线设置参数，使动作更自然",
        metadata={"category": "avatar"},
        parameters={
            "name": {"type": "str", "description": "参数名称"},
            "value": {"type": "float", "description": "目标值"},
            "duration": {"type": "float", "description": "动画时长（秒）"},
            "easing": {"type": "str", "description": "缓动类型（linear/easeIn/easeOut/easeBoth/overshoot/zip）"}
        }
    )
    async def set_parameter_with_easing(self, name: str = "", value: float = 0.0, duration: float = 0.3, easing: str = "easeBoth", **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        if not name:
            return Err("请提供参数名称")
        
        start_value = self._current_params.get(name, 0.0)
        
        task = asyncio.create_task(
            self._animate_parameter(name, start_value, value, duration, easing)
        )
        self._animation_tasks.append(task)
        
        task.add_done_callback(lambda t: self._animation_tasks.remove(task))
        
        return Ok({"result": f"参数 {name} 正在动画中"})

    @plugin_entry(
        id="vts_set_multiple_params",
        name="设置多个参数",
        description="同时设置多个Live2D参数",
        metadata={"category": "avatar"},
        parameters={"params": {"type": "dict", "description": "参数字典，如 {\"MouthOpen\": 0.5, \"EyeBlink\": 0.0}"}}
    )
    async def set_multiple_params(self, params: dict = None, **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        if not params or not isinstance(params, dict):
            return Err("请提供有效的参数字典")
        
        param_list = [{"id": name, "value": value} for name, value in params.items()]
        
        try:
            await self._inject_parameters(param_list)
            return Ok({"result": f"已设置 {len(params)} 个参数"})
        except Exception as e:
            return Err(f"设置失败: {str(e)}")

    @plugin_entry(
        id="vts_get_models",
        name="获取模型列表",
        description="获取VTube Studio中可用的模型列表",
        metadata={"category": "avatar"},
        parameters={}
    )
    async def get_models(self, **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        
        try:
            response = await self.vts.request(
                self.vts.vts_request.requestModelList()
            )
            models = []
            if hasattr(response, 'data'):
                for model in response.data.models:
                    models.append({
                        "name": model.name,
                        "id": model.modelId,
                        "loaded": model.loaded
                    })
            return Ok({"result": models})
        except Exception as e:
            return Err(f"获取失败: {str(e)}")

    @plugin_entry(
        id="vts_load_model",
        name="加载模型",
        description="加载指定的Live2D模型",
        metadata={"category": "avatar"},
        parameters={"model_id": {"type": "str", "description": "模型ID"}}
    )
    async def load_model(self, model_id: str = "", **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        if not model_id:
            return Err("请提供模型ID")
        
        try:
            await self.vts.request(
                self.vts.vts_request.requestModelLoad(modelID=model_id)
            )
            await asyncio.sleep(1)
            await self._update_current_params()
            return Ok({"result": f"模型 {model_id} 加载成功"})
        except Exception as e:
            return Err(f"加载失败: {str(e)}")

    @plugin_entry(
        id="vts_set_position",
        name="设置位置",
        description="设置虚拟形象在场景中的位置",
        metadata={"category": "avatar"},
        parameters={
            "x": {"type": "float", "description": "X坐标"},
            "y": {"type": "float", "description": "Y坐标"},
            "scale": {"type": "float", "description": "缩放比例"}
        }
    )
    async def set_position(self, x: float = 0.0, y: float = 0.0, scale: float = 1.0, **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        
        try:
            await self.vts.request(
                self.vts.vts_request.requestModelMove(
                    positionX=x,
                    positionY=y,
                    scale=scale
                )
            )
            return Ok({"result": f"位置已设置为 ({x}, {y})，缩放: {scale}"})
        except Exception as e:
            return Err(f"设置失败: {str(e)}")

    @plugin_entry(
        id="vts_blink",
        name="眨眼",
        description="触发虚拟形象眨眼动作",
        metadata={"category": "avatar"},
        parameters={}
    )
    async def blink(self, **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        
        try:
            await self._inject_parameters([{"id": "EyeBlink", "value": 1.0}])
            await asyncio.sleep(0.1)
            await self._inject_parameters([{"id": "EyeBlink", "value": 0.0}])
            return Ok({"result": "眨眼动作已触发"})
        except Exception as e:
            return Err(f"触发失败: {str(e)}")

    @plugin_entry(
        id="vts_set_auto_blink",
        name="设置自动眨眼",
        description="开启或关闭自动眨眼",
        metadata={"category": "avatar"},
        parameters={
            "enabled": {"type": "bool", "description": "是否开启"},
            "interval": {"type": "int", "description": "眨眼间隔（毫秒）"}
        }
    )
    async def set_auto_blink(self, enabled: bool = True, interval: int = 3000, **_):
        self._auto_blink_enabled = enabled
        self._blink_interval = interval
        
        self._stop_auto_blink()
        
        if enabled and self.is_connected:
            self._start_auto_blink()
        
        return Ok({"result": f"自动眨眼已{'开启' if enabled else '关闭'}，间隔: {interval}ms"})

    @plugin_entry(
        id="vts_get_status",
        name="获取状态",
        description="获取VTube Studio连接状态",
        metadata={"category": "avatar"},
        parameters={}
    )
    def get_status(self, **_):
        return Ok({"result": {"connected": self.is_connected}})

    @plugin_entry(
        id="vts_get_parameters",
        name="获取参数",
        description="获取当前模型的参数列表",
        metadata={"category": "avatar"},
        parameters={}
    )
    async def get_parameters(self, **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        
        try:
            response = await self.vts.request(
                self.vts.vts_request.requestParameterList()
            )
            params = []
            if hasattr(response, 'data'):
                for param in response.data.parameters:
                    params.append({
                        "name": param.id,
                        "value": param.value,
                        "min": param.min,
                        "max": param.max,
                        "default": param.defaultValue
                    })
            return Ok({"result": params})
        except Exception as e:
            return Err(f"获取失败: {str(e)}")

    @plugin_entry(
        id="vts_subscribe_event",
        name="订阅事件",
        description="订阅VTube Studio事件",
        metadata={"category": "avatar"},
        parameters={"event_name": {"type": "str", "description": "事件名称"}}
    )
    async def subscribe_event(self, event_name: str = "", **_):
        if not self.is_connected:
            return Err("请先连接VTube Studio")
        if not event_name:
            return Err("请提供事件名称")
        
        try:
            await self.vts.request(
                self.vts.vts_request.requestEventSubscription(
                    eventName=event_name,
                    subscribe=True
                )
            )
            return Ok({"result": f"已订阅事件: {event_name}"})
        except Exception as e:
            return Err(f"订阅失败: {str(e)}")

    def set_event_handler(self, event_name: str, handler):
        self._event_handlers[event_name] = handler

    async def _subscribe_events(self):
        try:
            events = ['ModelLoaded', 'ModelUnloaded', 'ParameterValueChanged', 'HotkeyTriggered']
            
            for event in events:
                await self.vts.request(
                    self.vts.vts_request.requestEventSubscription(
                        eventName=event,
                        subscribe=True
                    )
                )
                
            @self.vts.on('ModelLoaded')
            async def on_model_loaded(event):
                await self._update_current_params()
                handler = self._event_handlers.get('ModelLoaded')
                if handler:
                    await handler(event)
            
            @self.vts.on('ParameterValueChanged')
            async def on_param_changed(event):
                handler = self._event_handlers.get('ParameterValueChanged')
                if handler:
                    await handler(event)
            
            logger.info("事件订阅完成")
        except Exception as e:
            logger.warning(f"事件订阅失败: {e}")

    async def _inject_parameters(self, params):
        if not params:
            return
        
        await self.vts.request(
            self.vts.vts_request.requestInjectParameterData(
                parameter_values=params
            )
        )
        
        for param in params:
            self._current_params[param['id']] = param['value']

    async def _update_current_params(self):
        try:
            response = await self.vts.request(
                self.vts.vts_request.requestParameterList()
            )
            if hasattr(response, 'data'):
                for param in response.data.parameters:
                    self._current_params[param.id] = param.value
        except:
            pass

    async def _animate_parameter(self, name, start_value, end_value, duration, easing_type):
        start_time = time.time()
        
        while time.time() - start_time < duration:
            elapsed = time.time() - start_time
            progress = elapsed / duration
            
            eased_progress = self._apply_easing(progress, easing_type)
            current_value = start_value + (end_value - start_value) * eased_progress
            
            await self._inject_parameters([{"id": name, "value": current_value}])
            await asyncio.sleep(0.01)
        
        await self._inject_parameters([{"id": name, "value": end_value}])

    def _apply_easing(self, progress, easing_type):
        if easing_type == EasingType.LINEAR:
            return progress
        
        elif easing_type == EasingType.EASE_IN:
            return progress ** 2
        
        elif easing_type == EasingType.EASE_OUT:
            return 1 - (1 - progress) ** 2
        
        elif easing_type == EasingType.EASE_BOTH:
            if progress < 0.5:
                return 2 * progress ** 2
            return 1 - (-2 * progress + 2) ** 2 / 2
        
        elif easing_type == EasingType.OVERSHOOT:
            s = 1.70158
            return ((s + 1) * progress - s) * progress ** 2
        
        elif easing_type == EasingType.ZIP:
            return progress + 0.05 * math.sin(progress * math.pi * 8)
        
        return progress

    def _start_auto_blink(self):
        async def blink_loop():
            while self._auto_blink_enabled and self.is_connected:
                await self.blink()
                await asyncio.sleep(self._blink_interval / 1000)
        
        self._blink_task = asyncio.create_task(blink_loop())

    def _stop_auto_blink(self):
        if self._blink_task:
            self._blink_task.cancel()
            self._blink_task = None

    def get_mouth_open_value(self):
        return self._mouth_open_value

    def get_current_params(self):
        return self._current_params