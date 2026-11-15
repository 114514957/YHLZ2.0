# -*- coding: utf-8 -*-
"""等全量训练结束（或被看门狗兜住）→ 自动跑 PPL 对比 + 风格评测。"""
from __future__ import annotations

import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
OUT = "/root/autodl-tmp/models/full/yuanheng-v9f1-gemma"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=7200):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


t0 = time.time()
last = ""
while time.time() - t0 < 4800:
    time.sleep(60)
    o, _ = sh("pgrep -c '[f]inetune_train.py' || echo 0")
    alive = o.strip() not in ("0", "")
    o2, _ = sh("tail -c 600 /root/autodl-tmp/logs/full_v9f1.log")
    m = re.findall(r"(\d+)/935", o2)
    step = m[-1] if m else "?"
    if step != last:
        print("  %s 步｜进程 %s｜%.0f 分钟" % (step, "在" if alive else "无",
                                             (time.time() - t0) / 60), flush=True)
        last = step
    if not alive:
        print("训练进程结束（第 %s 步）" % step)
        break

o, _ = sh("ls -l %s/*.safetensors 2>/dev/null | tail -2; du -sh %s 2>/dev/null; df -h /root/autodl-tmp | tail -1"
          % (OUT, OUT))
print("\n产物：\n%s" % o)

o, _ = sh("tail -c 800 /root/autodl-tmp/logs/full_v9f1.log")
print("\n日志尾：\n%s" % o[-600:])

# 有没有最终模型
o, _ = sh("test -f %s/model.safetensors && echo YES || echo NO" % OUT)
if "YES" in o:
    print("\n== 遗忘检查（训练后 PPL）==")
    o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u ppl_probe.py "
              "--model %s --tag full 2>&1 | grep -v 'Loading weights' | tail -3" % OUT, t=3600)
    print(o or e)
    print("\n== 风格评测 ==")
    o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u eval_style.py "
              "--base %s --tag v9f1-full 2>&1 | grep -v 'Loading weights' | head -14" % OUT, t=3600)
    print(o or e)
else:
    print("\n⚠️ 没有最终 model.safetensors——最终保存没成功，看 checkpoint 还在不在")
c.close()
