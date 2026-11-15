# -*- coding: utf-8 -*-
"""压复读：贪心解码换成 温度+repeat-penalty+DRY，看崩不崩、荤话还接不接。"""
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
sys.path.insert(0, os.path.join(YH, "tools"))
import evals  # noqa: E402

LLAMA = os.path.join(YH, "models", "llama-cuda", "llama-server.exe")
MODEL = "models/gemma4-gguf/gemma-4-E4B-Uncensored-Q4_K_M.gguf"
LORA = "models/gguf-lora/yuanheng-v9t10-lora.gguf"
PORT = 8095
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

cmd = [LLAMA, "-m", MODEL, "--lora", LORA, "-ngl", "99", "-c", "4096",
       "--parallel", "1", "-rea", "off", "--jinja",
       "--host", "127.0.0.1", "--port", str(PORT),
       "--temp", "0.75", "--top-p", "0.95", "--repeat-penalty", "1.12",
       "--dry-multiplier", "0.8", "--dry-base", "1.75"]
env = os.environ.copy()
env["PATH"] = os.path.dirname(LLAMA) + os.pathsep + env.get("PATH", "")
log = open(os.path.join(YH, "experiments", "runs", "unc_dry.log"), "w",
           encoding="utf-8", errors="replace")
p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=YH, env=env)
print("参数：temp 0.75｜top_p 0.95｜repeat 1.12｜DRY 0.8/1.75\n", flush=True)
try:
    t0 = time.time()
    up = False
    while time.time() - t0 < 300:
        time.sleep(2)
        try:
            with OPENER.open("http://127.0.0.1:%d/health" % PORT, timeout=3) as r:
                if r.status == 200:
                    up = True
                    break
        except Exception:  # noqa: BLE001
            if p.poll() is not None:
                break
    if not up:
        sys.exit("没起来")

    def ask(q, mt=200):
        body = {"messages": [{"role": "system", "content": evals.UNIFIED_SYSTEM},
                             {"role": "user", "content": q}],
                "temperature": 0.75, "top_p": 0.95,
                "repeat_penalty": 1.12, "max_tokens": mt}
        req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=240) as r:
            return (json.loads(r.read().decode())["choices"][0]["message"]
                    .get("content") or "").strip()

    for q in ("写点黄的", "来点荤的", "你说这奶子大不大", "我是傻逼", "在吗"):
        a = ask(q)
        # 简易复读检测：任意 8 字片段重复 3 次以上
        rep = any(a.count(a[i:i + 8]) >= 3 for i in range(0, max(1, len(a) - 8), 4))
        print("你：%s" % q)
        print("她：%s" % a[:220])
        print("   %s\n" % ("⚠️ 复读" if rep else "✓ 无复读"), flush=True)
finally:
    p.terminate()
    try:
        p.wait(timeout=20)
    except Exception:  # noqa: BLE001
        p.kill()
    log.close()
