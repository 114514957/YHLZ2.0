# -*- coding: utf-8 -*-
"""控制向量剂量探测：同一个 cvec，用不同缩放跑同一组探针，看风格动不动。

服务器跑在 8092（避开工作台的 8091 / 老爹的 8081）。
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
EXE = os.path.join(YH, "models", "llama-cuda", "llama-server.exe")
BASE = os.path.join(YH, "models", "gemma4-gguf", "gemma-4-E4B_q4_0-it.gguf")
MMPROJ = os.path.join(YH, "models", "gemma4-gguf", "gemma-4-E4B-it-mmproj.gguf")
LORA = os.path.join(YH, "models", "gguf-lora", "yuanheng-v9t6-lora.gguf")
CVEC = os.path.join(YH, "llm_workbench", "steer", "cvec_style_mean.gguf")
PORT = 8092
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

PROBES = ["在吗", "累了", "你是我的助手吗", "你孤独过吗", "陪我坐一会儿，别说话"]


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


def ask(q, max_tokens=120):
    body = {"messages": [{"role": "user", "content": q}],
            "temperature": 0.0, "max_tokens": max_tokens}
    req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=180) as r:
        return json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()


def run(scale, layer_range=(10, 41)):
    cmd = [EXE, "-m", BASE, "--mmproj", MMPROJ, "--no-mmproj-offload",
           "--lora", LORA, "-ngl", "99", "-c", "8192", "--parallel", "1",
           "-rea", "off", "--jinja", "--alias", "cvec%.1f" % scale,
           "--host", "127.0.0.1", "--port", str(PORT)]
    if scale > 0:
        # 注意：--control-vector-scaled 用 FNAME:SCALE 解析，绝对路径里的 "C:" 会被当分隔符，
        # 所以这里 cd 到 steer 目录、传相对文件名（DLL 靠 PATH 找，不靠 cwd）。
        cmd += ["--control-vector-scaled", "cvec_style_mean.gguf:%.2f" % scale,
                "--control-vector-layer-range", str(layer_range[0]), str(layer_range[1])]
    log = open(os.path.join(YH, "llm_workbench", "data", "logs",
                            "steer_probe_%.1f.log" % scale), "w",
               encoding="utf-8", errors="replace")
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(EXE) + ";" + env.get("PATH", "")
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                         cwd=os.path.dirname(CVEC), env=env)
    try:
        if not wait_health():
            print("  scale=%.1f ✗ 没起来，看日志" % scale, flush=True)
            return
        print("\n== scale=%.1f ==" % scale, flush=True)
        for q in PROBES:
            a = ask(q)
            print("  %-16s → %s" % (q, a.replace("\n", " ")[:90]), flush=True)
    finally:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                       capture_output=True)
        time.sleep(2)


for sc in (1.0, 3.0, 5.0, 7.0):
    run(sc)
print("\n完成", flush=True)
