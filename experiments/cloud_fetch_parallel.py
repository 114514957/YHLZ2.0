# -*- coding: utf-8 -*-
"""上传并行下载脚本 → 后台跑 → 轮询进度。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
SIZE = 15992595884

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=7200):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


# 先杀掉旧的单连接 curl
sh("pkill -f 'curl.*model.safetensors' || true")
s = c.open_sftp()
s.put(os.path.join(YH, "experiments", "fetch_base_parallel.sh"), "/root/yh/fetch_base_parallel.sh")
s.close()
sh("chmod +x /root/yh/fetch_base_parallel.sh")

o, _ = sh("cd /root/yh && nohup bash fetch_base_parallel.sh > /root/autodl-tmp/logs/fetch_base.log 2>&1 & echo STARTED", t=60)
print(o)

t0 = time.time()
last = -1
while time.time() - t0 < 3000:
    time.sleep(45)
    o, _ = sh("cd /root/autodl-tmp/models/gemma-4-e4b-it-uncensored && "
              "cat part.* 2>/dev/null | wc -c; stat -c %s model.safetensors 2>/dev/null || echo 0", t=120)
    nums = [int(x) for x in o.split() if x.isdigit()]
    done = nums[0] if nums else 0
    if done >= SIZE:
        print("下载完成 %d 字节（%.0f 秒）" % (done, time.time() - t0))
        break
    if done != last:
        print("  %.1f%%  %d/%d  (%.0f 秒)" % (100 * done / SIZE, done, SIZE, time.time() - t0),
              flush=True)
        last = done

o, _ = sh("tail -5 /root/autodl-tmp/logs/fetch_base.log")
print("日志尾：\n" + o)
c.close()
