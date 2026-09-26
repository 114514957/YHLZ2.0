"""
YHLZ Agent Core V3.0 - 插件 SDK

修复 V2.x 遗留问题: plugins/ 目录下的插件 import backend.plugin_sdk
但该模块不存在, 导致插件全部无法加载。

本模块提供:
    - NekoPluginBase: 插件基类
    - neko_plugin: 装饰器, 标记插件入口函数
    - plugin_entry: 装饰器, 声明工具 schema
    - Ok / Err: Result 类型 (与 voice_identity.clone.result 一致)

兼容旧 plugins/ 目录的导入路径:
    from backend.plugin_sdk import NekoPluginBase, neko_plugin, plugin_entry, Ok, Err
"""
from __future__ import annotations

import functools
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

from backend.agent.schemas import Tool, ToolSchema

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ----------------------------------------------------------------------
# Result 类型
# ----------------------------------------------------------------------

@dataclass
class Ok(Generic[T]):
    """成功结果"""
    value: T

    @property
    def is_ok(self) -> bool:
        return True

    @property
    def is_err(self) -> bool:
        return False

    def unwrap(self) -> T:
        return self.value


@dataclass
class Err:
    """失败结果"""
    error: str

    @property
    def is_ok(self) -> bool:
        return False

    @property
    def is_err(self) -> bool:
        return True

    def unwrap(self) -> Any:
        raise RuntimeError(f"Err.unwrap: {self.error}")


# ----------------------------------------------------------------------
# 插件基类
# ----------------------------------------------------------------------

class NekoPluginBase:
    """插件基类

    子类需实现:
        - name: 插件名
        - version: 版本
        - get_tools() -> List[Tool]: 返回插件提供的工具列表
        - on_load() / on_unload(): 生命周期钩子 (可选)
    """
    name: str = "base"
    version: str = "0.1.0"
    description: str = ""

    def __init__(self):
        self._loaded: bool = False
        self._tools: List[Tool] = []

    def on_load(self) -> None:
        """加载钩子 (可重写)"""
        pass

    def on_unload(self) -> None:
        """卸载钩子 (可重写)"""
        pass

    def get_tools(self) -> List[Tool]:
        """返回插件提供的工具列表 (子类必须实现)"""
        raise NotImplementedError

    def load(self) -> bool:
        """加载插件"""
        if self._loaded:
            return True
        try:
            self.on_load()
            self._tools = self.get_tools()
            self._loaded = True
            logger.info(f"插件已加载: {self.name} v{self.version} ({len(self._tools)} 工具)")
            return True
        except Exception as e:
            logger.error(f"插件加载失败 {self.name}: {e}")
            return False

    def unload(self) -> None:
        """卸载插件"""
        if not self._loaded:
            return
        try:
            self.on_unload()
        except Exception as e:
            logger.warning(f"插件卸载异常 {self.name}: {e}")
        finally:
            self._loaded = False
            self._tools = []


# ----------------------------------------------------------------------
# 装饰器
# ----------------------------------------------------------------------

def neko_plugin(cls):
    """类装饰器: 标记为 YHLZ 插件

    用法:
        @neko_plugin
        class WeatherPlugin(NekoPluginBase):
            name = "weather"
    """
    orig_init = cls.__init__

    @functools.wraps(orig_init)
    def __init__(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        if not isinstance(self, NekoPluginBase):
            # 自动继承基类
            pass

    cls.__init__ = __init__
    cls._is_neko_plugin = True
    return cls


def plugin_entry(
    id: str,
    name: Optional[str] = None,
    description: str = "",
    parameters: Optional[Dict[str, Any]] = None,
    category: str = "plugin",
):
    """函数装饰器: 声明工具入口

    用法:
        @plugin_entry(id="get_time", description="获取当前时间", parameters={...})
        def get_time(params: Dict) -> str:
            ...

    被装饰函数会带上 _tool_meta 属性, ToolRegistry 可识别并注册。
    """
    def decorator(func: Callable):
        tool_name = name or id
        params = parameters or {"type": "object", "properties": {}, "required": []}

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # 构造 Tool 元数据
        schema = ToolSchema(
            type=params.get("type", "object"),
            properties=params.get("properties", {}),
            required=params.get("required", []),
        )
        wrapper._tool_meta = {
            "name": tool_name,
            "description": description or func.__doc__ or "",
            "parameters": schema,
            "handler": wrapper,
            "category": category,
        }
        return wrapper

    return decorator


__all__ = [
    "NekoPluginBase", "Ok", "Err",
    "neko_plugin", "plugin_entry",
]
