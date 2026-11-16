# -*- coding: utf-8 -*-
"""场景裁剪（台账 1259）：闲聊不需要全部提示词，只留必要的。

老爹的判断：「聊天时并不需要启用全部提示词，只需要启用必要提示词，比如人格、禁令」。

和"压缩"的区别（这一条很关键）：
  · 上一轮我做的是**把人格块写短** → 人格 -5（教训：动了人格块就掉分）
  · 这一轮做的是**人格块一字不改，整块丢掉闲聊用不到的**
    （开发流程、工具协议、反幻觉、记忆边界、内容释放、后台说明…）

默认关闭（`YHLZ_PROMPT_SCENE=1` 才生效），因为要先过 3 轮评测。
"""
from __future__ import annotations

import os
import re

__all__ = ["DROP_IN_CASUAL", "classify", "enabled", "droppable_names"]

# 闲聊（casual）时可以整块不发的：都与"开发/工具/检索/系统说明"有关
DROP_IN_CASUAL = (
    "DEV_DISPATCH_CLAUSE",        # 开发活派给利贞的流程
    "DEV_TOOL_BOUNDARY_CLAUSE",   # 开发工具边界
    "TOOL_PROTOCOL_CLAUSE",       # 工具调用协议
    "ANTI_HALLUCINATION",         # 检索/执行事实的防编造（闲聊用不到检索）
    "MEMORY_BOUNDARY_CLAUSE",     # 记忆边界（写入规则）
    "CONTENT_RELEASE_CLAUSE",     # 内容释放流程
    "BACKGROUND_CLAUSE",          # 后台/系统说明
)

WORK = re.compile(
    r"(改|修|写|跑|测|装|部署|编译|训练|评测|导出|打包|生成|脚本|代码|目录|配置|"
    r"接口|端口|日志|报错|bug|git|pip|npm|数据库|表|字段|正则|函数|模块|重构|"
    r"台账|记录 ?\d|权重|数据集|推文|报表|查一下|搜一下|帮我查|帮我找|检索)")


def enabled() -> bool:
    return (os.getenv("YHLZ_PROMPT_SCENE") or "").strip() in ("1", "true", "on", "yes")


def classify(text: str) -> str:
    """这一轮是闲聊还是干活。"""
    return "work" if WORK.search(str(text or "")) else "casual"


def droppable_names(scene: str, public: bool = False) -> tuple[str, ...]:
    """哪些块可以不发。

    2026-11-16（台账 1260）：**只在群聊（public）裁剪**。
    三次实验一致显示：任何"减负"都让私聊人格掉分（-5~-10）、群聊反而升（+2~3），
    所以私聊保持全量，群聊才裁。
    """
    if not enabled() or scene != "casual" or not public:
        return ()
    return DROP_IN_CASUAL
