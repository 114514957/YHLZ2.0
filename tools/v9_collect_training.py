#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""训练产物收集与校验（老爹 2026-10-23：「训练完成后记得把这些数据拉取下来」）。

为什么要有这个：上次 v8 训完，**LLM 的训练日志一条没留**，只剩一个 adapter，
事后无法判断是不是发散、该不该调 lr。这次训练脚本已经会写
`train_summary.json / train_summary.md / train_log.csv`，但还得**打包 + 校验 + 判读**。

用法：
    # 在云端训练完，立刻打包（产物目录默认 out/yuanheng-v9）
    python tools/v9_collect_training.py --pack
    python tools/v9_collect_training.py --pack --out out/yuanheng-v9

    # 下载回本地后校验并判读质量
    python tools/v9_collect_training.py --verify v9_train_artifacts.tar.gz

判读规则（loss 该长什么样）：
    · 正常：loss 下降 30–60%，无尖峰，eval_loss 同步下降
    · 学不动：下降 < 15% → lr 偏小或数据太难
    · 发散：出现 loss 突增 > 2 倍、或 eval_loss 上升 → lr 偏大 / 数据有问题
    · 过拟合：train loss 一直降但 eval_loss 反弹 → 减 epoch
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 必须收进包里的东西（少了就算不完整）
REQUIRED = [
    "adapter_config.json",
    "adapter_model.safetensors",
    "train_summary.json",
    "train_log.csv",
]
OPTIONAL = [
    "tokenizer.json", "tokenizer_config.json", "chat_template.jinja",
    "train_summary.md", "trainer_state.json", "README.md",
    "special_tokens_map.json", "generation_config.json",
]


def sha256_of(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_summary(out_dir: str) -> dict | None:
    p = os.path.join(out_dir, "train_summary.json")
    if not os.path.exists(p):
        return None
    try:
        return json.load(io.open(p, encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return None


def judge(summary: dict) -> list[str]:
    """按 loss 曲线给判读结论。"""
    out = []
    red = summary.get("loss_reduction_pct")
    if red is None:
        out.append("⚠ 没有 loss 采样点，判断不了收敛情况")
    else:
        if red >= 30:
            out.append("✅ loss 下降 %.1f%%，收敛正常" % red)
        elif red >= 15:
            out.append("⚠ loss 只降 %.1f%%，偏弱（可能 lr 偏小或步数不够）" % red)
        else:
            out.append("❌ loss 只降 %.1f%%，基本没学到东西" % red)
    el = summary.get("eval_loss_last")
    ef = summary.get("eval_loss_first")
    if el is not None and ef is not None:
        if el < ef:
            out.append("✅ eval_loss 下降 %.4f → %.4f" % (ef, el))
        else:
            out.append("❌ eval_loss **上升** %.4f → %.4f（过拟合或 lr 偏大）" % (ef, el))
    steps = summary.get("total_steps") or 0
    if steps and steps < 100:
        out.append("⚠ 总步数只有 %d，太少（可能数据或 batch 配置有问题）" % steps)
    lr = summary.get("lr")
    if lr:
        out.append("ℹ 学习率 %g（%s + warmup %s）"
                   % (lr, summary.get("lr_scheduler_type"), summary.get("warmup_ratio")))
    return out


def do_pack(out_dir: str, out_tar: str) -> int:
    if not os.path.isdir(out_dir):
        print("❌ 产物目录不存在：%s" % out_dir)
        return 1
    files, missing = [], []
    for fn in REQUIRED:
        p = os.path.join(out_dir, fn)
        (files if os.path.exists(p) else missing).append(fn)
    for fn in OPTIONAL:
        p = os.path.join(out_dir, fn)
        if os.path.exists(p):
            files.append(fn)
    if missing:
        print("❌ 缺关键文件：%s" % missing)
        print("   （训练脚本没跑完？或 output_dir 指错了）")
        return 1

    summary = read_summary(out_dir)
    manifest = {
        "packed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "out_dir": os.path.abspath(out_dir),
        "files": {}, "summary": summary,
    }
    print("=" * 70)
    print("打包训练产物")
    print("=" * 70)
    for fn in sorted(set(files)):
        p = os.path.join(out_dir, fn)
        sz = os.path.getsize(p)
        manifest["files"][fn] = {"bytes": sz, "sha256": sha256_of(p)}
        print("  %-32s %9.1f KB" % (fn, sz / 1024))

    mp = os.path.join(out_dir, "MANIFEST_artifacts.json")
    with io.open(mp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print("  %-32s （已生成）" % "MANIFEST_artifacts.json")

    with tarfile.open(out_tar, "w:gz") as tf:
        for fn in sorted(set(files) | {"MANIFEST_artifacts.json"}):
            tf.add(os.path.join(out_dir, fn), arcname=fn)
    tsz = os.path.getsize(out_tar)
    print("\n包：%s（%.1f MB）" % (out_tar, tsz / 1048576))
    print("  包 sha256：%s" % sha256_of(out_tar))

    if summary:
        print("\n" + "=" * 70)
        print("训练质量判读")
        print("=" * 70)
        for line in judge(summary):
            print("  " + line)
        print("\n  关键数字：总步数 %s｜耗时 %.1f 秒｜loss %.4f → %.4f"
              % (summary.get("total_steps"), summary.get("elapsed_sec") or 0,
                 summary.get("loss_first") or 0, summary.get("loss_last") or 0))

    print("\n" + "=" * 70)
    print("拉回本地（在你自己机器上跑，不是在云端）")
    print("=" * 70)
    print("  scp <用户>@<云端IP>:%s ." % os.path.abspath(out_tar))
    print("  # 或 rsync -avP <用户>@<云端IP>:%s ./" % os.path.abspath(out_tar))
    print("  # 回来之后：python tools/v9_collect_training.py --verify %s"
          % os.path.basename(out_tar))
    return 0


def do_verify(tar_path: str) -> int:
    if not os.path.exists(tar_path):
        print("❌ 找不到 %s" % tar_path)
        return 1
    print("=" * 70)
    print("校验训练产物包")
    print("=" * 70)
    with tarfile.open(tar_path, "r:gz") as tf:
        names = tf.getnames()
        print("  包内 %d 个文件｜包大小 %.1f MB"
              % (len(names), os.path.getsize(tar_path) / 1048576))
        for fn in REQUIRED:
            print("  %s %s" % ("✅" if fn in names else "❌", fn))
        miss = [f for f in REQUIRED if f not in names]
        if miss:
            print("\n❌ 包不完整，缺：%s" % miss)
            return 1
        # 读 summary 判读
        try:
            # 2026-10-23 修：tar 里的成员是 ExFileObject，不能直接喂 io.open，
            # 必须 .read() 出 bytes 再 decode。
            f = tf.extractfile("train_summary.json")
            _raw = f.read() if f else None
            summary = json.loads(_raw.decode("utf-8-sig")) if _raw else None
        except Exception:  # noqa: BLE001
            summary = None

    if summary:
        print("\n" + "=" * 70)
        print("训练质量判读（来自包内 train_summary.json）")
        print("=" * 70)
        for line in judge(summary):
            print("  " + line)
        print("\n  配置：%d epoch｜batch %s×%s｜lr %g（%s）｜LoRA r=%s α=%s｜seq %s｜4bit=%s"
              % (summary.get("epochs", 0), summary.get("batch_size"),
                 summary.get("grad_accum"), summary.get("lr", 0),
                 summary.get("lr_scheduler_type"), summary.get("lora_r"),
                 summary.get("lora_alpha"), summary.get("max_seq_len"),
                 summary.get("load_in_4bit")))
    else:
        print("\n⚠ 包里没有可读的 train_summary.json，判断不了收敛情况")
    print("\n✅ 包完整，可以解压使用：tar -xzf %s" % os.path.basename(tar_path))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", action="store_true", help="在云端打包产物")
    ap.add_argument("--verify", default="", help="本地校验包")
    ap.add_argument("--out", default="out/yuanheng-v9", help="产物目录")
    ap.add_argument("--tar", default="v9_train_artifacts.tar.gz", help="输出包名")
    a = ap.parse_args()
    if a.verify:
        return do_verify(a.verify)
    if a.pack:
        return do_pack(a.out, a.tar)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
