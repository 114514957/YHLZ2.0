# -*- coding: utf-8 -*-
"""把训练包上传到云端，方便老爹从 AutoDL 网盘直接下载；并列出云端可取的文件清单。"""
from __future__ import annotations

import hashlib
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
LOCAL_PKG = os.path.join(ROOT, "dist", "retrain_pkg_gemma_v13.tar.gz")
REMOTE_PKG = "/root/autodl-tmp/retrain_pkg_gemma_v13.tar.gz"

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("connect.nma1.seetacloud.com", port=39522, username="root",
            password="FSMqu7B3fRXc", timeout=40)
sftp = cli.open_sftp()


def sh(cmd: str, timeout: int = 120) -> str:
    _i, o, e = cli.exec_command(cmd, timeout=timeout)
    return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")


print("上传训练包（%.1f MB）→ %s" % (os.path.getsize(LOCAL_PKG) / 1048576, REMOTE_PKG))
sftp.put(LOCAL_PKG, REMOTE_PKG)

h = hashlib.sha256(open(LOCAL_PKG, "rb").read()).hexdigest()
r = sh("sha256sum %s | cut -d' ' -f1" % REMOTE_PKG).strip()
print("本地 sha256：%s" % h)
print("云端 sha256：%s" % r)
print("校验：%s" % ("✅ 一致" if h == r else "❌ 不一致"))

print("\n=== 云端可取文件清单 ===")
print(sh("ls -la /root/autodl-tmp/models/lora/yuanheng-v13/adapter_* "
         "/root/autodl-tmp/retrain_pkg_gemma_v13.tar.gz 2>/dev/null; "
         "echo '--- 训练日志与摘要 ---'; "
         "ls -la /root/autodl-tmp/models/lora/yuanheng-v13/{train_log.csv,train_summary.json,README.md} "
         "2>/dev/null; echo '--- 素材目录 ---'; ls -la /root/yh/material_v13 | head -12"))
sftp.close()
cli.close()
