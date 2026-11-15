# -*- coding: utf-8 -*-
"""关卡前最后一次清点：把云端 v14 的小件产物全部拉回，并核对 adapter。"""
from __future__ import annotations

import hashlib
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(ROOT, "dist", "v14_产物")
os.makedirs(OUT, exist_ok=True)
REMOTE = "/root/autodl-tmp/models/lora/yuanheng-v14"
R_LOG = "/root/yh/material_v14"

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("connect.nma1.seetacloud.com", port=39522, username="root",
            password="FSMqu7B3fRXc", timeout=40)
sftp = cli.open_sftp()


def sh(cmd: str, t: int = 120) -> str:
    _i, o, e = cli.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")


pairs = [
    ("%s/adapter_config.json" % REMOTE, "adapter_config.json"),
    ("%s/train_log.csv" % REMOTE, "train_log.csv"),
    ("%s/train_summary.json" % REMOTE, "train_summary.json"),
    ("%s/train_summary.md" % REMOTE, "train_summary.md"),
    ("%s/README.md" % REMOTE, "adapter_README.md"),
    ("%s/v14.log" % R_LOG, "v14_训练日志.txt"),
    ("%s/smoke.log" % R_LOG, "smoke_冒烟日志.txt"),
    ("%s/cfg.json" % R_LOG, "cfg_used.json"),
    ("%s/train_v13.py" % R_LOG, "train_v13_used.py"),
]
print("=== 拉取小件 ===")
for remote, name in pairs:
    try:
        st = sftp.stat(remote)
        sftp.get(remote, os.path.join(OUT, name))
        print("   %-22s %8.1f KB" % (name, st.st_size / 1024))
    except Exception as ex:  # noqa: BLE001
        print("   ⚠ %-20s %s" % (name, ex))

# 核对 adapter（本地已有）
local_ad = os.path.join(ROOT, "models", "lora", "yuanheng-v14", "adapter_model.safetensors")
if os.path.exists(local_ad):
    h = hashlib.sha256()
    with open(local_ad, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    remote_sha = sh("sha256sum %s/adapter_model.safetensors | cut -d' ' -f1" % REMOTE).strip()
    print("\n=== adapter 核对 ===")
    print("   本地 %.1f MB｜sha256 %s" % (os.path.getsize(local_ad) / 1048576,
                                         h.hexdigest()[:20]))
    print("   云端          ｜sha256 %s" % remote_sha[:20])
    print("   %s" % ("✅ 一致，可以关卡" if h.hexdigest() == remote_sha else "❌ 不一致"))

# 列一下云端还有哪些大件（关了就没了）
print("\n=== 云端大件（关了就没了，确认不需要）===")
print(sh("du -sh %s /root/yh/material_v14 /root/yh/v14_chunks /root/autodl-tmp/retrain_pkg_gemma_v13.tar.gz "
         "/root/autodl-tmp/models/lora/yuanheng-v13 2>/dev/null" % REMOTE))
sftp.close()
cli.close()
