# -*- coding: utf-8 -*-
"""AutoDL 学术加速（/etc/network_turbo）→ 直连 huggingface 测速。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=300):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


o, _ = sh("ls -l /etc/network_turbo 2>/dev/null && head -12 /etc/network_turbo || echo 没有 academic 加速脚本")
print(o)

P = "TrevorJS/gemma-4-E4B-it-uncensored/resolve/main/model.safetensors"
cmd = ("source /etc/network_turbo 2>/dev/null; cd /tmp && rm -f spd.bin && "
       "S=$(date +%s) && curl -sS -L --max-time 60 -r 0-104857599 -o spd.bin "
       "https://huggingface.co/%s ; E=$(date +%%s) && SZ=$(stat -c %%s spd.bin 2>/dev/null || echo 0) && "
       "echo \"$SZ 字节 / $((E-S)) 秒 = $((SZ/1024/1024/(E-S+1))) MB/s\"" % P)
o, e = sh(cmd, t=300)
print("学术加速下 HF 直连：%s %s" % (o, e))
c.close()
