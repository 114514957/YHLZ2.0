# -*- coding: utf-8 -*-
"""符号检验：+3 让答案变长（216 字），那 -1 / -3 会不会变短、分数会不会回去？

如果 -3 明显短于基线、且分数不低于基线，说明方向本身有效，只是符号反了。
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


def run_case(tag, scale):
    cmd = [EXE, "-m", BASE, "--mmproj", MMPROJ, "--no-mmproj-offload",
           "--lora", LORA, "-ngl", "99", "-c", "8192", "--parallel", "1",
           "-rea", "off", "--jinja", "--alias", tag,
           "--host", "127.0.0.1", "--port", str(PORT),
           "--control-vector-scaled", "cvec_style_mean.gguf:%.2f" % scale,
           "--control-vector-layer-range", "10", "41"]
    log = open(os.path.join(YH, "llm_workbench", "data", "logs",
                            "steer_%s.log" % tag), "w", encoding="utf-8", errors="replace")
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(EXE) + ";" + env.get("PATH", "")
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=STEER, env=env)
    try:
        if not wait_health():
            print("  %s ✗ 起不来" % tag, flush=True)
            return
        if scale < 0:
            # 先看一眼能不能说话
            body = {"messages": [{"role": "user", "content": "在吗"}],
                    "temperature": 0.0, "max_tokens": 40}
            req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                         data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with OPENER.open(req, timeout=120) as r:
                print("  探针 在吗 → %r" % json.loads(r.read().decode())
                      ["choices"][0]["message"]["content"], flush=True)
        t0 = time.time()
        out = evals._run_persona56(PORT, tag)
        el = time.time() - t0
        fails = [x["id"] for x in out["results"] if not x["ok"]]
        lens = [len(x["answer"]) for x in out["results"] if x.get("answer")]
        print("  %-12s %s/%s | %s | %.0fs | 均长 %.0f 字 | 失败 %s"
              % (tag, out["ok"], out["total"],
                 json.dumps(out["by_cat"], ensure_ascii=False), el,
                 sum(lens) / max(1, len(lens)), ",".join(fails)), flush=True)
    finally:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        time.sleep(2)


print("== scale=-1.0", flush=True)
run_case("steer_n1", -1.0)
print("\n== scale=-3.0", flush=True)
run_case("steer_n3", -3.0)
