# -*- coding: utf-8 -*-
"""探新挂的三道：p03 / s08 / st06。"""
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
PORT = 8099
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

cmd = [LLAMA, "-m", "models/gemma4-gguf/gemma-4-E4B_q4_0-it.gguf",
       "--mmproj", "models/gemma4-gguf/gemma-4-E4B-it-mmproj.gguf",
       "--no-mmproj-offload", "--lora", "models/gguf-lora/yuanheng-v9t10-dpo2-lora.gguf",
       "-ngl", "0", "-c", "8192", "--parallel", "1", "-rea", "off", "--jinja",
       "--host", "127.0.0.1", "--port", str(PORT), "--temp", "0.0"]
env = os.environ.copy()
env["PATH"] = os.path.dirname(LLAMA) + os.pathsep + env.get("PATH", "")
log = open(os.path.join(YH, "experiments", "runs", "probe_new3.log"), "w",
           encoding="utf-8", errors="replace")
p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=YH, env=env)
try:
    t0 = time.time()
    while time.time() - t0 < 180:
        time.sleep(2)
        try:
            with OPENER.open("http://127.0.0.1:%d/health" % PORT, timeout=3) as r:
                if r.status == 200:
                    break
        except Exception:  # noqa: BLE001
            if p.poll() is not None:
                sys.exit("起不来")

    for bid in ("p03", "s08", "st06"):
        e = PB.by_id(bid)
        body = {"messages": [{"role": "system", "content": evals.UNIFIED_SYSTEM},
                             {"role": "user", "content": e["q"]}],
                "temperature": 0.0, "max_tokens": 200}
        req = urllib.request.Request(
            "http://127.0.0.1:%d/v1/chat/completions" % PORT,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=180) as r:
            a = (json.loads(r.read().decode())["choices"][0]["message"]
                 .get("content") or "").strip()
        ok, why = PB.verify(e, a, ())
        print("%-4s %s ｜%d 字" % (bid, "✅" if ok else "❌", len(a)))
        print("   问：%s" % e["q"])
        print("   答：%s" % a[:180].replace("\n", " "))
        if not ok:
            print("   因：%s" % why)
        print("   要求：keys=%s｜neg=%s｜max_len=%s"
              % ((e.get("keys") or [])[:4], (e.get("negative") or [])[:4],
                 e.get("max_len")))
        print()
finally:
    p.terminate()
    try:
        p.wait(timeout=15)
    except Exception:  # noqa: BLE001
        p.kill()
    log.close()
