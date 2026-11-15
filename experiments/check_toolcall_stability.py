# -*- coding: utf-8 -*-
"""同一请求跑 5 次：看原生 tool_calls / 文本伪调用 的分布（判断是不是不稳定）。"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "llm_workbench"))
from backend import target_prompts as TP  # noqa: E402
import evals as EV  # noqa: E402

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
tools = EV.load_tools()
sysp = TP.render_system_prompt(public=False)

for q in ("现在几点", "帮我加个任务：明天整理素材"):
    print("=" * 66)
    print("问：%s" % q)
    native = text_form = none_fmt = 0
    for i in range(5):
        body = {"messages": [{"role": "system", "content": sysp},
                             {"role": "user", "content": q}],
                "tools": tools, "tool_choice": "auto",
                "temperature": 0.0, "max_tokens": 300, "stream": False}
        req = urllib.request.Request("http://127.0.0.1:8081/v1/chat/completions",
                                     data=json.dumps(body, ensure_ascii=False).encode(),
                                     headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=120) as r:
            d = json.loads(r.read().decode())
        ch = (d.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        tc = msg.get("tool_calls") or []
        content = str(msg.get("content") or "")
        if tc:
            native += 1
            kind = "原生 tool_calls: %s" % [c["function"]["name"] for c in tc]
        elif re.search(r"<tool_call>|<call:", content):
            text_form += 1
            kind = "文本伪调用：%s" % content[:60].replace("\n", " ")
        else:
            none_fmt += 1
            kind = "纯文本回答：%s" % content[:60].replace("\n", " ")
        print("  %d) finish=%s｜%s" % (i + 1, ch.get("finish_reason"), kind))
    print("  统计：原生 %d｜文本伪调用 %d｜纯文本 %d" % (native, text_form, none_fmt))
