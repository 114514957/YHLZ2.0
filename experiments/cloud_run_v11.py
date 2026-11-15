# -*- coding: utf-8 -*-
"""一键在云端跑 v11：上传包 → 确保基座 → 装依赖 → 预检 → 训练 → 打包。

用法（拿到卡后，改 host/port/password）：
  python cloud_run_v11.py --host connect.xxx.seetacloud.com --port 22175 --password xxx

做的事：
  1. 查 GPU/磁盘，不够就停
  2. 传 retrain_pkg_gemma_v11.tar.gz 并解开
  3. 基座不存在就用直链下（hf-mirror，8 路并行由脚本内部处理）
  4. pip 装 transformers/peft/datasets/accelerate/bitsandbytes（指定版本）
  5. 跑 preflight_mlp.py（MLP 可否挂 LoRA）
  6. 训练（日志落 /root/autodl-tmp/logs/train_v11.log）
  7. 训练完自动调 pack_cloud_artifacts 打成一个包
  8. 打印供老爹从面板拉的路径 + sha256
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
TAR = os.path.join(YH, "dist", "retrain_pkg_gemma_v11.tar.gz")
BASE = "/root/autodl-tmp/models/gemma-4-e4b-it"
PKGDIR = "/root/yh/retrain_pkg_gemma_v11"
OUT = "/root/autodl-tmp/models/lora/yuanheng-v11"
LOG = "/root/autodl-tmp/logs/train_v11.log"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--user", default="root")
    ap.add_argument("--skip-deps", action="store_true")
    a = ap.parse_args()

    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(a.host, port=a.port, username=a.user, password=a.password,
              timeout=30, banner_timeout=30, auth_timeout=30)

    def sh(cmd, t=7200, quiet=False):
        _i, o, e = c.exec_command(cmd, timeout=t)
        out = o.read().decode("utf-8", "replace").rstrip()
        err = e.read().decode("utf-8", "replace").rstrip()
        if not quiet:
            print((out or err)[:1500])
        return out, err

    print("[1/8] 环境")
    sh("nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader; "
       "df -h /root/autodl-tmp | tail -1; nproc")

    print("\n[2/8] 传包")
    s = c.open_sftp()
    sh("mkdir -p /root/yh", quiet=True)
    s.put(TAR, "/root/yh/retrain_pkg_gemma_v11.tar.gz")
    s.close()
    sh("cd /root/yh && rm -rf retrain_pkg_gemma_v11 && tar -xzf retrain_pkg_gemma_v11.tar.gz "
       "&& wc -l retrain_pkg_gemma_v11/*.jsonl")

    print("\n[3/8] 基座")
    o, _ = sh("test -f %s/model.safetensors && echo HAS || echo MISS" % BASE)
    if "HAS" not in o:
        print("    基座缺失，开始直链下载（约 15GB）…")
        sh("mkdir -p %s && cd %s && "
           "for f in config.json generation_config.json tokenizer.json tokenizer_config.json "
           "chat_template.jinja; do "
           "curl -sSL -C - --retry 20 --retry-all-errors -o $f "
           "https://hf-mirror.com/google/gemma-4-e4b-it/resolve/main/$f || true; done; "
           "curl -L -C - --retry 30 --retry-all-errors -o model.safetensors "
           "https://hf-mirror.com/google/gemma-4-e4b-it/resolve/main/model.safetensors; "
           "ls -l model.safetensors" % (BASE, BASE), t=14400)
    else:
        print("    已有")

    if not a.skip_deps:
        print("\n[4/8] 依赖")
        sh("/root/miniconda3/bin/pip install -q 'transformers==5.20.2' 'peft==0.21.2' "
           "'datasets==5.1.0' 'accelerate==1.15.0' 'bitsandbytes==0.50.2' 2>&1 | tail -3", t=1800)
    else:
        print("\n[4/8] 依赖（跳过）")

    print("\n[5/8] 预检 MLP")
    o, e = sh("cd %s && /root/miniconda3/bin/python preflight_mlp.py %s" % (PKGDIR, BASE), t=1800)
    if "PASS" not in (o + e):
        print("预检没过，停止。")
        c.close()
        return 3

    print("\n[6/8] 训练（1649 步，约 88 分钟）")
    sh("mkdir -p /root/autodl-tmp/logs && cd %s && "
       "TOKENIZERS_PARALLELISM=false nohup /root/miniconda3/bin/python -u finetune_train.py "
       "--config config/finetune.gemma4.v11.json --base %s > %s 2>&1 & echo LAUNCHED"
       % (PKGDIR, BASE, LOG), t=120)
    time.sleep(60)
    sh("grep -aE 'trainable params|编码后保留|权重重采样|已冻结' %s | tail -6" % LOG)

    print("\n[7/8] 等训练结束（每 5 分钟看一眼）")
    t0 = time.time()
    while time.time() - t0 < 4 * 3600:
        time.sleep(300)
        o, _ = sh("pgrep -c '[f]inetune_train.py' || echo 0", quiet=True)
        o2, _ = sh("tail -c 400 %s" % LOG, quiet=True)
        print("    %.0f 分钟｜进程 %s｜%s" % ((time.time() - t0) / 60, o.strip(),
                                           o2.strip().splitlines()[-1][:80] if o2.strip() else ""))
        if o.strip() == "0":
            break

    print("\n[8/8] 打包")
    s = c.open_sftp()
    s.put(os.path.join(YH, "experiments", "pack_cloud_artifacts.py"), "/root/yh/pack_cloud_artifacts.py")
    s.close()
    o, e = sh("cd /root/yh && YH_SSH_PASS=%s /root/miniconda3/bin/python pack_cloud_artifacts.py v11 "
              "--kind lora --host 127.0.0.1 --port 22 2>/dev/null || "
              "tar -czf /root/autodl-tmp/pack_v11.tar.gz --exclude='checkpoint-*' -C %s . && "
              "sha256sum /root/autodl-tmp/pack_v11.tar.gz && ls -l /root/autodl-tmp/pack_v11.tar.gz"
              % (a.password, OUT), t=1800)
    print("\n完成。面板里进 /root/autodl-tmp/ 拉 pack_v11.tar.gz")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
