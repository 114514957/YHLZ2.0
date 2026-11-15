# -*- coding: utf-8 -*-
"""等 stylepatch 训完 → 云端转 GGUF（66MB，比 139MB 小一半）→ 打包给老爹拉。"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
BASE = "/root/autodl-tmp/models/gemma-4-e4b-it"
ADP = "/root/autodl-tmp/models/lora/yuanheng-stylepatch4"
LOG = "/root/autodl-tmp/logs/train_stylepatch4.log"
GGUF = "/root/autodl-tmp/yuanheng-stylepatch4-lora.gguf"
PACK = "/root/autodl-tmp/pack_stylepatch4.tar.gz"

import paramiko  # noqa: E402


def conn():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
              banner_timeout=30, auth_timeout=30)
    return c


def q(c, cmd, t=1800):
    _i, o, e = c.exec_command(cmd, timeout=t)
    o.channel.settimeout(t - 5)
    try:
        return o.read().decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return ""


print("等训练结束…", flush=True)
for i in range(40):
    c = conn()
    n = q(c, "pgrep -cf '[f]inetune_train.py' || echo 0", t=60)
    tail = q(c, "tr -d '\\r' < %s | tail -c 150" % LOG, t=60)
    c.close()
    print("  %2d 轮｜进程 %s｜%s" % (i, n, tail.splitlines()[-1][:60] if tail else ""), flush=True)
    if n.strip() == "0":
        break
    time.sleep(45)

c = conn()
print("\n摘要：")
print(q(c, "tr -d '\\r' < %s | grep -aE '已保存|总步数' | tail -3" % LOG))
print(q(c, "ls -l %s/adapter_model.safetensors" % ADP))

print("\n转 GGUF：")
CONV = q(c, "ls /root/yh/convert_lora_to_gguf.py 2>/dev/null || echo NO", t=60)
print("  转换器：%s" % CONV)
if CONV.startswith("/"):
    print(q(c, "cd /root/yh && /root/miniconda3/bin/python convert_lora_to_gguf.py "
               "--outfile %s --outtype f16 --base %s %s 2>&1 | tail -5"
               % (GGUF, BASE, ADP), t=1800))
print(q(c, "ls -l %s 2>/dev/null || echo 没转成" % GGUF))

print("\n打包（GGUF + adapter_config + 摘要）：")
print(q(c, "rm -f %s && tar -czf %s -C %s . -C /root/autodl-tmp %s "
           "&& ls -l %s && sha256sum %s | cut -d' ' -f1"
           % (PACK, PACK, ADP, "yuanheng-stylepatch4-lora.gguf", PACK, PACK), t=900))
c.close()
