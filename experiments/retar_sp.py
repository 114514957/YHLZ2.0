# -*- coding: utf-8 -*-
"""删 checkpoint 再打包（--exclude 顺序坑：必须写在 -C 之前）。"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
ADP = "/root/autodl-tmp/models/lora/yuanheng-stylepatch4"
PACK = "/root/autodl-tmp/pack_stylepatch4.tar.gz"

import paramiko  # noqa: E402

for attempt in range(4):
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
                  banner_timeout=30, auth_timeout=30)
        for label, cmd in (
            ("清 checkpoint", "rm -rf %s/checkpoint-*; du -sh %s" % (ADP, ADP)),
            ("打包", "rm -f %s && tar -czf %s --exclude='checkpoint-*' -C %s . "
                     "&& stat -c %%s %s" % (PACK, PACK, ADP, PACK)),
            ("sha", "sha256sum %s | cut -d' ' -f1" % PACK),
        ):
            _i, o, e = c.exec_command(cmd, timeout=900)
            o.channel.settimeout(880)
            print("%s：%s" % (label, o.read().decode("utf-8", "replace").strip()))
        c.close()
        break
    except Exception as ex:  # noqa: BLE001
        print("第 %d 次失败 %s" % (attempt + 1, type(ex).__name__))
        time.sleep(5)
