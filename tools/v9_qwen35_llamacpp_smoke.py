#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""llama-server 上的性能 + 多模态冒烟（Qwen3.5-4B Q4_K_M + mmproj）。"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://127.0.0.1:8082"
IMG = os.path.join(ROOT, "cache", "mm_test.png")
OUT = os.path.join(ROOT, "cache", "v9_base_compare")


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path: str, payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(BASE + path,
                                 data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with _opener().open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def perf(prompt: str, runs: int = 3) -> list[dict]:
    res = []
    for i in range(runs):
        payload = {"messages": [{"role": "user", "content": prompt}],
                   "temperature": 0.3, "max_tokens": 200, "stream": False}
        t0 = time.time()
        try:
            d = post("/v1/chat/completions", payload)
            total = time.time() - t0
            tm = d.get("timings") or {}
            text = (d.get("choices") or [{}])[0].get("message", {}).get("content", "")
            res.append({"run": i + 1, "total_s": round(total, 2),
                        "prompt_tok": tm.get("prompt_n"),
                        "gen_tok": tm.get("predicted_n"),
                        "tok_per_s": round(tm.get("predicted_per_second") or 0, 2),
                        "ttft_s": round((tm.get("prompt_ms") or 0) / 1000, 3) if tm.get("prompt_ms") else None,
                        "text": text[:150]})
        except Exception as exc:  # noqa: BLE001
            res.append({"run": i + 1, "error": "%s: %s" % (type(exc).__name__, exc)})
    return res


def mm() -> list[dict]:
    b64 = base64.b64encode(open(IMG, "rb").read()).decode("ascii")
    asks = [("图中写了哪些字？原样念出来。", ["YHLZ", "2049", "红色", "方块"]),
            ("图里有几个蓝色方块？还有什么颜色形状的图形？", ["3", "三", "蓝", "方"])]
    out = []
    for q, keys in asks:
        payload = {"messages": [{"role": "user", "content": [
            {"type": "text", "text": q},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}],
            "temperature": 0.1, "max_tokens": 300}
        t0 = time.time()
        try:
            d = post("/v1/chat/completions", payload)
            ans = (d.get("choices") or [{}])[0].get("message", {}).get("content", "")
            hits = [k for k in keys if k in ans]
            out.append({"q": q, "answer": ans[:400], "hits": hits,
                        "ok": len(hits) >= 2, "sec": round(time.time() - t0, 2)})
        except Exception as exc:  # noqa: BLE001
            out.append({"q": q, "error": "%s: %s" % (type(exc).__name__, exc)})
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=" * 70)
    print("Qwen3.5-4B Q4_K_M @ llama-server 8082（含 mmproj-F16）")
    print("=" * 70)

    perf("你好", 1)  # warmup
    print("\n【性能】")
    p = perf("用一句话介绍你自己，再讲一个关于雪的笑话。", 3)
    for r in p:
        if "error" in r:
            print("  run%d 失败: %s" % (r["run"], r["error"]))
        else:
            print("  run%d  总 %.2fs  TTFT %.2fs  %s tok  **%.1f tok/s**"
                  % (r["run"], r["total_s"], r["ttft_s"] or 0, r["gen_tok"], r["tok_per_s"]))
            if r["run"] == 1:
                print("     输出: %s" % r["text"].replace("\n", " "))

    print("\n【多模态】")
    m = mm()
    for a in m:
        if "error" in a:
            print("  ❌ %s: %s" % (a["q"], a["error"]))
        else:
            print("  %s\n     答: %s\n     命中 %s -> %s"
                  % (a["q"], a["answer"][:300].replace("\n", " "), a["hits"],
                     "✅ 能看见" if a["ok"] else "⚠️ 弱/猜"))

    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, "smoke_qwen35_4b_llamacpp.json")
    with io.open(fp, "w", encoding="utf-8") as fh:
        json.dump({"perf": p, "multimodal": m}, fh, ensure_ascii=False, indent=1)
    print("\n结果: %s" % os.path.relpath(fp, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
