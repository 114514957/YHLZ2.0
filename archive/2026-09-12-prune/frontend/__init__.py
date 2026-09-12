"""
YHLZ AI伙伴前端 (Frontend Runtime Shell)

重新设计定位 (V10.1 Frontend Runtime Edition):
    - 不是聊天软件 / 不是工具面板
    - 是 AI 伙伴生命载体终端 (Companion Runtime Shell)

结构:
    avatar/    形象层 (Live2D 渲染封装 / 动画 / 情绪)
    runtime/   运行时层 (状态 / 事件 / 追踪)
    startup/   一键启动核心
    settings/  设置 (基础/AI/Memory/Developer)
    monitor/   开发模式运行时控制台
    main.py    桌面主窗口入口

设计原则:
    - 一键启动完整伙伴核心, 用户无需手动连接/选择
    - 伙伴状态反馈优先 (思考中/学习中/待机/在线)
    - 保持原 Live2D 视觉风格 (透明/无边框/半透明)
    - 开发模式隐藏 (Ctrl+Shift+R)
    - 不暴露后台日志给普通用户
"""
from __future__ import annotations

__version__ = "10.1.0"
