# -*- coding: utf-8 -*-
"""腾空间（删 Qwen3-4B / 测试文件 / 旧包）→ 续传上传基座。"""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
SRC = os.path.join(YH, "models", "gemma4-hf", "gemma-4-E4B-it-uncensored", "model.safetensors")
DST = "/root/autodl-tmp/models/gemma-4-e4b-it-uncensored/model.safetensors"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("connect.nma1.seetacloud.com", port=39522, username="root",
          password="FSMqu7B3fRXc", timeout=30, banner_timeout=30, auth_timeout=30)
_i, o, e = c.exec_command(
    "rm -rf /root/autodl-tmp/models/Qwen3-4B /root/autodl-tmp/_up_test.bin "
    "/root/autodl-tmp/pack_v9t*.tar.gz /tmp/spd.bin; "
    "rm -f /root/autodl-tmp/models/gemma-4-e4b-it-uncensored/model.safetensors; "
    "cd /root/autodl-tmp/models/gemma-4-e4b-it-uncensored && du -cb part.* 2>/dev/null | tail -1; "
    "df -h /root/autodl-tmp | tail -1", timeout=300)
print("腾空间后：\n" + o.read().decode())
c.close()

t0 = time.time()
r = subprocess.run([sys.executable, os.path.join(YH, "experiments", "parallel_upload.py"),
                    SRC, DST, "8"], encoding="utf-8", errors="replace",
                   capture_output=True, text=True)
out = (r.stdout or "")[-2500:]
err = (r.stderr or "")[-600:]
print(out)
print(err)
print("总耗时 %.0f 分钟｜退出码 %s" % ((time.time() - t0) / 60, r.returncode))
