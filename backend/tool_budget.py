# -*- coding: utf-8 -*-
"""工具按需加载（台账 1242：43 个工具 schema = 2933 token，每轮全塞太贵）。

**默认关闭**（`YHLZ_TOOL_BUDGET=1` 才启用），接线前先能度量、能回归。

分层（按轮次意图给不同子集）：
  casual   闲聊/寒暄 → 6 个最常用（时间/记忆读写/日记/任务）
  normal   一般对话 → 上面 6 个 + 检索类（台账/知识/文件/网络）
  work     明确要做工程/文件/任务 → 全量 43 个

判断依据（可解释）：工程词表、请求动词、长度。命中 work 词表 → 全量；
否则看有没有检索/记忆类意图 → normal；纯闲聊 → casual。

安全兜底：任何异常都返回**全量**（宁可多花钱，不可让它"不会用"）。
"""
from __future__ import annotations

import os
import re
from typing import Iterable, Sequence

__all__ = ["select", "level_of", "enabled", "LEVELS", "CORE", "RETRIEVAL"]

CORE = ("system_time", "memory_save", "memory_recall", "diary_write",
        "task_plan", "schedule_plan")
RETRIEVAL = ("ledger_search", "ledger_get", "ledger_list", "kb_query", "kb_add",
             "file_read", "file_list", "web_search", "web_fetch", "memory_why")

WORK_HINTS = re.compile(
    r"(改|修|写|跑|测|装|部署|编译|训练|评测|导出|打包|生成|脚本|代码|目录|配置|"
    r"接口|端口|日志|报错|bug|git|pip|npm|数据库|表|字段|正则|函数|类|模块|重构|"
    r"权重|数据集|推文|报表)")
# 注意：`台账`/`记录`/`查` 属**检索**（读），不算 work——
# 否则"查一下台账"会吃全量 43 个工具（实测：2933 token，等于没省）。
RETRIEVAL_HINTS = re.compile(
    r"(查|搜|找|记得|上次|之前|说过|是什么|为什么|多少|谁|哪里|哪个|来着|"
    r"台账|知识|资料|文件|网页|搜索)")

LEVELS = ("casual", "normal", "work")


def enabled() -> bool:
    return (os.getenv("YHLZ_TOOL_BUDGET") or "").strip() in ("1", "true", "on", "yes")


def level_of(text: str) -> str:
    """判断这一轮该给哪一档工具。"""
    t = str(text or "")
    if WORK_HINTS.search(t):
        return "work"
    if RETRIEVAL_HINTS.search(t):
        return "normal"
    return "casual"


def select(all_tools: Sequence[dict], text: str,
           allowed: Iterable[str] | None = None) -> list[dict]:
    """按意图裁剪工具列表。`allowed` 是权限白名单（先交再裁）。

    不在 enable 状态、或异常 → 返回原列表（安全兜底）。
    """
    try:
        if not enabled():
            return list(all_tools)
        names = {t.get("function", {}).get("name") for t in all_tools}
        allow = set(allowed) if allowed is not None else names
        lvl = level_of(text)
        if lvl == "work":
            want = names
        elif lvl == "normal":
            want = set(CORE) | set(RETRIEVAL)
        else:
            want = set(CORE)
        picked = [t for t in all_tools
                  if t.get("function", {}).get("name") in (want & allow)]
        # 一个都没选出来就别裁（否则模型真的没有工具可用）
        return picked or list(all_tools)
    except Exception:  # noqa: BLE001
        return list(all_tools)
