# -*- coding: utf-8 -*-
"""验证：44/56 是不是 llama-server 的 prompt 缓存造成的？

做法：先说话（复现 44 的条件），然后在评测请求里加 `cache_prompt: false`。
若分数回到 45，就说明是缓存复用让两道边缘题翻面。
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


def chat(text="在吗") -> str:
    body = {"messages": [{"role": "user", "content": text}],
            "temperature": 0.0, "max_tokens": 60}
    req = urllib.request.Request("http://127.0.0.1:8091/v1/chat/completions",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]


def boot():
    r = serverctl.start(V["id"], V["path"], reg["bases"]["gguf"], reg["bases"]["mmproj"],
                        port=8091, ctx=8192, ngl=99)
    print("  启动 %s" % json.dumps(r, ensure_ascii=False), flush=True)
    return bool(r.get("ok"))


def report(tag, out):
    fails = [x["id"] for x in out["results"] if not x["ok"]]
    print("  %-20s %s/%s | %s | 失败 %s"
          % (tag, out["ok"], out["total"], json.dumps(out["by_cat"], ensure_ascii=False),
             ",".join(fails)), flush=True)
    p10 = [x for x in out["results"] if x["id"] == "p10"][0]
    print("     p10: %s | %r" % (p10["ok"], p10["answer"][:70]), flush=True)


orig_post = evals._post


def post_no_cache(port, body, timeout=300):
    body = dict(body)
    body["cache_prompt"] = False
    return orig_post(port, body, timeout)


# --- 对照组：先说话 + 默认（应复现 44）
print("== A 先说话 → 默认请求（复现 44）", flush=True)
if boot():
    print("  聊天：%r" % chat(), flush=True)
    report("A_default", evals._run_persona56(8091, "A_default"))
    serverctl.stop()

# --- 实验组：先说话 + cache_prompt=false
print("\n== B 先说话 → cache_prompt=false", flush=True)
if boot():
    print("  聊天：%r" % chat(), flush=True)
    evals._post = post_no_cache
    try:
        report("B_no_cache", evals._run_persona56(8091, "B_no_cache"))
    finally:
        evals._post = orig_post
    serverctl.stop()
