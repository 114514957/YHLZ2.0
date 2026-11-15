# -*- coding: utf-8 -*-
"""查一件事：`<tool_call>{json}</tool_call>` 到底有没有被 llama-server 解析成原生 tool_calls。

直接发一次带 tools 的请求，把 message 对象原样打出来。
"""
from __future__ import annotations

import json
import os
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
body = {
    "messages": [{"role": "system", "content": TP.render_system_prompt(public=False)},
                 {"role": "user", "content": "现在几点"}],
    "tools": tools, "tool_choice": "auto",
    "temperature": 0.0, "max_tokens": 300, "stream": False,
}
req = urllib.request.Request("http://127.0.0.1:8081/v1/chat/completions",
                             data=json.dumps(body, ensure_ascii=False).encode(),
                             headers={"Content-Type": "application/json"})
with OPENER.open(req, timeout=120) as r:
    d = json.loads(r.read().decode())
msg = (d.get("choices") or [{}])[0].get("message") or {}
print("message 的键：", sorted(msg))
print("finish_reason：", (d.get("choices") or [{}])[0].get("finish_reason"))
print("tool_calls：", json.dumps(msg.get("tool_calls"), ensure_ascii=False))
print("content：", repr(str(msg.get("content") or ""))[:300])
