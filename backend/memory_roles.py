# -*- coding: utf-8 -*-
"""记忆分层规则（**纯函数、无副作用**，生产与工具共用）。

台账 1232/1235：1022 条记忆里约 70% 是工程流水账，直接注入会把她的口吻带成"项目经理"。
所以按来源与内容把每条分到四层，**只有 her / owner 参与召回注入**。

分层原则（可解释、可复现、宁可少判不可错判）：
  engineering  开发日志来源（agent/opencode/利贞）；或含工程强特征（台账/记录编号/验收/探针/链路…）
  her          群聊原话且去掉前缀后够长（"元亨: ..."）
  owner        来源或内容明确指向老爹，且不像工程
  unknown      都不像 —— **默认不注入**，留待人工复核
"""
from __future__ import annotations

import re

__all__ = ["classify", "ROLES", "ENG_STRONG", "ENG_MED", "is_injectable"]

ROLES = ("her", "owner", "engineering", "unknown")

ENG_STRONG = re.compile(
    r"(台账|记录 ?\d{3,4}|用户决策|用户要求|本轮依据|验收|探针|冻结|链路|重构|部署|接口|端口|"
    r"测试证据|只动目标|Provider|架构|数据库|脚本|编译|显存|LoRA|数据集|评测|回归|"
    r"计划表|会话档案|工作流|开发经验|opencode|利贞|简报|待处理|基线|批次|批处理|"
    r"设计结论|模块化|Session Kernel|WebUI|Health Supervisor|判定清单|收敛|"
    r"仍需用户确认|未决事项|下一步依据|能力模块|审计|PR |提交)")
ENG_MED = re.compile(r"(配置|日志|模型|训练|GPU|CPU|服务|进程|版本|字段|接口|调用|api|API|"
                     r"阈值|指标|场景|扬声器|耳机|认证)")

HER_TALK = re.compile(r"元亨[:：]")
HER_MIN_BODY = 8
DEV_SRC = re.compile(r"(agent|opencode|利贞)")
OWNER_SRC = re.compile(r"(老爹|owner|qq_private)")
OWNER_TXT = re.compile(r"(老爹|你爹|爸|主人)")


def classify(item: dict) -> tuple[str, str]:
    """返回 (role, 理由)。item 需含 summary / source。"""
    text = " ".join(str(item.get("summary") or "").split())
    src = str(item.get("source") or "")
    if DEV_SRC.search(src):
        return "engineering", "开发日志来源(%s)" % src[:16]
    if HER_TALK.search(text) and len(HER_TALK.sub("", text).strip()) >= HER_MIN_BODY:
        return "her", "群聊原话"
    eng_s = len(ENG_STRONG.findall(text))
    eng_m = len(ENG_MED.findall(text))
    if eng_s >= 1:
        return "engineering", "工程强特征×%d" % eng_s
    if eng_m >= 3:
        return "engineering", "工程中特征×%d" % eng_m
    if OWNER_SRC.search(src) or OWNER_TXT.search(text):
        return "owner", "来源/内容含老爹"
    if eng_m >= 1:
        return "unknown", "弱工程特征×%d（待人工）" % eng_m
    return "unknown", "规则未覆盖"


def is_injectable(role: str) -> bool:
    """是否允许进入召回注入。默认只有 her/owner。"""
    return role in ("her", "owner")
