# -*- coding: utf-8 -*-
"""再切一刀：是「任何先前的请求」会把分数带偏，还是只有「没系统提示的短聊天」？

C 组：先发一条和评测同形状的请求（同一份 UNIFIED_SYSTEM + 一句问）→ 再评测。
   C 若 45 → 触发条件是「无系统提示的请求」
   C 若 44 → 触发条件是「服务过任何请求」
"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench"
sys.path.insert(0, HERE)

import urllib.request  # noqa: E402

import evals  # noqa: E402
import registry  # noqa: E402
import serverctl  # noqa: E402

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
reg = registry.scan()
V = next(x for x in reg["versions"] if x["id"] == "gguf:yuanheng-v9t6-lora.gguf")


def boot():
    r = serverctl.start(V["id"], V["path"], reg["bases"]["gguf"], reg["bases"]["mmproj"],
                        port=8091, ctx=8192, ngl=99)
    print("  启动 %s" % json.dumps(r, ensure_ascii=False), flush=True)
    return bool(r.get("ok"))


def ask(messages, max_tokens=60):
    body = {"messages": messages, "temperature": 0.0, "max_tokens": max_tokens}
    req = urllib.request.Request("http://127.0.0.1:8091/v1/chat/completions",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]


def report(tag, out):
    fails = [x["id"] for x in out["results"] if not x["ok"]]
    print("  %-22s %s/%s | %s | 失败 %s"
          % (tag, out["ok"], out["total"], json.dumps(out["by_cat"], ensure_ascii=False),
             ",".join(fails)), flush=True)


print("== C 先发一条「带系统提示」的请求 → 评测", flush=True)
if boot():
    print("  预热：%r" % ask([{"role": "system", "content": evals.UNIFIED_SYSTEM},
                            {"role": "user", "content": "你好"}]), flush=True)
    report("C_after_system", evals._run_persona56(8091, "C_after_system"))
    serverctl.stop()

print("\n== D 先发一条「无系统提示」的短请求 → 评测（对照，复现 44）", flush=True)
if boot():
    print("  预热：%r" % ask([{"role": "user", "content": "你好"}]), flush=True)
    report("D_after_nosystem", evals._run_persona56(8091, "D_after_nosystem"))
    serverctl.stop()
