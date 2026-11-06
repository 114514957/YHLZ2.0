# -*- coding: utf-8 -*-
"""把训练包的 tar.gz 也登记进素材版本清单（素材版本不只是补丁，还有整包）。"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAN = os.path.join(YH, "data", "finetune", "_versions", "material_manifest.json")

m = json.load(io.open(MAN, encoding="utf-8"))
for tag, tar in (("v9t8", os.path.join(YH, "dist", "retrain_pkg_gemma_v9t8.tar.gz")),
                 ("v9t7", os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7.tar.gz"))):
    if not os.path.exists(tar) or tag not in m["versions"]:
        continue
    h = hashlib.sha256(open(tar, "rb").read()).hexdigest()
    m["versions"][tag].setdefault("packs", {})[os.path.basename(tar)] = {
        "bytes": os.path.getsize(tar), "sha256": h}
    print("%s ← %s（%d 字节）" % (tag, os.path.basename(tar), os.path.getsize(tar)))

json.dump(m, io.open(MAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n清单：%s" % MAN)
for tag, v in sorted(m["versions"].items()):
    print("  %-6s %s 补丁%d个 整包%d个" % (tag, v["created"][:10], len(v["files"]),
                                      len(v.get("packs", {}))))
