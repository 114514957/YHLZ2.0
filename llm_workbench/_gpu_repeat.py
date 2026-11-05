# -*- coding: utf-8 -*-
"""GPU 复现性：起一次 v9t6，连跑三次 56 题，看分数抖不抖。"""
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


def gpu() -> str:
    try:
        return subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as ex:  # noqa: BLE001
        return "n/a (%s)" % ex


reg = registry.scan()
v = next(x for x in reg["versions"] if x["id"] == "gguf:yuanheng-v9t6-lora.gguf")
print("起前 GPU %s" % gpu(), flush=True)
r = serverctl.start(v["id"], v["path"], reg["bases"]["gguf"], reg["bases"]["mmproj"],
                    port=8091, ctx=8192, ngl=99)
print("启动 %s | GPU %s" % (json.dumps(r, ensure_ascii=False), gpu()), flush=True)
if not r.get("ok"):
    sys.exit(1)

runs = []
for i in range(3):
    t = time.time()
    out = evals._run_persona56(8091, "gpu_rep%d" % (i + 1))
    el = time.time() - t
    fails = [x["id"] for x in out["results"] if not x["ok"]]
    runs.append({"ok": out["ok"], "total": out["total"], "by_cat": out["by_cat"],
                 "fails": fails, "el": round(el, 1)})
    print("第 %d 遍：%s/%s | %.1fs | %s\n        失败：%s"
          % (i + 1, out["ok"], out["total"], el,
             json.dumps(out["by_cat"], ensure_ascii=False), ",".join(fails)), flush=True)

print("\n分数集合：%s" % [x["ok"] for x in runs], flush=True)
base = set(runs[0]["fails"])
for i, x in enumerate(runs[1:], 2):
    s = set(x["fails"])
    print("  第1遍 vs 第%d遍：新增失败 %s | 少失败 %s"
          % (i, sorted(s - base) or "无", sorted(base - s) or "无"), flush=True)

print("\n停实例 %s" % json.dumps(serverctl.stop(), ensure_ascii=False), flush=True)
time.sleep(3)
print("停后 GPU %s" % gpu(), flush=True)
