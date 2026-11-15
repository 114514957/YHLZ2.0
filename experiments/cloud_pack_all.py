# -*- coding: utf-8 -*-
"""云端打包：每一版一个**瘦包**（不含 checkpoint），附 sha256。

产物清单（每个 tag）：
    /root/autodl-tmp/<tag>_产物.tar.gz
    /root/autodl-tmp/<tag>_产物.sha256
    /root/autodl-tmp/产物清单.json     ← 所有 tag 一表看清
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
TAGS = ["v9t7", "v9t8", "v9t10"]

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=1800):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


manifest = {}
for tag in TAGS:
    lora = "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-%s" % tag
    o, _ = sh("test -d %s && echo YES || echo NO" % lora)
    if "YES" not in o:
        print("%-7s 云端没有这个目录，跳过" % tag)
        continue

    print("\n== %s" % tag)
    # 瘦包：只打 adapter + 小文件，**不含 checkpoint-***
    cmd = ("cd %s && rm -f /root/autodl-tmp/%s_产物.tar.gz && "
           "tar -czf /root/autodl-tmp/%s_产物.tar.gz "
           "adapter_model.safetensors adapter_config.json chat_template.jinja README.md "
           "train_summary.json train_summary.md train_log.csv 2>/dev/null; "
           "sha256sum /root/autodl-tmp/%s_产物.tar.gz > /root/autodl-tmp/%s_产物.sha256; "
           "ls -l /root/autodl-tmp/%s_产物.tar.gz; cat /root/autodl-tmp/%s_产物.sha256"
           % (lora, tag, tag, tag, tag, tag, tag))
    o, e = sh(cmd, t=2400)
    print("  " + (o or e))

    o2, _ = sh("stat -c %%s /root/autodl-tmp/%s_产物.tar.gz 2>/dev/null" % tag)
    o3, _ = sh("cut -d' ' -f1 /root/autodl-tmp/%s_产物.sha256 2>/dev/null" % tag)
    manifest[tag] = {"bytes": o2.strip(), "sha256": o3.strip(),
                     "path": "/root/autodl-tmp/%s_产物.tar.gz" % tag}

with io.open(os.path.join(os.path.dirname(__file__), "..", "cache", "_tmp_manifest.json"),
             "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=1)

# 把清单也写一份到云端，方便老爹对着看
lines = ["tag\tbytes\tsha256\tpath"]
for tag, v in manifest.items():
    lines.append("%s\t%s\t%s\t%s" % (tag, v["bytes"], v["sha256"], v["path"]))
s = c.open_sftp()
with s.open("/root/autodl-tmp/产物清单.tsv", "w") as f:
    f.write("\n".join(lines) + "\n")
s.close()

print("\n=== 汇总（都在 /root/autodl-tmp/ 下）===")
for tag, v in manifest.items():
    print("  %-7s %10.1f MB  %s" % (tag, int(v["bytes"]) / 1048576, v["sha256"][:16]))
print("\n清单文件：/root/autodl-tmp/产物清单.tsv")
c.close()
