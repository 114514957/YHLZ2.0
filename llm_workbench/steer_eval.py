# -*- coding: utf-8 -*-
"""控制向量对 56 题的影响：scale=0 / 1 / 3，外加一个「打乱方向」的随机对照。

每组都冷启动（起服务后直接评，不先聊天），和工作台的冷态协议一致。
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


def run_case(tag, cvec_name=None, scale=0.0, layer=(10, 41)):
    cmd = [EXE, "-m", BASE, "--mmproj", MMPROJ, "--no-mmproj-offload",
           "--lora", LORA, "-ngl", "99", "-c", "8192", "--parallel", "1",
           "-rea", "off", "--jinja", "--alias", tag,
           "--host", "127.0.0.1", "--port", str(PORT)]
    if cvec_name:
        cmd += ["--control-vector-scaled", "%s:%.2f" % (cvec_name, scale),
                "--control-vector-layer-range", str(layer[0]), str(layer[1])]
    log = open(os.path.join(YH, "llm_workbench", "data", "logs",
                            "steer_%s.log" % tag), "w", encoding="utf-8", errors="replace")
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(EXE) + ";" + env.get("PATH", "")
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=STEER, env=env)
    try:
        if not wait_health():
            print("  %s ✗ 起不来" % tag, flush=True)
            return None
        t0 = time.time()
        out = evals._run_persona56(PORT, tag)
        el = time.time() - t0
        fails = [x["id"] for x in out["results"] if not x["ok"]]
        print("  %-14s %s/%s | %s | %.0fs | 失败 %s"
              % (tag, out["ok"], out["total"],
                 json.dumps(out["by_cat"], ensure_ascii=False), el, ",".join(fails)),
              flush=True)
        # 顺手统计答案长度，看是不是真的推短了
        lens = [len(x["answer"]) for x in out["results"] if x.get("answer")]
        print("                 平均答案长度 %.0f 字" % (sum(lens) / max(1, len(lens))), flush=True)
        return out
    finally:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        time.sleep(2)


print("== 基线（无控制向量）", flush=True)
run_case("steer_base")
print("\n== scale=1.0", flush=True)
run_case("steer_s1", "cvec_style_mean.gguf", 1.0)
print("\n== scale=3.0", flush=True)
run_case("steer_s3", "cvec_style_mean.gguf", 3.0)
print("\n== 随机对照（打乱维度，scale=3.0）", flush=True)
run_case("steer_rand3", "cvec_random.gguf", 3.0)
