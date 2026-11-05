# -*- coding: utf-8 -*-
"""切版本验收：v7b（attention+MLP，52.61 MB）对比 v9t6（只训 attention，17.33 MB）。

若分数与台账 1059 的 v7b 41/56 对得上，就说明"版本切换 → 跑分对比"这条链是真的。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench"
sys.path.insert(0, HERE)

import evals  # noqa: E402
import registry  # noqa: E402
import serverctl  # noqa: E402

reg = registry.scan()
for vid in ("gguf:yuanheng-v7b-lora.gguf",):
    v = next(x for x in reg["versions"] if x["id"] == vid)
    t0 = time.time()
    r = serverctl.start(v["id"], v["path"], reg["bases"]["gguf"], reg["bases"]["mmproj"],
                        port=8091, ctx=8192, ngl=99)
    print("启动 %s → %s | %.1fs" % (v["version"], json.dumps(r, ensure_ascii=False),
                                  time.time() - t0), flush=True)
    if not r.get("ok"):
        continue
    t = time.time()
    out = evals._run_persona56(8091, "gpu_%s" % v["version"])
    fails = [x["id"] for x in out["results"] if not x["ok"]]
    print("%s：%s/%s（%.1f%%）| %s | %.1fs"
          % (v["version"], out["ok"], out["total"], 100.0 * out["ok"] / out["total"],
             json.dumps(out["by_cat"], ensure_ascii=False), time.time() - t), flush=True)
    print("  失败：%s" % ",".join(fails), flush=True)
    print("  停：%s" % json.dumps(serverctl.stop(), ensure_ascii=False), flush=True)
    time.sleep(2)
