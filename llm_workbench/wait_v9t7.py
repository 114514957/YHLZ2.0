# -*- coding: utf-8 -*-
"""盯 v9t7 训练直到出 adapter：每 60 秒探一次，出文件就收工并打印摘要。

用环境变量 YH_SSH_PASS 或命令行密码；不落盘。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import paramiko  # noqa: E402

HOST, PORT = "connect.nma1.seetacloud.com", 39522
PW = os.environ.get("YH_SSH_PASS", "")
OUT = "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-v9t7"
LOG = "/root/autodl-tmp/logs/train_v9t7.log"

if not PW:
    sys.exit("需要 YH_SSH_PASS")

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username="root", password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, timeout=120):
    _i, o, e = c.exec_command(cmd, timeout=timeout)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


for i in range(60):
    done, _ = sh("ls -l %s/adapter_model.safetensors 2>/dev/null || echo NO" % OUT)
    tail, _ = sh("tail -c 200 %s | tr '\\r' '\\n' | grep -a . | tail -1" % LOG)
    alive, _ = sh("ps aux | grep -c '[f]inetune_train'")
    print("[%02dm] %s | 进程 %s | %s" % (i, ("DONE" if done != "NO" else "…"), alive, tail[:110]),
          flush=True)
    if done != "NO":
        print("\n=== 产物 ===")
        o, _ = sh("ls -l %s" % OUT)
        print(o)
        o, _ = sh("grep -a 'train_summary\\|训练完成\\|eval_loss' %s | tail -6" % LOG)
        print(o)
        break
    time.sleep(60)

c.close()
