# -*- coding: utf-8 -*-
"""守着 v11 训练：每 5 分钟报进度；结束后自动打包 + sha256 + 列出产物。"""
from __future__ import annotations

import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
LOG = "/root/autodl-tmp/logs/train_v11.log"
OUT = "/root/autodl-tmp/models/lora/yuanheng-v11"
PACK = "/root/autodl-tmp/pack_v11.tar.gz"

import paramiko  # noqa: E402


def conn():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
              banner_timeout=30, auth_timeout=30)
    return c


def q(cmd, t=120):
    _i, o, e = c.exec_command(cmd, timeout=t)
    o.channel.settimeout(t - 5)
    try:
        return o.read().decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return ""


t0 = time.time()
last = ""
while True:
    try:
        c = conn()
        n = q("pgrep -cf '[f]inetune_train.py' || echo 0")
        tail = q("tail -c 400 %s 2>/dev/null" % LOG)
        c.close()
    except Exception as ex:  # noqa: BLE001
        print("[%3.0f 分] 连不上（%s），30 秒后重试" % ((time.time() - t0) / 60,
                                                  type(ex).__name__), flush=True)
        time.sleep(30)
        continue

    steps = re.findall(r"(\d+)/1649 \[([0-9:]+)<([0-9:]+)", tail)
    if steps:
        s, used, eta = steps[-1]
        msg = "%s/1649｜已用 %s｜剩 %s" % (s, used, eta)
    else:
        msg = tail.splitlines()[-1][:70] if tail else "…"
    if msg != last:
        print("[%3.0f 分] %s" % ((time.time() - t0) / 60, msg), flush=True)
        last = msg

    if n.strip() == "0":
        print("\n训练进程结束。", flush=True)
        break
    time.sleep(300)

print("检查产物…", flush=True)
c = conn()
print(q("ls -l %s | head -8; du -sh %s" % (OUT, OUT)))
print(q("grep -aE 'train_runtime|train_loss|已保存' %s | tail -4" % LOG))

print("\n打包…", flush=True)
c2 = conn()
_i, o, e = c2.exec_command(
    "rm -f %s && tar -czf %s --exclude='checkpoint-*' -C %s . && "
    "sha256sum %s && stat -c %%s %s" % (PACK, PACK, OUT, PACK, PACK), timeout=1800)
res = o.read().decode("utf-8", "replace").strip()
print(res)
c.close()
print("\n面板路径：%s" % PACK, flush=True)
