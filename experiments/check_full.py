# -*- coding: utf-8 -*-
"""查全量训练进度（从日志尾部解析）。"""
from __future__ import annotations

import re
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


o, _ = sh("pgrep -c finetune_train || echo 0")
print("训练进程数：%s" % o.strip())

o, _ = sh("tail -c 4000 /root/autodl-tmp/logs/full_v9f1.log")
steps = re.findall(r"(\d+)/935 \[([0-9:]+)<([0-9:]+),\s*([0-9.]+)s/it\]", o)
if steps:
    n, el, eta, s = steps[-1]
    print("进度 %s/935｜已用 %s｜剩余 %s｜%.2f s/步" % (n, el, eta, float(s)))
else:
    tail = [x for x in o.splitlines() if x.strip()][-3:]
    print("尾部：\n" + "\n".join(tail)[-600:])

o, _ = sh("grep -a 'loss' /root/autodl-tmp/logs/full_v9f1.log | tail -3")
print("\n最近 loss：\n%s" % o[-300:])

o, _ = sh("ls -l /root/autodl-tmp/models/full/ 2>/dev/null | tail -3; "
          "du -sh /root/autodl-tmp/models/full 2>/dev/null")
print("\n产物：\n%s" % o)
c.close()
