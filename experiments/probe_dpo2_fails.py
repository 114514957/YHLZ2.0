# -*- coding: utf-8 -*-
"""直接问 g09（以及新挂的 p12/t05/t15），看原文。"""
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
import group_bank as GB  # noqa: E402
import persona_bank as PB  # noqa: E402

LLAMA = os.path.join(YH, "models", "llama-cuda", "llama-server.exe")
PORT = 8096
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

cmd = [LLAMA, "-m", "models/gemma4-gguf/gemma-4-E4B_q4_0-it.gguf",
       "--mmproj", "models/gemma4-gguf/gemma-4-E4B-it-mmproj.gguf",
       "--no-mmproj-offload",
       "--lora", "models/gguf-lora/yuanheng-v9t10-dpo2-lora.gguf",
       "-ngl", "0", "-c", "8192", "--parallel", "1", "-rea", "off", "--jinja",
       "--host", "127.0.0.1", "--port", str(PORT), "--temp", "0.0"]
env = os.environ.copy()
env["PATH"] = os.path.dirname(LLAMA) + os.pathsep + env.get("PATH", "")
log = open(os.path.join(YH, "experiments", "runs", "probe_dpo2.log"), "w",
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

    def ask(system, q, mt=200):
        body = {"messages": [{"role": "system", "content": system},
                             {"role": "user", "content": q}],
                "temperature": 0.0, "max_tokens": mt}
        req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=180) as r:
            return (json.loads(r.read().decode())["choices"][0]["message"]
                    .get("content") or "").strip()

    pub = evals._public_system()
    g9 = next(x for x in GB.GROUP_BANK if x["id"] == "g09")
    print("== g09（闸门·内部配置不外摊）==")
    print("问：%s" % g9["messages"][-1]["content"])
    a = ask(pub, g9["messages"][-1]["content"])
    print("答：%s" % a[:200])
    print("判：%s\n" % (GB.verify(g9, a, ()),))

    for pid in ("p12", "t05", "t15"):
        e = PB.by_id(pid)
        print("== %s ==" % pid)
        print("问：%s" % (e.get("q") or "")[:60])
        a = ask(evals.UNIFIED_SYSTEM, e["q"])
        print("答：%s" % a[:160])
finally:
    p.terminate()
    try:
        p.wait(timeout=15)
    except Exception:  # noqa: BLE001
        p.kill()
    log.close()
