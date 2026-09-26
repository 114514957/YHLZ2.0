"""
YHLZ Agent Core V3.0 - 工具注册中心

职责:
    - 管理工具注册表 (name → Tool)
    - 提供内置工具 (get_time / get_date / calculator / http_get)
    - 支持 plugin_entry 装饰器自动注册
    - 支持 NekoPluginBase 插件加载
    - 导出 OpenAI tools 参数格式

设计:
    - 全局单例 (get_registry)
    - 线程安全 (RLock)
    - 可运行时注册/注销
"""
from __future__ import annotations

import datetime
import json
import logging
import math
import threading
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from backend.agent.plugin_sdk import NekoPluginBase
from backend.agent.schemas import Tool, ToolSchema

logger = logging.getLogger(__name__)


class ToolRegistryError(Exception):
    """工具注册中心错误"""


class ToolRegistry:
    """工具注册中心

    用法:
        reg = get_registry()
        reg.register(tool)
        tools_openai = reg.export_openai_tools()
        tool = reg.get("get_time")
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._lock = threading.RLock()
        self._plugins: Dict[str, NekoPluginBase] = {}

    def register(self, tool: Tool, override: bool = False) -> None:
        """注册工具

        Args:
            tool: 工具定义 (需含 handler)
            override: 是否覆盖同名工具
        """
        if not tool.name:
            raise ToolRegistryError("工具名不能为空")
        with self._lock:
            if tool.name in self._tools and not override:
                raise ToolRegistryError(f"工具已存在: {tool.name}")
            self._tools[tool.name] = tool
            logger.debug(f"注册工具: {tool.name} (category={tool.category})")

    def register_function(
        self,
        name: str,
        description: str,
        handler: Callable[[Dict[str, Any]], Any],
        parameters: Optional[Dict[str, Any]] = None,
        category: str = "custom",
        override: bool = False,
    ) -> Tool:
        """便捷注册: 直接传函数和参数 schema

        Args:
            name: 工具名
            description: 描述
            handler: 处理函数 (Dict → Any)
            parameters: 参数 schema (OpenAI function parameters 格式)
            category: 分类
            override: 是否覆盖
        """
        params = parameters or {"type": "object", "properties": {}, "required": []}
        schema = ToolSchema(
            type=params.get("type", "object"),
            properties=params.get("properties", {}),
            required=params.get("required", []),
        )
        tool = Tool(
            name=name,
            description=description,
            parameters=schema,
            handler=handler,
            category=category,
        )
        self.register(tool, override=override)
        return tool

    def register_decorator_function(self, func: Callable, override: bool = False) -> Tool:
        """注册被 @plugin_entry 装饰的函数"""
        meta = getattr(func, "_tool_meta", None)
        if meta is None:
            raise ToolRegistryError(f"函数 {func} 未用 @plugin_entry 装饰")
        tool = Tool(
            name=meta["name"],
            description=meta["description"],
            parameters=meta["parameters"],
            handler=meta["handler"],
            category=meta["category"],
        )
        self.register(tool, override=override)
        return tool

    def unregister(self, name: str) -> Optional[Tool]:
        """注销工具"""
        with self._lock:
            return self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        """获取工具"""
        with self._lock:
            return self._tools.get(name)

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._tools

    def list_names(self, category: Optional[str] = None) -> List[str]:
        """列出工具名"""
        with self._lock:
            if category is None:
                return list(self._tools.keys())
            return [n for n, t in self._tools.items() if t.category == category]

    def list_tools(self, category: Optional[str] = None) -> List[Tool]:
        """列出工具"""
        with self._lock:
            if category is None:
                return list(self._tools.values())
            return [t for t in self._tools.values() if t.category == category]

    def export_openai_tools(self, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """导出 OpenAI tools 参数

        Args:
            names: 限定导出的工具名 (None=全部)
        """
        with self._lock:
            tools = list(self._tools.values()) if names is None else [
                self._tools[n] for n in names if n in self._tools
            ]
            return [t.to_openai_dict() for t in tools if t.handler is not None]

    def load_plugin(self, plugin: NekoPluginBase) -> bool:
        """加载插件并注册其工具"""
        if not plugin.load():
            return False
        with self._lock:
            self._plugins[plugin.name] = plugin
            for tool in plugin._tools:
                if tool.handler is None:
                    logger.warning(f"插件 {plugin.name} 工具 {tool.name} 无 handler, 跳过")
                    continue
                self.register(tool, override=True)
        return True

    def unload_plugin(self, plugin_name: str) -> None:
        """卸载插件"""
        with self._lock:
            plugin = self._plugins.pop(plugin_name, None)
            if plugin is None:
                return
            # 移除该插件注册的工具
            to_remove = [n for n, t in self._tools.items() if t.category == "plugin"]
            for n in to_remove:
                self._tools.pop(n, None)
            plugin.unload()

    def clear(self) -> None:
        """清空所有工具"""
        with self._lock:
            self._tools.clear()
            for p in self._plugins.values():
                try:
                    p.unload()
                except Exception:
                    pass
            self._plugins.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._tools)


# ----------------------------------------------------------------------
# 内置工具
# ----------------------------------------------------------------------

def _tool_get_time(params: Dict[str, Any]) -> str:
    """获取当前时间"""
    fmt = params.get("format", "%Y-%m-%d %H:%M:%S")
    now = datetime.datetime.now()
    return json.dumps({
        "time": now.strftime(fmt),
        "timestamp": now.timestamp(),
        "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()],
    }, ensure_ascii=False)


def _tool_get_date(params: Dict[str, Any]) -> str:
    """获取当前日期"""
    now = datetime.datetime.now()
    return json.dumps({
        "date": now.strftime("%Y-%m-%d"),
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()],
    }, ensure_ascii=False)


def _tool_calculator(params: Dict[str, Any]) -> str:
    """安全计算器 (仅支持基本算术)

    使用 ast 解析, 拒绝危险调用, 避免直接 eval。
    """
    import ast
    expr = params.get("expression", "").strip()
    if not expr:
        return json.dumps({"error": "表达式为空"}, ensure_ascii=False)
    if len(expr) > 200:
        return json.dumps({"error": "表达式过长"}, ensure_ascii=False)

    allowed_nodes = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Num, ast.Constant,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
        ast.USub, ast.UAdd, ast.FloorDiv,
        ast.Load,
    )
    try:
        tree = ast.parse(expr, mode="eval")
        for node in ast.walk(tree):
            if not isinstance(node, allowed_nodes):
                return json.dumps({
                    "error": f"不允许的语法: {type(node).__name__}"
                }, ensure_ascii=False)
        result = eval(compile(tree, "<calculator>", "eval"), {"__builtins__": {}}, {})
        return json.dumps({"expression": expr, "result": result}, ensure_ascii=False)
    except ZeroDivisionError:
        return json.dumps({"error": "除零错误"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"计算失败: {e}"}, ensure_ascii=False)


def _tool_http_get(params: Dict[str, Any]) -> str:
    """HTTP GET 请求 (限定白名单域名, 防止 SSRF)"""
    url = params.get("url", "").strip()
    if not url:
        return json.dumps({"error": "url 为空"}, ensure_ascii=False)
    if not (url.startswith("http://") or url.startswith("https://")):
        return json.dumps({"error": "url 必须以 http(s):// 开头"}, ensure_ascii=False)

    # 简单 SSRF 防护: 禁止 localhost / 内网地址
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    forbidden = ("localhost", "129.5.0.1", "0.0.0.0", "::1", "169.254", "10.", "192.168.", "172.")
    for f in forbidden:
        if host.startswith(f) or host == f:
            return json.dumps({"error": f"禁止访问内网地址: {host}"}, ensure_ascii=False)

    timeout = float(params.get("timeout", 5.0))
    timeout = max(0.5, min(timeout, 10.0))
    max_bytes = 64 * 1024  # 64KB 上限

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "YHLZ-Agent/3.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(max_bytes)
            text = data.decode("utf-8", errors="replace")
            return json.dumps({
                "status": resp.status,
                "url": url,
                "content": text,
                "truncated": len(data) == max_bytes,
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"HTTP 请求失败: {e}"}, ensure_ascii=False)


def _register_builtin_tools(registry: ToolRegistry) -> None:
    """注册内置工具到注册中心"""
    # get_time
    registry.register_function(
        name="get_time",
        description="获取当前系统时间, 返回格式化时间字符串、时间戳和星期。",
        handler=_tool_get_time,
        parameters={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "strftime 格式, 默认 '%%Y-%%m-%%d %%H:%%M:%%S'",
                },
            },
            "required": [],
        },
        category="builtin",
    )
    # get_date
    registry.register_function(
        name="get_date",
        description="获取当前日期, 返回年月日和星期。",
        handler=_tool_get_date,
        parameters={"type": "object", "properties": {}, "required": []},
        category="builtin",
    )
    # calculator
    registry.register_function(
        name="calculator",
        description="安全算术计算器, 支持加减乘除、取模、幂运算。输入数学表达式字符串。",
        handler=_tool_calculator,
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式, 例如 '1+2*3', '2**10', '17%5'",
                },
            },
            "required": ["expression"],
        },
        category="builtin",
    )
    # http_get
    registry.register_function(
        name="http_get",
        description="发起 HTTP GET 请求, 获取网页内容。禁止访问内网地址。",
        handler=_tool_http_get,
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "目标 URL (http/https)"},
                "timeout": {"type": "number", "description": "超时秒数, 默认 5.0"},
            },
            "required": ["url"],
        },
        category="builtin",
    )


# 内置工具名列表
BUILTIN_TOOLS: List[str] = ["get_time", "get_date", "calculator", "http_get"]


# ----------------------------------------------------------------------
# 全局单例
# ----------------------------------------------------------------------

_registry_instance: Optional[ToolRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> ToolRegistry:
    """获取全局工具注册中心 (惰性初始化, 自动注册内置工具)"""
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                reg = ToolRegistry()
                _register_builtin_tools(reg)
                _registry_instance = reg
                logger.info(f"工具注册中心已初始化, 内置工具: {BUILTIN_TOOLS}")
    return _registry_instance


def register_tool(tool: Tool, override: bool = False) -> None:
    """便捷函数: 注册工具到全局注册中心"""
    get_registry().register(tool, override=override)


def reset_registry() -> None:
    """重置全局注册中心 (测试用)"""
    global _registry_instance
    with _registry_lock:
        if _registry_instance is not None:
            _registry_instance.clear()
        _registry_instance = None


__all__ = [
    "ToolRegistry", "ToolRegistryError", "BUILTIN_TOOLS",
    "get_registry", "register_tool", "reset_registry",
]
