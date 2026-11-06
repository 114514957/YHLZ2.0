# -*- coding: utf-8 -*-
"""素材版本留档：每一版补丁/数据集落一份快照，不可覆盖，带哈希。

为什么要有（2026-11-06 事故）：重跑打包脚本把 v9t7 的配置/脚本冲掉了，只因为没留档，
只能从产物副本里捞回来。素材比代码更该留档——**代码能重写，素材是人的东西**。

用法：
    python material_archive.py --tag v9t7 --note "内部拒绝5+群短答77，删687条记得"
    python material_archive.py --list

目录：
    data/finetune/_versions/<tag>/<原文件名>
    data/finetune/_versions/material_manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
FT = os.path.join(YH, "data", "finetune")
VER = os.path.join(FT, "_versions")
MANIFEST = os.path.join(VER, "material_manifest.json")

# 每次留档要带上的东西（存在才收）
CANDIDATES = [
    "supplement_v9t7.jsonl",
    "identity_ai_patch_v9t8.jsonl",
    "identity_v2.jsonl",
    "harden_v9t2.jsonl",
    "harden_v9t3.jsonl",
]


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def count_lines(p):
    with io.open(p, encoding="utf-8", errors="replace") as f:
        return sum(1 for x in f if x.strip())


def load_manifest():
    if os.path.exists(MANIFEST):
        with io.open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    return {"versions": {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="", help="版本号，如 v9t7")
    ap.add_argument("--note", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--force", action="store_true", help="允许覆盖同版本（默认禁止）")
    a = ap.parse_args()

    m = load_manifest()
    if a.list or not a.tag:
        print("已有版本 %d 个：" % len(m["versions"]))
        for tag, v in sorted(m["versions"].items()):
            print("  %-8s %s  %d 个文件  %s"
                  % (tag, v["created"][:19], len(v["files"]), v.get("note", "")[:40]))
        return 0

    if a.tag in m["versions"] and not a.force:
        sys.exit("版本 %s 已存在，禁止覆盖（要覆盖加 --force）" % a.tag)

    dst_dir = os.path.join(VER, a.tag)
    os.makedirs(dst_dir, exist_ok=True)

    files = {}
    for name in CANDIDATES:
        src = os.path.join(FT, name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(dst_dir, name)
        shutil.copy2(src, dst)
        files[name] = {"bytes": os.path.getsize(dst), "rows": count_lines(dst),
                       "sha256": sha256(dst)}
        print("  ✓ %-32s %d 条  %d 字节  %s"
              % (name, files[name]["rows"], files[name]["bytes"], files[name]["sha256"][:12]))

    m["versions"][a.tag] = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "note": a.note, "files": files}
    with io.open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    print("\n留档完成：%s（%d 个文件）" % (dst_dir, len(files)))
    print("清单：%s" % MANIFEST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
