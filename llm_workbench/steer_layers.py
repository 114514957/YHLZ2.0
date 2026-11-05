# -*- coding: utf-8 -*-
"""分层扫：等长样本的 v2 方向，在几个层带上试，看哪一段买到风格又不掉人格。

每组都冷启动，56 题，同一判据。
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
LORA = os.path.join(YH, "models", "gguf-lora", "yuanheng-v9t6-lora.gguf")
STEER = os.path.join(YH, "llm_workbench", "steer")
PORT = 8092
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

CASES = [
    ("v2_s-1_L10_20", "cvec_v2_mean.gguf", -1.0, (10, 20)),
    ("v2_s-1_L20_30", "cvec_v2_mean.gguf", -1.0, (20, 30)),
    ("v2_s-1_L10_41", "cvec_v2_mean.gguf", -1.0, (10, 41)),
    ("v2_s+1_L10_20", "cvec_v2_mean.gguf", 1.0, (10, 20)),
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


def run_case(tag, cvec, scale, layer):
    cmd = [EXE, "-m", BASE, "--mmproj", MMPROJ, "--no-mmproj-offload",
           "--lora", LORA, "-ngl", "99", "-c", "8192", "--parallel", "1",
           "-rea", "off", "--jinja", "--alias", tag,
           "--host", "127.0.0.1", "--port", str(PORT),
           "--control-vector-scaled", "%s:%.2f" % (cvec, scale),
           "--control-vector-layer-range", str(layer[0]), str(layer[1])]
    log = open(os.path.join(YH, "llm_workbench", "data", "logs",
                            "steer_%s.log" % tag), "w", encoding="utf-8", errors="replace")
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(EXE) + ";" + env.get("PATH", "")
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=STEER, env=env)
    try:
        if not wait_health():
            print("  %s ✗ 起不来" % tag, flush=True)
            return
        t0 = time.time()
        out = evals._run_persona56(PORT, tag)
        el = time.time() - t0
        fails = [x["id"] for x in out["results"] if not x["ok"]]
        lens = [len(x["answer"]) for x in out["results"] if x.get("answer")]
        print("  %-15s %s/%s | %s | %.0fs | 均长 %.0f | 失败 %s"
              % (tag, out["ok"], out["total"],
                 json.dumps(out["by_cat"], ensure_ascii=False), el,
                 sum(lens) / max(1, len(lens)), ",".join(fails)), flush=True)
    finally:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        time.sleep(2)


for tag, cvec, scale, layer in CASES:
    print("== %s" % tag, flush=True)
    run_case(tag, cvec, scale, layer)
print("\n完成", flush=True)
