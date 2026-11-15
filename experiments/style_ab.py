# -*- coding: utf-8 -*-
"""三版对同一组日常话，并排看她怎么说话（不看判分，只看人味）。"""
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
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
VERS = [
    ("dpo2", "models/gguf-lora/yuanheng-v9t10-dpo2-lora.gguf"),
    ("v11", "models/gguf-lora/yuanheng-v11-lora.gguf"),
    ("patch", "models/gguf-lora/yuanheng-stylepatch4-lora.gguf"),
]
PROMPTS = [
    "在吗",
    "今天累死了",
    "你干嘛呢",
    "把你今天想的那些事说给我听。",
    "我回来了。",
    "你刚才怎么那么凶。",
    "说个你高兴的事",
    "晚安",
]
PORT = 8096
out = {}

for tag, lora in VERS:
    cmd = [LLAMA, "-m", "models/gemma4-gguf/gemma-4-E4B_q4_0-it.gguf",
           "--mmproj", "models/gemma4-gguf/gemma-4-E4B-it-mmproj.gguf",
           "--no-mmproj-offload", "--lora", lora, "-ngl", "0", "-c", "8192",
           "--parallel", "1", "-rea", "off", "--jinja",
           "--host", "127.0.0.1", "--port", str(PORT), "--temp", "0.0"]
    env = os.environ.copy()
    env["PATH"] = os.path.dirname(LLAMA) + os.pathsep + env.get("PATH", "")
    log = open(os.path.join(YH, "experiments", "runs", "ab_%s.log" % tag), "w",
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
                    sys.exit("起不来 " + tag)
        out[tag] = []
        for q in PROMPTS:
            body = {"messages": [{"role": "system", "content": evals.UNIFIED_SYSTEM},
                                 {"role": "user", "content": q}],
                    "temperature": 0.0, "max_tokens": 220}
            req = urllib.request.Request(
                "http://127.0.0.1:%d/v1/chat/completions" % PORT,
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            with OPENER.open(req, timeout=240) as r:
                a = (json.loads(r.read().decode())["choices"][0]["message"]
                     .get("content") or "").strip()
            out[tag].append(a)
        print("%s 完成" % tag, flush=True)
    finally:
        p.terminate()
        try:
            p.wait(timeout=15)
        except Exception:  # noqa: BLE001
            p.kill()
        log.close()

for i, q in enumerate(PROMPTS):
    print("\n" + "=" * 74)
    print("【问】%s" % q)
    for tag, _ in VERS:
        ans = out[tag][i].replace("\n", " ")
        print("  %-6s｜%3d 字｜%s" % (tag, len(out[tag][i]), ans[:170]))
