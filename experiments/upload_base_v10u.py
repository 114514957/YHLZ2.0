# -*- coding: utf-8 -*-
"""清理云端半截分块 → 8 路并行上传整份基座。"""
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
    "pkill -f fetch_base_parallel || true; sleep 1; "
    "cd /root/autodl-tmp/models/gemma-4-e4b-it-uncensored && rm -f part.* ranges.txt; "
    "df -h /root/autodl-tmp | tail -1", timeout=180)
print("清理后：\n" + o.read().decode())
c.close()

t0 = time.time()
r = subprocess.run([sys.executable, os.path.join(YH, "experiments", "parallel_upload.py"),
                    SRC, DST, "8"], encoding="utf-8", errors="replace")
print(r.stdout[-1500:], r.stderr[-500:])
print("总耗时 %.0f 分钟" % ((time.time() - t0) / 60))
