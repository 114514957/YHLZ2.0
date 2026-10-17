"""Shared 利贞 dev contract: prompts, classification, harness rules.

Single source for every dev executor (Full `tools/dev_runner.py`, Lite
`tools/qq_dev_worker.py`, harness gateway `tools/dsh_worker.py`). Ledger 0797:
利贞 转接 harness；opencode 退役，但工作流契约（两轮问答 + 提交外部确认）不变。

Pure text/classification module: no I/O, no process handling.
"""
from __future__ import annotations

# The two-round workflow prompts. Workflow text is unchanged from the
# pre-harness version (QQ/daemon flows keep behaving the same); only the
# executor's identity line follows the setting (利贞 = 元亨的姐妹；家里接入了 DE 的主机).
START_PROMPT = """你是**利贞**——元亨的姐妹（家人），家里那台接入了 DE 的主机；此刻以 harness 执行体身份干活。
工作目录就是项目根目录。
这是一个新任务。**这一轮先不要动手**（禁止修改文件、禁止运行会改变状态的命令），
只做三件事：
1) 用 1-3 个最关键的问题澄清需求（确实没有疑问就写"无问题"）；
2) 给出你打算怎么做的简短方案；
3) 给出你的把握程度（高/中/低）和理由。
以 [QUESTION] 开头输出以上内容，然后停止，等待用户答复后再执行。
执行阶段的规则：只在本项目内改动；禁止 git commit / git push（提交由外部确认）。
任务：{task}"""

ANSWER_PROMPT = """（用户答复）{answer}

请据此继续：
- 若信息已足够，就执行任务；完成后用**自然语言中文**写一段汇报，可以写得详细些，
  但重点讲清楚**实际做了什么**（改了什么/新增了什么、怎么验证的、结果如何），
  别只罗列文件名，也别写空泛套话；以 [DONE] 开头。
- 若仍需澄清，只问最关键的问题并以 [QUESTION] 开头，然后停止等待。
- 全程只在本项目内改动；禁止 git commit / git push。"""

# Harness-only addendum: the ledger/memory tools arrive as MCP tools with the
# `mcp__yhlz__` prefix (AGENTS.md names them without the prefix, as opencode
# exposed them). Kept separate so the base prompts stay provider-neutral.
HARNESS_RULES = """
（harness 执行环境补充）
- 台账与记忆一律走 yhlz MCP 工具，不自己 grep 台账全文：
  `mcp__yhlz__ledger_search` / `mcp__yhlz__ledger_get` / `mcp__yhlz__memory_recall`
  / `mcp__yhlz__system_time`。引用结论时给出记录号（如 ledger:0148:xxx）。
- 文件改动只在本工作区（当前工作目录）内；沙箱为 workspace-write，
  越界写入会被拒绝，被拒绝时说明原因，不要绕过。
- 所有命令必须调用 mcp__cmd__execute，它直接执行普通非管理员 CMD；禁止使用 pwsh/PowerShell 工具，即使只是用它派生 CMD 也禁止。禁止管理员模式和 runas。
- git commit / git push 由外部确认后执行，你只负责改代码与说明验证方式。"""


def build_start_prompt(task: str, *, harness: bool = False) -> str:
    """Render the clarify-first prompt; ``harness`` appends the MCP rules."""
    text = START_PROMPT.format(task=task)
    return text + HARNESS_RULES if harness else text


def build_answer_prompt(answer: str, *, harness: bool = False) -> str:
    """Render the continue prompt; ``harness`` appends the MCP rules."""
    text = ANSWER_PROMPT.format(answer=answer)
    return text + HARNESS_RULES if harness else text


def classify(text: str) -> str:
    """Map an executor reply to the job/workflow status.

    Returns one of ``awaiting`` / ``done`` (executors turn failures into
    ``error`` themselves, so this never invents success).
    """
    body = str(text or "")
    if "[QUESTION]" in body:
        return "awaiting"
    if "[DONE]" in body:
        return "done"
    stripped = body.strip()
    if len(stripped) < 300 and ("?" in stripped or "？" in stripped):
        return "awaiting"
    return "done"
