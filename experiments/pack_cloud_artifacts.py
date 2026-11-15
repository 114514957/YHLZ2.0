# -*- coding: utf-8 -*-
"""训练完在云端打**一个**包，给老爹从网页面板直拉（他拉得快，我不抢带宽）。

约定（2026-11-11 定，教训来自 v10u 那次）：
  · 只打**产物**，不打 checkpoint（v10u 那次打进去 2 个 checkpoint，385MB -> 123MB）
  · 文件名全 ASCII（中文会被网页面板翻译坏：jinja->金贾、safetensors->安全张量）
  · 放 /root/autodl-tmp/ 根目录（面板里一眼看到，不用翻 models/lora/...）
  · 同时生成 .sha256 和 PACKS.txt 一行记录，方便核对

用法（能连上云时）：
  python pack_cloud_artifacts.py v11 --kind lora
  python pack_cloud_artifacts.py v9f1 --kind full
"""
from __future__ import annotations

import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = os.environ.get("YH_CLOUD_HOST", "connect.nma1.seetacloud.com")
PORT = int(os.environ.get("YH_CLOUD_PORT", "39522"))
USER = os.environ.get("YH_CLOUD_USER", "root")
PW = os.environ.get("YH_SSH_PASS", "")

KINDS = {
    "lora": "/root/autodl-tmp/models/lora/{name}",
    "full": "/root/autodl-tmp/models/full/{name}",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", help="v11 / v9f1 ...")
    ap.add_argument("--kind", default="lora", choices=list(KINDS))
    ap.add_argument("--name", default="", help="产物目录名（默认 yuanheng-<tag>）")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args()

    name = a.name or ("yuanheng-" + a.tag)
    src = KINDS[a.kind].format(name=name)
    tar = "/root/autodl-tmp/pack_%s.tar.gz" % a.tag
    sha = "/root/autodl-tmp/pack_%s.sha256" % a.tag

    if not PW:
        sys.exit("需要 YH_SSH_PASS")

    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(a.host, port=a.port, username=USER, password=PW, timeout=30,
              banner_timeout=30, auth_timeout=30)

    def sh(cmd, t=1800):
        _i, o, e = c.exec_command(cmd, timeout=t)
        return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()

    o, _ = sh("test -d %s && echo YES || echo NO" % src)
    if "YES" not in o:
        sys.exit("云端没有这个目录：%s" % src)

    cmd = ("cd %s && rm -f %s && "
           "tar -czf %s --exclude='checkpoint-*' --exclude='*.pt' "
           "--exclude='optimizer*' --exclude='rng_state*' --exclude='scheduler*' . "
           "&& sha256sum %s > %s && ls -l %s && cut -d' ' -f1 %s"
           % (src, tar, tar, tar, sha, tar, sha))
    o, e = sh(cmd, t=1800)
    print(o or e)

    line = "%s\t%s\t%s" % (a.tag, tar, os.path.basename(sha))
    sh("grep -q '%s' /root/autodl-tmp/PACKS.txt 2>/dev/null || echo '%s' >> /root/autodl-tmp/PACKS.txt"
       % (a.tag, line))

    o, _ = sh("stat -c %%s %s" % tar)
    size = o.strip()
    if size.isdigit():
        print("\nOK 打包完成：%s（%.1f MB）" % (tar, int(size) / 1048576))
        print("   面板里进 /root/autodl-tmp/ 就能看到，直接下拉")
        print("   校验：cat %s" % sha)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
