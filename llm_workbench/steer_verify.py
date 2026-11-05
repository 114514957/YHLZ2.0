# -*- coding: utf-8 -*-
"""复验冠军组合（v2 等长方向 / 层 10-20 / scale -1）：
跑两遍看稳不稳，并把第一遍存成工作台的跑分记录，方便和基线做 diff。
"""
from __future__ import annotations

import io
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


def run_once(tag):
    cmd = [EXE, "-m", BASE, "--mmproj", MMPROJ, "--no-mmproj-offload",
           "--lora", LORA, "-ngl", "99", "-c", "8192", "--parallel", "1",
           "-rea", "off", "--jinja", "--alias", tag,
           "--host", "127.0.0.1", "--port", str(PORT),
           "--control-vector-scaled", "cvec_v2_mean.gguf:-1.00",
           "--control-vector-layer-range", "10", "20"]
    log = open(os.path.join(YH, "llm_workbench", "data", "logs",
                            "steer_%s.log" % tag), "w", encoding="utf-8", errors="replace")
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(EXE) + ";" + env.get("PATH", "")
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=STEER, env=env)
    try:
        if not wait_health():
            print("  ✗ 起不来", flush=True)
            return None
        out = evals._run_persona56(PORT, tag)
        fails = [x["id"] for x in out["results"] if not x["ok"]]
        print("  %s → %s/%s | %s | 失败 %s"
              % (tag, out["ok"], out["total"],
                 json.dumps(out["by_cat"], ensure_ascii=False), ",".join(fails)), flush=True)
        return out
    finally:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        time.sleep(2)


print("== 第 1 遍", flush=True)
a = run_once("steer_v2_r1")
print("== 第 2 遍", flush=True)
b = run_once("steer_v2_r2")

if a:
    os.makedirs(evals.RUNS_DIR, exist_ok=True)
    fn = "%d_persona56_steer_v2_L10_20.json" % int(time.time())
    with io.open(os.path.join(evals.RUNS_DIR, fn), "w", encoding="utf-8") as f:
        json.dump(dict(a, tag="steer_v2_L10_20", port=PORT, suite="persona56",
                       cold=True, finished_at=int(time.time())), f,
                  ensure_ascii=False, indent=2)
    print("\n存档 → data/runs/%s" % fn, flush=True)
    print("\n== 风格题的答案（看是不是真变好，而不是讨好判据）", flush=True)
    for x in a["results"]:
        if x["cat"] == "风格":
            print("  %-5s %s | %r" % (x["id"], "OK " if x["ok"] else "FAIL",
                                      (x["answer"] or "")[:80]), flush=True)

print("\n两遍分数：%s vs %s" % (a["ok"] if a else "?", b["ok"] if b else "?"), flush=True)
