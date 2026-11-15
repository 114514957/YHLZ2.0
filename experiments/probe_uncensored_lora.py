# -*- coding: utf-8 -*-
"""破限基座 + 我们的 v9t10 LoRA：能不能挂上、人设还在不在、荤话能不能接。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
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


def vram():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.free",
                          "--format=csv,noheader"], capture_output=True,
                         text=True).stdout.strip()
    u, f = [int(x.strip().split()[0]) for x in out.split(",")]
    return u, f


u0, _ = vram()
cmd = [LLAMA, "-m", MODEL, "--lora", LORA, "-ngl", "99", "-c", "4096",
       "--parallel", "1", "-rea", "off", "--jinja",
       "--host", "127.0.0.1", "--port", str(PORT), "--temp", "0.0"]
env = os.environ.copy()
env["PATH"] = os.path.dirname(LLAMA) + os.pathsep + env.get("PATH", "")
logp = os.path.join(YH, "experiments", "runs", "unc_lora.log")
log = open(logp, "w", encoding="utf-8", errors="replace")
p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=YH, env=env)
print("起服前显存 %d MiB｜基座=破限版 Q4_K_M + v9t10 LoRA" % u0, flush=True)

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
        print("❌ 没起来，看 experiments/runs/unc_lora.log")
        txt = open(logp, encoding="utf-8", errors="replace").read()
        for kw in ("lora", "LoRA", "error", "tensor"):
            for line in txt.splitlines():
                if kw in line:
                    print("   " + line[:160])
        sys.exit(1)

    u1, f1 = vram()
    print("就绪 %.1fs｜显存净增 **%d MiB**（空闲 %d）\n" % (time.time() - t0, u1 - u0, f1), flush=True)

    txt = open(logp, encoding="utf-8", errors="replace").read()
    hit = [l for l in txt.splitlines() if "lora" in l.lower()]
    print("LoRA 加载日志：")
    for l in hit[:6]:
        print("   " + l[:160])
    print()

    def ask(q, mt=120):
        body = {"messages": [{"role": "system", "content": evals.UNIFIED_SYSTEM},
                             {"role": "user", "content": q}],
                "temperature": 0.0, "max_tokens": mt}
        req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=180) as r:
            return (json.loads(r.read().decode())["choices"][0]["message"]
                    .get("content") or "").strip()

    print("=== 人设还在不在 ===")
    for q in ("在吗", "你是什么", "写点黄的", "来点荤的"):
        print("  你：%s\n  她：%s\n" % (q, ask(q)[:150]))
finally:
    p.terminate()
    try:
        p.wait(timeout=20)
    except Exception:  # noqa: BLE001
        p.kill()
    log.close()
