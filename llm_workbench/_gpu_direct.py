# -*- coding: utf-8 -*-
"""GPU 真机验收（单进程直连，不起第二层服务）。

验的是同一套代码：serverctl.start（-ngl 99）→ 对话 → evals 56 题 → serverctl.stop。
HTTP 那层在 CPU 验收里已经过了（/api/server/*、/api/chat SSE、/api/eval/*）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench"
sys.path.insert(0, HERE)

import evals  # noqa: E402
import registry  # noqa: E402
import serverctl  # noqa: E402

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def gpu() -> str:
    try:
        return subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as ex:  # noqa: BLE001
        return "n/a (%s)" % ex


reg = registry.scan()
v = next(x for x in reg["versions"] if x["id"] == "gguf:yuanheng-v9t6-lora.gguf")
print("== 0. 起前 GPU(used,free MiB) %s | gpu_free_mb()=%s" % (gpu(), serverctl.gpu_free_mb()),
      flush=True)

print("\n== 1. GPU 起 v9t6（-ngl 99, ctx 8192, port 8091）", flush=True)
t0 = time.time()
r = serverctl.start(v["id"], v["path"], reg["bases"]["gguf"], reg["bases"]["mmproj"],
                    port=8091, ctx=8192, ngl=99)
print("   %s | %.1fs | GPU %s" % (json.dumps(r, ensure_ascii=False), time.time() - t0, gpu()),
      flush=True)
if not r.get("ok"):
    sys.exit(1)

print("\n== 2. 对话（非流式 + 流式各一次）", flush=True)
body = {"messages": [{"role": "user", "content": "在吗"}], "temperature": 0.0, "max_tokens": 60}
req = urllib.request.Request("http://127.0.0.1:8091/v1/chat/completions",
                             data=json.dumps(body).encode("utf-8"),
                             headers={"Content-Type": "application/json"})
t1 = time.time()
with OPENER.open(req, timeout=120) as resp:
    d = json.loads(resp.read().decode("utf-8"))
print("   非流式：%r | %.2fs" % (d["choices"][0]["message"]["content"], time.time() - t1),
      flush=True)

body2 = dict(body, stream=True)
req2 = urllib.request.Request("http://127.0.0.1:8091/v1/chat/completions",
                              data=json.dumps(body2).encode("utf-8"),
                              headers={"Content-Type": "application/json"})
acc, t_first, n_chunk = "", None, 0
t2 = time.time()
with OPENER.open(req2, timeout=120) as resp:
    for line in resp:
        s = line.decode("utf-8", "replace").strip()
        if not s.startswith("data:"):
            continue
        payload = s[5:].strip()
        if payload == "[DONE]":
            break
        try:
            j = json.loads(payload)
        except Exception:  # noqa: BLE001
            continue
        piece = ((j.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
        if piece:
            if t_first is None:
                t_first = time.time() - t2
            acc += piece
            n_chunk += 1
el = time.time() - t2
print("   流式：%r | 首字 %s s | 总 %.2fs | %d 块 | %.1f tok/s"
      % (acc, round(t_first, 3) if t_first else None, el, n_chunk,
         (n_chunk / el) if el else 0), flush=True)

print("\n== 3. 56 题评测（GPU 实例）", flush=True)
t3 = time.time()
out = evals._run_persona56(8091, "gpu_v9t6")
el3 = time.time() - t3
print("   %s/%s（%.1f%%）| %.1f 秒（%.2f 秒/题）| %s"
      % (out["ok"], out["total"], 100.0 * out["ok"] / out["total"], el3, el3 / out["total"],
         json.dumps(out["by_cat"], ensure_ascii=False)), flush=True)
fails = [x for x in out["results"] if not x["ok"]]
print("   失败 %d 条：%s" % (len(fails), ",".join(x["id"] for x in fails)), flush=True)

import io  # noqa: E402
import os  # noqa: E402
os.makedirs(evals.RUNS_DIR, exist_ok=True)
fn = "%d_persona56_gpu_v9t6.json" % int(time.time())
with io.open(os.path.join(evals.RUNS_DIR, fn), "w", encoding="utf-8") as f:
    json.dump(dict(out, tag="gpu_v9t6", port=8091, suite="persona56",
                   finished_at=int(time.time())), f, ensure_ascii=False, indent=2)
print("   明细 → data/runs/%s" % fn, flush=True)

print("\n== 4. 停实例", flush=True)
print("   %s" % json.dumps(serverctl.stop(), ensure_ascii=False), flush=True)
time.sleep(3)
print("   停后：%s | GPU %s" % (json.dumps(serverctl.status()["own"], ensure_ascii=False),
                              gpu()), flush=True)
