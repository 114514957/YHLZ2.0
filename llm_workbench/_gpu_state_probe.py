# -*- coding: utf-8 -*-
"""对照实验：先对话再评测，会不会把分数带偏？

A 组：起服务 → 直接评测
B 组：起服务 → 先发两条对话 → 再评测
两组同权重、同参数、同判据。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench"
sys.path.insert(0, HERE)

import evals  # noqa: E402
import registry  # noqa: E402
import serverctl  # noqa: E402

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
reg = registry.scan()
V = next(x for x in reg["versions"] if x["id"] == "gguf:yuanheng-v9t6-lora.gguf")


def chat_once(text: str) -> str:
    body = {"messages": [{"role": "user", "content": text}],
            "temperature": 0.0, "max_tokens": 60}
    req = urllib.request.Request("http://127.0.0.1:8091/v1/chat/completions",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]


def start():
    r = serverctl.start(V["id"], V["path"], reg["bases"]["gguf"], reg["bases"]["mmproj"],
                        port=8091, ctx=8192, ngl=99)
    if not r.get("ok"):
        print("✗ 启动失败", r, flush=True)
        sys.exit(1)
    return r


# ---- A 组：冷启动直接评测
start()
out_a = evals._run_persona56(8091, "state_A")
fa = [x["id"] for x in out_a["results"] if not x["ok"]]
print("A（冷启动直接评）：%s/%s %s" % (out_a["ok"], out_a["total"],
                                   json.dumps(out_a["by_cat"], ensure_ascii=False)), flush=True)
print("  失败：%s" % ",".join(fa), flush=True)

# ---- B 组：同一实例，先聊两句，再评
print("\n先发两条对话：%r / %r" % (chat_once("在吗"), chat_once("讲个笑话")), flush=True)
out_b = evals._run_persona56(8091, "state_B")
fb = [x["id"] for x in out_b["results"] if not x["ok"]]
print("B（聊过后再评）：%s/%s %s" % (out_b["ok"], out_b["total"],
                                 json.dumps(out_b["by_cat"], ensure_ascii=False)), flush=True)
print("  失败：%s" % ",".join(fb), flush=True)

print("\n差异：新增失败 %s | 少失败 %s"
      % (sorted(set(fb) - set(fa)) or "无", sorted(set(fa) - set(fb)) or "无"), flush=True)
serverctl.stop()
