#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V9 云端一条龙：装公钥 → 上传训练包 → 远程训练 → 拉回产物。

为什么要有这个：老爹「记得之前的教训」——上次训完产物和日志都没留。
现在流程固定成五步，每步都有校验，产物自动打包拉回。

首次用需要密码（只用来装公钥，之后全程免密）。密码不会写进任何文件。

用法：
    # 首次（会提示输入密码）
    python tools/v9_cloud_launch.py --host connect.nma1.seetacloud.com --port 39522

    # 已装过公钥（免密）
    python tools/v9_cloud_launch.py --host <ip> --port <port> --skip-key

    # 只上传不训练
    python tools/v9_cloud_launch.py --host <ip> --port <port> --skip-key --upload-only

参数说明：
    --remote-dir  远端工作目录（默认 /root/autodl-tmp/yh，AutoDL 数据盘不占系统盘）
    --local-tar   本地上传包（默认 dist/v9_bundle_upload.tar.gz）
    --epochs      覆盖 epoch 数（默认用配置里的 3）
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KEY = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")),
                   ".ssh", "id_ed25519_yh")


def run(cmd: list[str], check: bool = True, capture: bool = True) -> tuple[int, str]:
    """跑一条命令，实时回显（训练要能看到进度）。"""
    print("  $ " + " ".join(cmd[:6]) + (" …" if len(cmd) > 6 else ""))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace",
                         bufsize=1)
    lines = []
    for ln in p.stdout:
        sys.stdout.write("    " + ln)
        sys.stdout.flush()
        lines.append(ln)
    p.wait()
    out = "".join(lines)
    if check and p.returncode != 0:
        raise RuntimeError("命令失败（%d）：%s" % (p.returncode, out[-400:]))
    return p.returncode, out


def ssh_base(host: str, port: str, user: str) -> list[str]:
    return ["ssh", "-p", port,
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=30",
            "-i", KEY, "%s@%s" % (user, host)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", default="22")
    ap.add_argument("--user", default="root")
    ap.add_argument("--remote-dir", default="/root/autodl-tmp/yh")
    ap.add_argument("--local-tar", default="dist/v9_bundle_upload.tar.gz")
    ap.add_argument("--skip-key", action="store_true", help="公钥已装，跳过")
    ap.add_argument("--upload-only", action="store_true")
    ap.add_argument("--epochs", default="")
    ap.add_argument("--config", default="config/finetune_v9_cloud.json")
    a = ap.parse_args()

    tar = os.path.join(ROOT, a.local_tar)
    if not os.path.exists(tar):
        print("❌ 找不到上传包：%s" % tar)
        print("   先跑：python tools/v9_build_train_bundle.py && tar -czf %s -C dist/v9_train_bundle ." % a.local_tar)
        return 1
    print("上传包：%s（%.2f MB）" % (a.local_tar, os.path.getsize(tar) / 1048576))
    base = ssh_base(a.host, a.port, a.user)

    # ── 1. 装公钥（首次）──
    if not a.skip_key:
        print("\n== 1/5 装公钥（需要输入一次密码）==")
        pub = KEY + ".pub"
        if not os.path.exists(pub):
            print("❌ 没有公钥 %s，先跑 ssh-keygen" % pub)
            return 1
        key = open(pub, encoding="utf-8").read().strip()
        cmd = ("mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
               "echo '%s' >> ~/.ssh/authorized_keys && "
               "chmod 600 ~/.ssh/authorized_keys && echo KEY_OK" % key)
        print("  接下来会提示输入密码（只这一次）")
        rc = subprocess.call(["ssh", "-p", a.port,
                              "-o", "StrictHostKeyChecking=accept-new",
                              "%s@%s" % (a.user, a.host), cmd])
        if rc != 0:
            print("❌ 装公钥失败（密码错？端口不对？）")
            return 1
        print("  ✅ 公钥已装，之后免密")
    else:
        print("\n== 1/5 跳过装公钥 ==")

    # ── 2. 连通性 ──
    print("\n== 2/5 连通性检查 ==")
    rc, out = run(base + ["nvidia-smi --query-gpu=name,memory.total --format=csv,noheader"])
    print("  远端 GPU 就绪")

    # ── 3. 上传 ──
    print("\n== 3/5 上传训练包 ==")
    run(base + ["mkdir -p %s" % a.remote_dir])
    scp = ["scp", "-P", a.port,
           "-o", "StrictHostKeyChecking=accept-new", "-i", KEY,
           tar, "%s@%s:%s/bundle.tar.gz" % (a.user, a.host, a.remote_dir)]
    run(scp)
    run(base + ["cd %s && rm -rf app && mkdir -p app && "
                "tar -xzf bundle.tar.gz -C app && ls app" % a.remote_dir])

    if a.upload_only:
        print("\n✅ 只上传，不训练。远端目录：%s/app" % a.remote_dir)
        return 0

    # ── 4. 远程训练（实时回显）──
    print("\n== 4/5 远程训练（会跑一会，日志实时回显）==")
    print("=" * 70)
    t0 = time.time()
    train_cmd = "cd %s/app && bash run.sh %s" % (a.remote_dir, a.config)
    if a.epochs:
        train_cmd = ("cd %s/app && sed -i 's/\"epochs\": [0-9]*/\"epochs\": %s/' %s "
                     "&& bash run.sh %s" % (a.remote_dir, a.epochs, a.config, a.config))
    run(base + [train_cmd])
    print("=" * 70)
    print("  训练耗时 %.1f 分钟" % ((time.time() - t0) / 60))

    # ── 5. 拉回产物 ──
    print("\n== 5/5 拉回产物 ==")
    rc, out = run(base + ["ls -1t %s/app/v9_train_artifacts_*.tar.gz 2>/dev/null | head -1"
                          % a.remote_dir], check=False)
    remote_tar = out.strip().split("\n")[-1] if out.strip() else ""
    if not remote_tar:
        print("⚠ 远端没找到产物包，请手动检查 %s/app/" % a.remote_dir)
        return 1
    print("  远端产物：%s" % remote_tar)
    dest = os.path.join(ROOT, "dist")
    run(["scp", "-P", a.port, "-o", "StrictHostKeyChecking=accept-new", "-i", KEY,
         "%s@%s:%s" % (a.user, a.host, remote_tar), dest])
    local_tar = os.path.join(dest, os.path.basename(remote_tar))
    print("  ✅ 已拉回：%s（%.1f MB）"
          % (local_tar, os.path.getsize(local_tar) / 1048576))

    # 顺带拉训练日志
    rc, out = run(base + ["ls -1t %s/app/train_*.log 2>/dev/null | head -1"
                          % a.remote_dir], check=False)
    rlog = out.strip().split("\n")[-1] if out.strip() else ""
    if rlog:
        run(["scp", "-P", a.port, "-o", "StrictHostKeyChecking=accept-new", "-i", KEY,
             "%s@%s:%s" % (a.user, a.host, rlog), dest])
        print("  ✅ 训练日志也拉回来了：%s" % os.path.basename(rlog))

    # ── 校验 + 判读 ──
    print("\n== 产物校验与质量判读 ==")
    run([sys.executable, os.path.join(ROOT, "tools", "v9_collect_training.py"),
         "--verify", local_tar])
    print("\n✅ 一条龙完成。产物在 dist/，日志也在 dist/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
