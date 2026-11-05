# -*- coding: utf-8 -*-
"""定位：为什么 _gpu_direct 跑出 44/56，_gpu_repeat 跑出 45/56？

唯一差别是评测前有没有发过「流式」请求。同一实例内做三步：
  ① 直接评测
  ② 发一条流式请求 → 再评测
  ③ 发一条非流式请求 → 再评测
"""
from __future__ import annotations

import json
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
reg = registry.scan()
V = next(x for x in reg["versions"] if x["id"] == "gguf:yuanheng-v9t6-lora.gguf")


def chat(text: str, stream: bool) -> str:
    body = {"messages": [{"role": "user", "content": text}],
            "temperature": 0.0, "max_tokens": 60, "stream": stream}
    req = urllib.request.Request("http://127.0.0.1:8091/v1/chat/completions",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    acc = ""
    with OPENER.open(req, timeout=120) as r:
        if not stream:
            return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]
        for line in r:
            s = line.decode("utf-8", "replace").strip()
            if not s.startswith("data:") or s[5:].strip() == "[DONE]":
                continue
            try:
                j = json.loads(s[5:].strip())
            except Exception:  # noqa: BLE001
                continue
            acc += ((j.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
    return acc


def run(label: str):
    out = evals._run_persona56(8091, label)
    fails = [x["id"] for x in out["results"] if not x["ok"]]
    print("   %-22s %s/%s | %s | 失败 %s"
          % (label, out["ok"], out["total"],
             json.dumps(out["by_cat"], ensure_ascii=False), ",".join(fails)), flush=True)
    return out["ok"], fails


r = serverctl.start(V["id"], V["path"], reg["bases"]["gguf"], reg["bases"]["mmproj"],
                    port=8091, ctx=8192, ngl=99)
print("启动 %s" % json.dumps(r, ensure_ascii=False), flush=True)
if not r.get("ok"):
    sys.exit(1)

print("\n① 起完直接评", flush=True)
a = run("A_direct")

print("\n② 先发一条流式请求：%r" % chat("老爹问你：在吗？", True), flush=True)
b = run("B_after_stream")

print("\n③ 再发一条非流式请求：%r" % chat("老爹问你：在吗？", False), flush=True)
c = run("C_after_nonstream")

print("\n④ 再发一条流式请求", flush=True)
chat("老爹问你：在吗？", True)
d = run("D_after_stream2")

print("\n汇总：")
for name, (ok, fails) in (("A", a), ("B", b), ("C", c), ("D", d)):
    print("   %s = %s" % (name, ok), flush=True)
serverctl.stop()
