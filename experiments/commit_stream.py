# -*- coding: utf-8 -*-
"""提交（消息文件），并展示本轮关键数字。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "commitmsg_stream.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "feat(llm): 流式路径记账 + 断网演练验证\n\n"
    "- llm_stream.stream_openai_compatible 结束后记账（channel=stream，含 usage）\n"
    "  原先只有非流式工厂记账，而工作台/QQ 的真实对话几乎全走流式 → 费用漏记大头\n"
    "- 实测：一句「在吗」in 6039 / out 5 / 2.77 秒 / ¥0.012118\n"
    "  其中系统提示 3147 token + 43 个工具定义 ~2900 token → 提示词瘦身能直接省一半\n"
    "- 断网演练（端点指到 127.0.0.1:9）：明确抛 LLMUnavailable，重试 3 次共 8.6 秒，\n"
    "  失败也记一条 ok=false；**没有静默降级到本地**（老爹 1231 定论：不做本地兜底）\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-120:]))
r = subprocess.run(["git", "log", "--oneline", "-3"], cwd=ROOT, capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
print(r.stdout)
r = subprocess.run(["git", "status", "-sb"], cwd=ROOT, capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
print(r.stdout.splitlines()[0] if r.stdout else "")
