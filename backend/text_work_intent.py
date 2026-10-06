"""Text-only work routing: concrete actions, not single-character substrings.

This selects reasoning/tool budget, never owner authorization. Voice uses its
frozen route. Explicit session mode=work/casual remains the caller override.
"""
from __future__ import annotations
import re

_ACTION = re.compile(
    r'(?:查(?:一下|询|找|阅|证)|检索|搜索|找一下|读取|列出|整理|计算|分析|对比|比较|'
    r'评估|总结|检查|测试|修复|部署|配置|规划|启动|关闭|审批|批准|待批|待审|'
    r'认知候选|技能草稿|owner_approve|记住|保存|写入|安排|待办|日程|日记|'
    r'记忆(?:库|条目|检索)|台账|知识库|数据库|回忆|记不记得|还记得|'
    r'任务表|(?:加|设|添加|新增).{0,4}(?:提醒|闹钟)|'
    r'记(?:到|进|入).{0,8}(?:任务|待办|日程|表|单|清单)|'
    r'(?:之前|上次|昨天|以前).{0,12}(?:说过|聊过|提过|记录|计划)|'
    r'(?:写|做|生成|处理).{0,8}(?:代码|脚本|程序|模块|文件|报告|方案|计划|任务|功能)|'
    r'(?:怎么|如何|为什么|解释).{0,12}(?:代码|程序|模型|训练|系统|报错|延迟|算法|架构|接口))'
)
_CREATIVE = re.compile(r'(?:写|讲|编|来|做|生成).{0,8}(?:笑话|小故事|故事|诗|俳句|段子|情话|祝福|台词)')


def want_text_work_mode(text: str) -> bool:
    text = str(text or '').strip()
    if not text:
        return False
    from backend.text_tool_contract import text_tool_contract
    if text_tool_contract(text) is not None:
        return True
    # Lightweight creation alone is a direct answer, not a dev/side-effect task.
    if _CREATIVE.search(text) and not re.search(r'保存|写入|日记|文件|任务|日程|记住', text):
        return False
    return bool(_ACTION.search(text))
