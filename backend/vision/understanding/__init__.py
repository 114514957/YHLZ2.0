"""
YHLZ Vision Understanding V1.0 - Understanding 包入口

子模块:
    - schema:        数据结构
    - interface:     抽象接口 (VLMAdapter)
    - base:          Adapter 基类 (模板方法)
    - adapters:      具体 Adapter 实现 (组合 Provider)
    - providers:     底层模型实现 (Mock / OpenAI 兼容 VLM)
    - manager:       注册表 + 路由
    - service:       对外统一 API
    - permission:    权限校验
    - logger:        日志
    - tools:         Agent 工具注册
"""
from __future__ import annotations

__version__ = "1.0.0"
