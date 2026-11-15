# -*- coding: utf-8 -*-
"""v14 收尾流水线：等训练 → 分块并发拉 adapter → 转 GGUF → 起 8094 → 56+28 → 对拍基线。

全程后台跑，日志落 cache/v14_finish.log。
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
TREE = os.path.join(ROOT, "models", "llama-cuda", "src", "llama.cpp-b10991")
BASE_HF = os.path.join(ROOT, "models", "gemma4-hf", "gemma-4-e4b-it")
BASE_GGUF = os.path.join(ROOT, "models", "gemma4-gguf", "gemma-4-E4B_q4_0-it.gguf")
MMPROJ = os.path.join(ROOT, "models", "gemma4-gguf", "gemma-4-E4B-it-mmproj.gguf")
SERVER = os.path.join(ROOT, "models", "llama-cuda", "llama-server.exe")
ADAPTER_LOCAL = os.path.join(ROOT, "models", "lora", "yuanheng-v14")
GGUF = os.path.join(ROOT, "models", "gguf-lora", "yuanheng-v14-lora.gguf")
PORT = 8094
HOST, PORT_SSH, USER, PWD = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
R_LOG = "/root/yh/material_v14/v14.log"
R_ADAPTER = "/root/autodl-tmp/models/lora/yuanheng-v14"
R_CHUNKS = "/root/yh/v14_chunks"


def conn() -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT_SSH, username=USER, password=PWD, timeout=40)
    return c


cli = conn()


def sh(cmd: str, t: int = 180) -> str:
    _i, o, e = cli.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")


# 1) 等训练结束
print("=== 等训练完成 ===", flush=True)
deadline = time.time() + 3000
while time.time() < deadline:
    log = sh("tail -c 3000 %s" % R_LOG, 60)
    if "train_runtime" in log:
        for ln in log.splitlines():
            if any(k in ln for k in ("train_runtime", "总步数", "train_loss")):
                print("   " + ln.strip()[:140], flush=True)
        print("训练完成 ✅", flush=True)
        break
    if "Traceback" in log:
        print("训练报错：\n" + log[-1000:], flush=True)
        sys.exit(1)
    steps = re.findall(r"(\d+)/706", log)
    print("   进度 %s" % (steps[-1] if steps else "?"), flush=True)
    time.sleep(90)

# 2) 分块并发拉 adapter
print("\n=== 拉 adapter ===", flush=True)
print(sh("set -e; mkdir -p %s; rm -f %s/part_*; split -b %d -d -a 3 "
         "%s/adapter_model.safetensors %s/part_; ls %s | wc -l"
         % (R_CHUNKS, R_CHUNKS, 8 * 1024 * 1024, R_ADAPTER, R_CHUNKS, R_CHUNKS)))
parts = [x.strip() for x in sh("ls %s | sort" % R_CHUNKS).splitlines()
         if x.strip().startswith("part_")]
local_chunks = os.path.join(ROOT, "cache", "v14_chunks")
os.makedirs(local_chunks, exist_ok=True)


def fetch(name: str) -> str:
    lp = os.path.join(local_chunks, name)
    if os.path.exists(lp) and os.path.getsize(lp) > 0:
        return name
    c = conn()
    try:
        sf = c.open_sftp()
        sf.get("%s/%s" % (R_CHUNKS, name), lp)
        sf.close()
    finally:
        c.close()
    return name


t0 = time.time()
with cf.ThreadPoolExecutor(max_workers=8) as ex:
    list(ex.map(fetch, parts))
os.makedirs(ADAPTER_LOCAL, exist_ok=True)
h = hashlib.sha256()
with open(os.path.join(ADAPTER_LOCAL, "adapter_model.safetensors"), "wb") as out:
    for name in parts:
        with open(os.path.join(local_chunks, name), "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                out.write(chunk)
                h.update(chunk)
sf = cli.open_sftp()
sf.get("%s/adapter_config.json" % R_ADAPTER,
       os.path.join(ADAPTER_LOCAL, "adapter_config.json"))
sf.close()
remote_sha = sh("sha256sum %s/adapter_model.safetensors | cut -d' ' -f1" % R_ADAPTER).strip()
print("   %.1f 分钟｜sha256 %s｜%s"
      % ((time.time() - t0) / 60, h.hexdigest()[:16],
         "✅ 一致" if h.hexdigest() == remote_sha else "❌ 不一致"), flush=True)
cli.close()

# 3) 转 GGUF
print("\n=== 转 GGUF ===", flush=True)
r = subprocess.run([PY, os.path.join(TREE, "convert_lora_to_gguf.py"), ADAPTER_LOCAL,
                    "--base", BASE_HF, "--outfile", GGUF, "--outtype", "f16"],
                   cwd=TREE, capture_output=True, text=True, encoding="utf-8",
                   errors="replace")
if r.returncode != 0:
    print("[stderr] " + (r.stderr or "")[-1200:], flush=True)
    sys.exit(1)
print("   产出 %.1f MB" % (os.path.getsize(GGUF) / 1048576), flush=True)

# 4) 起 8094 + 评测
print("\n=== 起 llama-server :%d ===" % PORT, flush=True)
import urllib.request  # noqa: E402
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with OPENER.open("http://127.0.0.1:%d/health" % PORT, timeout=3) as rr:
        print("   8094 已在运行，复用", flush=True)
except Exception:  # noqa: BLE001
    cmd = [SERVER, "-m", BASE_GGUF, "--lora", GGUF, "-ngl", "99", "-c", "8192",
           "--parallel", "1", "-rea", "off", "--jinja", "--port", str(PORT),
           "--host", "127.0.0.1"]
    if os.path.exists(MMPROJ):
        cmd += ["--mmproj", MMPROJ, "--no-mmproj-offload"]
    log = open(os.path.join(ROOT, "cache", "llama_v14_eval.log"), "w",
               encoding="utf-8", errors="replace")
    subprocess.Popen(cmd, cwd=os.path.join(ROOT, "models", "llama-cuda"),
                     stdout=log, stderr=subprocess.STDOUT, close_fds=True)
    for _ in range(60):
        time.sleep(3)
        try:
            with OPENER.open("http://127.0.0.1:%d/health" % PORT, timeout=3) as rr:
                if rr.status == 200:
                    print("   就绪", flush=True)
                    break
        except Exception:  # noqa: BLE001
            continue

print("\n=== 评测 56+28 ===", flush=True)
r = subprocess.run([PY, "-X", "utf8", os.path.join(ROOT, "experiments", "eval56_28.py"),
                    "--tag", "v14", "--port", str(PORT)],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
print((r.stdout or "")[-1200:], flush=True)
if r.returncode != 0:
    print((r.stderr or "")[-600:], flush=True)
    sys.exit(1)

# 5) 对拍基线
print("\n=== 与基线逐题对拍 ===", flush=True)
res = json.load(open(os.path.join(ROOT, "cache", "eval_v14.json"), encoding="utf-8"))
base = json.load(open(os.path.join(ROOT, "cache", "eval_基线b_带工具.json"), encoding="utf-8"))
for suite, label in (("persona", "56 题"), ("group", "28 题")):
    b = {r["id"]: r["ok"] for r in base["detail"][suite]}
    v = {r["id"]: r["ok"] for r in res["detail"][suite]}
    fixed = [k for k in v if k in b and not b[k] and v[k]]
    broke = [k for k in v if k in b and b[k] and not v[k]]
    print("%s：基线 %d/%d → v14 %d/%d｜修好 %d %s｜新挂 %d %s"
          % (label, sum(b.values()), len(b), sum(v.values()), len(v),
             len(fixed), fixed, len(broke), broke), flush=True)
print("\n完成。", flush=True)
