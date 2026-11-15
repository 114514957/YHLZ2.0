# -*- coding: utf-8 -*-
"""v14：上传 → 训练 → 拉 adapter（分块并发）→ 转 GGUF → 评测 → 对拍。

一条龙，每步都打印关键行。
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
HOST, PORT, USER, PWD = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
REMOTE_DIR = "/root/yh/material_v14"
ADAPTER_REMOTE = "/root/autodl-tmp/models/lora/yuanheng-v14"
LOCAL_ADAPTER = os.path.join(ROOT, "models", "lora", "yuanheng-v14")
GGUF_OUT = os.path.join(ROOT, "models", "gguf-lora", "yuanheng-v14-lora.gguf")


def conn() -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PWD, timeout=40)
    return c


cli = conn()


def sh(cmd: str, timeout: int = 300) -> str:
    _i, o, e = cli.exec_command(cmd, timeout=timeout)
    return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")


# 1) 上传素材 + 训练器 + 配置
print("=== 上传 ===")
sftp = cli.open_sftp()
sh("mkdir -p %s" % REMOTE_DIR)
ups = [
    (os.path.join(ROOT, "dist", "material_v14", "sft_persona_v14_train.jsonl"), "train.jsonl"),
    (os.path.join(ROOT, "dist", "material_v14", "sft_persona_v14_val.jsonl"), "val.jsonl"),
    (os.path.join(ROOT, "dist", "material_v13", "train_v13.py"), "train_v13.py"),
    (os.path.join(ROOT, "dist", "material_v14", "config", "finetune.gemma4.v14.json"), "cfg.json"),
]
for local, name in ups:
    sftp.put(local, "%s/%s" % (REMOTE_DIR, name))
    print("   %-14s %.1f MB" % (name, os.path.getsize(local) / 1048576))
sftp.close()
print(sh("cd %s && ls -la | tail -5" % REMOTE_DIR))

# 2) 训练
print("\n=== 启动 v14 训练 ===")
print(sh("cd %s && rm -f v14.log && setsid nohup /root/miniconda3/bin/python -u "
         "train_v13.py --config cfg.json > v14.log 2>&1 < /dev/null & sleep 3; echo started"
         % REMOTE_DIR))

deadline = time.time() + 2700
while time.time() < deadline:
    log = sh("tail -c 1200 %s/v14.log" % REMOTE_DIR, 60)
    steps = [int(x) for x in __import__("re").findall(r"(\d+)/706", log)]
    if "train_runtime" in log:
        print("训练完成 ✅")
        for ln in log.splitlines():
            if any(k in ln for k in ("train_runtime", "总步数", "gradcheck")):
                print("   " + ln.strip()[:130])
        break
    if "Traceback" in log:
        print("训练报错：\n" + log[-900:])
        sys.exit(1)
    if steps:
        print("   进度 %d/706" % steps[-1], flush=True)
    time.sleep(90)

# 3) 分块并发拉 adapter
print("\n=== 拉 adapter（分块并发）===")
RDIR = "/root/yh/v14_chunks"
print(sh("set -e; mkdir -p %s; rm -f %s/part_*; split -b %d -d -a 3 "
         "%s/adapter_model.safetensors %s/part_; ls %s | wc -l"
         % (RDIR, RDIR, 8 * 1024 * 1024, ADAPTER_REMOTE, RDIR, RDIR)))
parts = [x.strip() for x in sh("ls %s | sort" % RDIR).splitlines()
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
        sf.get("%s/%s" % (RDIR, name), lp)
        sf.close()
    finally:
        c.close()
    return name


with cf.ThreadPoolExecutor(max_workers=8) as ex:
    list(ex.map(fetch, parts))
os.makedirs(LOCAL_ADAPTER, exist_ok=True)
h = hashlib.sha256()
with open(os.path.join(LOCAL_ADAPTER, "adapter_model.safetensors"), "wb") as out:
    for name in parts:
        with open(os.path.join(local_chunks, name), "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                out.write(chunk)
                h.update(chunk)
sftp = cli.open_sftp()
sftp.get("%s/adapter_config.json" % ADAPTER_REMOTE,
         os.path.join(LOCAL_ADAPTER, "adapter_config.json"))
sftp.close()
remote_sha = sh("sha256sum %s/adapter_model.safetensors | cut -d' ' -f1" % ADAPTER_REMOTE).strip()
print("sha256：本地 %s" % h.hexdigest()[:16])
print("        云端 %s" % remote_sha[:16])
print("校验：%s" % ("✅" if h.hexdigest() == remote_sha else "❌"))
cli.close()

# 4) 转 GGUF
print("\n=== 转 GGUF ===")
r = subprocess.run([PY, os.path.join(ROOT, "experiments", "convert_v13_gguf.py")],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
print((r.stdout or "")[-400:])
print("\nv14 流水线完成。下一步：起 8094 端口评测。")
