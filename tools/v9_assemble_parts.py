#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""分卷合并 + 校验（手动下载完 model.part-00..19 后跑）。

用法：
    python tools/v9_assemble_parts.py --dir <放分卷的目录>
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXPECT_SIZE = 8044982080        # 云端 model.safetensors 的字节数
EXPECT = {
    "model.part-00": "59724b3e3f9b0ecda0d15558031268db",
    "model.part-01": "5d25b114c39e29479f52f228f6c2f396",
    "model.part-02": "9d5b7505039c0527698d763917decd9c",
    "model.part-03": "757e5e671fc39bfaf0f0c8ed53a202ed",
    "model.part-04": "d9a7ba0f610578cf0fd41f29c72c88c7",
    "model.part-05": "aa679827e2ff4e89e1880bdb7e6f0705",
    "model.part-06": "4a75c5508bedd88fdd174e2d2ff06b3b",
    "model.part-07": "29cb2d519fdd127d681471d7e1424e06",
    "model.part-08": "1b7204ddfe320a2005f3e0115ead5180",
    "model.part-09": "9a3662d9903f45c6d6e3ade36db544eb",
    "model.part-10": "68fa744c7ba62e3a61b858ffc63a352d",
    "model.part-11": "956e858a239471bd411ca6ed9ca38074",
    "model.part-12": "603b46fb6fdabb64a7562643931497ba",
    "model.part-13": "b17ee870ebfda1c7bd90a105b6645223",
    "model.part-14": "847aae9d8efe14f345b6af8724792139",
    "model.part-15": "5edf7020befe520303d3290ed9138f31",
    "model.part-16": "2d4aed69f6ec3596e81dac6732225246",
    "model.part-17": "15d8a1ffa4475f01490c77b94462d35b",
    "model.part-18": "a8ae24c5f7b9cf2fd91148d2aa587264",
    "model.part-19": "932b0f641fed0fa7b8c128f5017cefb4",
}


def md5(p: str, chunk: int = 8 << 20) -> str:
    h = hashlib.md5()
    with io.open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="models/full/qwen3-4b-yuanheng-v9t/parts")
    ap.add_argument("--out", default="models/full/qwen3-4b-yuanheng-v9t/model.safetensors")
    ap.add_argument("--no-merge", action="store_true", help="只校验不合并")
    a = ap.parse_args()

    if not os.path.isdir(a.dir):
        print("❌ 目录不存在：%s" % a.dir)
        return 1

    print("=" * 66)
    print("① 校验分卷（共 20 个）")
    print("=" * 66)
    bad, missing = [], []
    for fn, want in sorted(EXPECT.items()):
        p = os.path.join(a.dir, fn)
        if not os.path.exists(p):
            missing.append(fn)
            print("  ❌ %-16s 缺失" % fn)
            continue
        sz = os.path.getsize(p)
        got = md5(p)
        ok = (got == want)
        print("  %s %-16s %7.1f MB  %s"
              % ("✅" if ok else "❌", fn, sz / 1048576,
                 "md5 一致" if ok else "md5 不符（%s…）" % got[:12]))
        if not ok:
            bad.append(fn)

    if missing or bad:
        print("\n❌ 还不能合并：缺 %d 个、坏 %d 个" % (len(missing), len(bad)))
        if missing:
            print("   缺：%s" % missing)
        if bad:
            print("   坏：%s" % bad)
        return 1

    if a.no_merge:
        print("\n✅ 20 个分卷全部校验通过")
        return 0

    print("\n" + "=" * 66)
    print("② 合并")
    print("=" * 66)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with io.open(a.out, "wb") as out:
        for fn in sorted(EXPECT):
            with io.open(os.path.join(a.dir, fn), "rb") as f:
                while True:
                    b = f.read(8 << 20)
                    if not b:
                        break
                    out.write(b)
    sz = os.path.getsize(a.out)
    print("  合并后：%s（%d 字节）" % (a.out, sz))
    if sz != EXPECT_SIZE:
        print("  ❌ 大小不符，应为 %d" % EXPECT_SIZE)
        return 1
    print("  ✅ 大小正确")

    print("\n" + "=" * 66)
    print("③ 完整性")
    print("=" * 66)
    print("  整体 md5：%s" % md5(a.out))
    print("  （云端原文件大小 %d，已一致）" % EXPECT_SIZE)
    print("\n✅ 完成。可以直接用 transformers 加载：")
    print("   from transformers import AutoModelForCausalLM")
    print("   m = AutoModelForCausalLM.from_pretrained('%s')"
          % os.path.dirname(a.out).replace("\\", "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
