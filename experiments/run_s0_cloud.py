# -*- coding: utf-8 -*-
"""云端驱动：查状态 → 清盘 → 传脚本 → 跑 S0。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
SCRIPTS = ["s0_rank_diagnosis.py", "s2_compile.py", "abliterate.py"]

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=5400):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


print("== 状态 ==")
o, _ = sh("df -h /root/autodl-tmp | tail -1; du -sh /root/autodl-tmp/models/* 2>/dev/null; "
          "ls /root/autodl-tmp/models/gemma-4-e4b-it-uncensored/ 2>/dev/null | head -3")
print(o)

print("\n== 清盘（删 uncensored 分块，这轮用不到）==")
o, _ = sh("rm -rf /root/autodl-tmp/models/gemma-4-e4b-it-uncensored; "
          "df -h /root/autodl-tmp | tail -1; ls /root/autodl-tmp/models/gemma-4-e4b-it/ | head -3")
print(o)

s = c.open_sftp()
for f in SCRIPTS:
    s.put(os.path.join(YH, "experiments", f), "/root/yh/" + f)
s.close()
print("\n脚本已上传：%s" % SCRIPTS)

print("\n== GPU ==")
o, _ = sh("nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader")
print(o)

print("\n== 跑 S0（只前向）==")
t0 = time.time()
o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u s0_rank_diagnosis.py "
          "--base /root/autodl-tmp/models/gemma-4-e4b-it "
          "--out /root/yh/results/s0.json --max-tokens 50000 2>&1 | tail -40", t=5400)
print(o or e)
print("\nS0 用时 %.1f 分钟" % ((time.time() - t0) / 60))
c.close()
