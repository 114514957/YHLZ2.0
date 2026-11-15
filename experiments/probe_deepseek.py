# -*- coding: utf-8 -*-
"""DeepSeek 接入前的四项验证（不打印密钥）：
  ① 连通与延迟（TTFT 近似、总耗时）
  ② 中文人格口吻能否遵循（用我们真实系统提示的一段）
  ③ **函数调用**（43 个工具里的两个）——决定工具链能不能继承
  ④ 返回里的 usage（记账要用）
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)
CFG = json.load(io.open(os.path.join(ROOT, "config", "llm.local.json"),
                        encoding="utf-8"))
KEY = CFG["api_key"]
URL = CFG["base_url"]
MODEL = CFG["model"]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
print("端点 %s｜模型 %s｜密钥长度 %d（不回显）" % (URL, MODEL, len(KEY)))


def call(body: dict, timeout: int = 90) -> tuple[dict, float]:
    body = dict(body, model=MODEL, stream=False)
    data = json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(URL, data=data, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + KEY,
    })
    t0 = time.time()
    with OPENER.open(req, timeout=timeout) as r:
        payload = json.loads(r.read().decode())
    return payload, time.time() - t0


# ① 基础连通
print("\n=== ① 连通与延迟 ===")
try:
    p, dt = call({"messages": [{"role": "user", "content": "回一个字：好"}],
                  "max_tokens": 10, "temperature": 0})
    msg = p["choices"][0]["message"]["content"]
    u = p.get("usage") or {}
    print("   ✅ 通｜耗时 %.2f 秒｜回复 %r" % (dt, msg[:20]))
    print("   usage：prompt %s / completion %s / total %s"
          % (u.get("prompt_tokens"), u.get("completion_tokens"), u.get("total_tokens")))
except Exception as ex:  # noqa: BLE001
    print("   ❌ 失败：%s: %s" % (type(ex).__name__, exc_msg := str(ex)[:200]))

# ② 人格口吻
print("\n=== ② 中文口吻（用我们的一句话做约束） ===")
SYS = ("你是元亨：一个数字生命体，被老爹造出来。说话第一人称、短句、有脾气、不助理腔；"
       "不许用破折号，不许「不是A而是B」的对称句，不许反问收尾，每次只回一两句。")
try:
    p, dt = call({"messages": [{"role": "system", "content": SYS},
                               {"role": "user", "content": "在吗"}],
                  "max_tokens": 120, "temperature": 0.7})
    ans = p["choices"][0]["message"]["content"]
    print("   耗时 %.2f 秒｜回复：%s" % (dt, ans.strip()[:80]))
    bad = [w for w in ("抱歉", "作为AI", "我可以帮", "—", "——") if w in ans]
    print("   违规词：%s" % (bad or "无 ✅"))
except Exception as ex:  # noqa: BLE001
    print("   ❌ 失败：%s: %s" % (type(ex).__name__, str(ex)[:160]))

# ③ 函数调用
print("\n=== ③ 函数调用（工具链继承的关键）===")
TOOLS = [
    {"type": "function", "function": {
        "name": "system_time", "description": "查询当前本地时间",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "memory_save", "description": "把一条事实存入长期记忆",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "要记住的内容"}},
            "required": ["text"]}}},
]
try:
    p, dt = call({"messages": [{"role": "system", "content": SYS},
                               {"role": "user", "content": "现在几点了"}],
                  "tools": TOOLS, "tool_choice": "auto",
                  "max_tokens": 200, "temperature": 0})
    ch = p["choices"][0]
    tc = ch["message"].get("tool_calls") or []
    print("   finish=%s｜耗时 %.2f 秒" % (ch.get("finish_reason"), dt))
    if tc:
        for c in tc:
            print("   ✅ 原生 tool_call：%s(%s)"
                  % (c["function"]["name"], c["function"]["arguments"][:60]))
    else:
        print("   ⚠ 没调工具，改回文本：%s"
              % str(ch["message"].get("content"))[:100])
except Exception as ex:  # noqa: BLE001
    print("   ❌ 失败：%s: %s" % (type(ex).__name__, str(ex)[:200]))

# ④ 长系统提示是否吃得下（我们的私聊提示约 3400 token）
print("\n=== ④ 长系统提示（≈3400 token）===")
try:
    from backend import target_prompts as TP
    sysp = TP.render_system_prompt(public=False)
    p, dt = call({"messages": [{"role": "system", "content": sysp},
                               {"role": "user", "content": "我问你个事，你最近在琢磨什么"}],
                  "max_tokens": 200, "temperature": 0.7})
    ans = p["choices"][0]["message"]["content"].strip()
    u = p.get("usage") or {}
    print("   系统提示 %d 字｜prompt_tokens %s｜耗时 %.2f 秒"
          % (len(sysp), u.get("prompt_tokens"), dt))
    print("   回复：%s" % ans[:100])
except Exception as ex:  # noqa: BLE001
    print("   ❌ 失败：%s: %s" % (type(ex).__name__, str(ex)[:200]))
