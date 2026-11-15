# -*- coding: utf-8 -*-
"""只打 adapter 包（不转 GGUF），给老爹拉；本地再转。"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
ADP = "/root/autodl-tmp/models/lora/yuanheng-stylepatch4"
PACK = "/root/autodl-tmp/pack_stylepatch4.tar.gz"

import paramiko  # noqa: E402

for attempt in range(3):
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
                  banner_timeout=30, auth_timeout=30)
        cmd = ("rm -f %s && tar -czf %s -C %s . --exclude='checkpoint-*' && "
               "stat -c %%s %s && sha256sum %s | cut -d' ' -f1" % (PACK, PACK, ADP, PACK, PACK))
        _i, o, e = c.exec_command(cmd, timeout=900)
        o.channel.settimeout(880)
        print(o.read().decode("utf-8", "replace").strip())
        c.close()
        break
    except Exception as ex:  # noqa: BLE001
        print("第 %d 次失败 %s" % (attempt + 1, type(ex).__name__))
        time.sleep(5)
