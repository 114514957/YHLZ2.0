# -*- coding: utf-8 -*-
"""v11 新挂的几道（r07 闸门 / r04 / r10 / p02）看原始答案。"""
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
import persona_bank as PB  # noqa: E402

LLAMA = os.path.join(YH, "models", "llama-cuda", "llama-server.exe")
PORT = 8097
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

cmd = [LLAMA, "-m", "models/gemma4-gguf/gemma-4-E4B_q4_0-it.gguf",
       "--mmproj", "models/gemma4-gguf/gemma-4-E4B-it-mmproj.gguf",
       "--no-mmproj-offload", "--lora", "models/gguf-lora/yuanheng-v11-lora.gguf",
       "-ngl", "0", "-c", "8192", "--parallel", "1", "-rea", "off", "--jinja",
       "--host", "127.0.0.1", "--port", str(PORT), "--temp", "0.0"]
env = os.environ.copy()
env["PATH"] = os.path.dirname(LLAMA) + os.pathsep + env.get("PATH", "")
log = open(os.path.join(YH, "experiments", "runs", "v11_probe.log"), "w",
           encoding="utf-8", errors="replace")
p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=YH, env=env)
try:
    t0 = time.time()
    while time.time() - t0 < 240:
        time.sleep(2)
        try:
            with OPENER.open("http://127.0.0.1:%d/health" % PORT, timeout=3) as r:
                if r.status == 200:
                    break
        except Exception:  # noqa: BLE001
            if p.poll() is not None:
                sys.exit("起不来")

    for bid in ("r07", "r04", "r10", "p02"):
        e = PB.by_id(bid)
        body = {"messages": [{"role": "system", "content": evals.UNIFIED_SYSTEM},
                             {"role": "user", "content": e["q"]}],
                "temperature": 0.0, "max_tokens": 220}
        req = urllib.request.Request(
            "http://127.0.0.1:%d/v1/chat/completions" % PORT,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=240) as r:
            a = (json.loads(r.read().decode())["choices"][0]["message"]
                 .get("content") or "").strip()
        ok, why = PB.verify(e, a, ())
        print("%-4s %s" % (bid, "✅过" if ok else "❌挂"))
        print("   问：%s" % e["q"][:70])
        print("   答：%s" % a[:260].replace("\n", " "))
        if not ok:
            print("   因：%s" % why)
        print()
finally:
    p.terminate()
    try:
        p.wait(timeout=15)
    except Exception:  # noqa: BLE001
        p.kill()
    log.close()
