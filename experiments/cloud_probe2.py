# -*- coding: utf-8 -*-
"""看云上残留：python 在哪、基座模型在不在、上次的 lora/checkpoint 占多少。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import paramiko  # noqa: E402

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("connect.nma1.seetacloud.com", port=39522, username="root",
            password="FSMqu7B3fRXc", timeout=25)

CMDS = [
    ("python 位置", "ls /root/miniconda3/bin/python* 2>/dev/null; which conda; "
                    "ls /root/miniconda3/envs 2>/dev/null"),
    ("conda python 版本", "/root/miniconda3/bin/python -V 2>&1"),
    ("torch/transformers", "/root/miniconda3/bin/python -c "
                           "'import torch,transformers;print(torch.__version__, torch.cuda.is_available());"
                           "print(transformers.__version__)' 2>&1 | tail -3"),
    ("autodl-tmp 内容", "du -sh /root/autodl-tmp/* 2>/dev/null | sort -h | tail -12"),
    ("找基座", "ls -d /root/autodl-tmp/models/* /root/autodl-tmp/*e4b* 2>/dev/null"),
    ("lora 目录", "ls -d /root/autodl-tmp/models/lora/* 2>/dev/null | head"),
    ("根盘大件", "du -sh /root/* 2>/dev/null | sort -h | tail -6"),
]
for label, cmd in CMDS:
    _i, out, err = cli.exec_command(cmd, timeout=120)
    print("\n=== %s ===" % label)
    print(out.read().decode("utf-8", "replace").strip() or "(空)")
    e = err.read().decode("utf-8", "replace").strip()
    if e:
        print("[err] " + e[:200])
cli.close()
