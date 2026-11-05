# -*- coding: utf-8 -*-
"""收口 44/56 vs 45/56：四组对照，每组都冷启动一次。

G1 只评测（对照）
G2 先一条非流式对话 → 评测
G3 先一条流式对话 → 评测
G4 先非流式再流式（= _gpu_direct.py 的原样）→ 评测

每组都从 serverctl.start 起，跑完就停；组间互不共享 KV 缓存。
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


def chat(stream: bool, text: str = "在吗") -> str:
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


def boot():
    r = serverctl.start(V["id"], V["path"], reg["bases"]["gguf"], reg["bases"]["mmproj"],
                        port=8091, ctx=8192, ngl=99)
    if not r.get("ok"):
        print("  ✗ 起不来：%s" % r.get("error"), flush=True)
        return False
    return True


def phase(tag: str) -> tuple[int, list[str], list[str]]:
    out = evals._run_persona56(8091, tag)
    fails = [x["id"] for x in out["results"] if not x["ok"]]
    print("  %-8s %s/%s | %s | 失败 %s"
          % (tag, out["ok"], out["total"], json.dumps(out["by_cat"], ensure_ascii=False),
             ",".join(fails)), flush=True)
    return out["ok"], fails, [x["answer"][:60] for x in out["results"] if x["id"] in ("p10", "p11", "st06")]


results = {}

print("== G1 只评测", flush=True)
if boot():
    results["G1"] = phase("G1_eval_only")
    serverctl.stop()

print("\n== G2 一条非流式 → 评测", flush=True)
if boot():
    print("  聊天：%r" % chat(False), flush=True)
    results["G2"] = phase("G2_after_nonstream")
    serverctl.stop()

print("\n== G3 一条流式 → 评测", flush=True)
if boot():
    print("  聊天：%r" % chat(True), flush=True)
    results["G3"] = phase("G3_after_stream")
    serverctl.stop()

print("\n== G4 非流式+流式（direct 原样）→ 评测", flush=True)
if boot():
    print("  聊天：%r / %r" % (chat(False), chat(True)), flush=True)
    results["G4"] = phase("G4_after_both")
    serverctl.stop()

print("\n== 汇总", flush=True)
for k in ("G1", "G2", "G3", "G4"):
    if k in results:
        ok, fails, key_answers = results[k]
        print("  %s = %s/56 | p10/p11/st06 = %s" % (k, ok, key_answers), flush=True)
