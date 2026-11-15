# -*- coding: utf-8 -*-
"""云端测速：hf-mirror vs huggingface 直连，各取 50MB 看速率。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=600):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


P = "TrevorJS/gemma-4-E4B-it-uncensored/resolve/main/model.safetensors"
for name, host in (("hf-mirror", "https://hf-mirror.com"), ("huggingface", "https://huggingface.co")):
    cmd = ("cd /tmp && rm -f spd.bin && "
           "S=$(date +%%s) && curl -sS -L --max-time 40 -r 0-52428799 -o spd.bin %s/%s ; "
           "E=$(date +%%s) && SZ=$(stat -c %%s spd.bin 2>/dev/null || echo 0) && "
           "echo \"$SZ 字节 / $((E-S)) 秒 = $((SZ/1024/1024/(E-S+1))) MB/s\"" % (host, P))
    o, e = sh(cmd, t=300)
    print("%-12s %s" % (name, o or e))
c.close()
