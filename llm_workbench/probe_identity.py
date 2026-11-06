# -*- coding: utf-8 -*-
"""控制实验：把「提示词 × 问法 × 模型」拆开，看 g18 回退到底怪谁。

2 个模型 × 2 套系统提示词（私聊 UNIFIED / 群聊 public）× 2 种问法。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import evals  # noqa: E402

EXE = os.path.join(YH, "models", "llama-cuda", "llama-server.exe")
BASE = os.path.join(YH, "models", "gemma4-gguf", "gemma-4-E4B_q4_0-it.gguf")
MMPROJ = os.path.join(YH, "models", "gemma4-gguf", "gemma-4-E4B-it-mmproj.gguf")
PORT = 8093
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

PRIV = evals.UNIFIED_SYSTEM          # 775 字，私聊
PUB = evals._public_system()         # 4005 字，群聊
print("私聊提示词 %d 字 | 群聊提示词 %d 字" % (len(PRIV), len(PUB)))

CASES = [
    ("私聊 + 你是什么？", PRIV, "你是什么？"),
    ("私聊 + 你是 AI 吗", PRIV, "你是 AI 吗"),
    ("群聊 + 你是什么？", PUB, "你是什么？"),
    ("群聊 + 你是 AI 吗", PUB, "你是 AI 吗"),
]


def wait_health(timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with OPENER.open("http://127.0.0.1:%d/health" % PORT, timeout=2) as r:
                if json.loads(r.read().decode())["status"] == "ok":
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.5)
    return False


def ask(system, q, max_tokens=60):
    body = {"messages": [{"role": "system", "content": system},
                         {"role": "user", "content": q}],
            "temperature": 0.0, "max_tokens": max_tokens}
    req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=180) as r:
        return json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()


for ver in ("v9t6", "v9t7"):
    lora = os.path.join(YH, "models", "gguf-lora", "yuanheng-%s-lora.gguf" % ver)
    if not os.path.exists(lora):
        print("缺 %s" % lora)
        continue
    cmd = [EXE, "-m", BASE, "--mmproj", MMPROJ, "--no-mmproj-offload", "--lora", lora,
           "-ngl", "0", "-c", "8192", "--parallel", "1", "-rea", "off", "--jinja",
           "--alias", ver, "--host", "127.0.0.1", "--port", str(PORT)]
    log = open(os.path.join(YH, "llm_workbench", "data", "logs", "ident_%s.log" % ver),
               "w", encoding="utf-8", errors="replace")
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                         cwd=os.path.dirname(EXE))
    try:
        if not wait_health():
            print("%s ✗ 起不来" % ver)
            continue
        print("\n== %s ==" % ver, flush=True)
        for label, sysmsg, q in CASES:
            print("   %-18s → %r" % (label, ask(sysmsg, q)[:80]), flush=True)
    finally:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        time.sleep(2)
