# -*- coding: utf-8 -*-
"""等 v13 训完 → 拉 adapter → 本地转 GGUF（不落云端转换）。

只用现成工具：models/llama-cuda/src/llama.cpp-b10991/convert_lora_to_gguf.py
"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
REMOTE_DIR = "/root/autodl-tmp/models/lora/yuanheng-v13"
LOCAL_DIR = os.path.join(ROOT, "models", "lora", "yuanheng-v13")

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("connect.nma1.seetacloud.com", port=39522, username="root",
            password="FSMqu7B3fRXc", timeout=30)


def sh(cmd: str, timeout: int = 120) -> str:
    _i, out, err = cli.exec_command(cmd, timeout=timeout)
    return out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")


# 1) 等训练结束
DEADLINE = time.time() + 1500
while time.time() < DEADLINE:
    log = sh("tail -c 1500 /root/yh/material_v13/v13.log", 60)
    if "train_runtime" in log:
        print("训练已结束 ✅")
        for ln in log.splitlines():
            if any(k in ln for k in ("train_runtime", "train_loss", "总步数", "eval_loss")):
                print("   " + ln.strip()[:120])
        break
    if "Traceback" in log:
        print("训练报错：\n" + log[-800:])
        sys.exit(1)
    time.sleep(45)
else:
    print("等待超时，仍在训练。先退出。")
    sys.exit(2)

# 2) 看产物
print("\n=== 产物 ===")
print(sh("ls -la %s | tail -8" % REMOTE_DIR))

# 3) 拉 adapter（只拉配置与权重）
os.makedirs(LOCAL_DIR, exist_ok=True)
sftp = cli.open_sftp()
for name in ("adapter_config.json", "adapter_model.safetensors"):
    remote = "%s/%s" % (REMOTE_DIR, name)
    local = os.path.join(LOCAL_DIR, name)
    try:
        st = sftp.stat(remote)
        sftp.get(remote, local)
        print("已拉 %-26s %.1f MB" % (name, st.st_size / 1048576))
    except Exception as ex:  # noqa: BLE001
        print("拉 %s 失败：%s" % (name, ex))
sftp.close()
cli.close()
