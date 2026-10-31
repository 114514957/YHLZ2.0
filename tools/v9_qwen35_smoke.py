#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Qwen3.5 在 8GB 卡上的性能与多模态冒烟测试。

只回答两个问题（老爹要求：性能 + 多模态"有就行"）：
  1. **性能**：首字延迟 TTFT、生成速度 tok/s、总耗时
  2. **多模态**：能不能真的"看见"图（读文字、数图形）——不是猜

用法：
    python tools/v9_qwen35_smoke.py --model qwen3.5:2b
    python tools/v9_qwen35_smoke.py --model qwen3.5:4b --runs 3
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "cache", "mm_test.png")
OUT_DIR = os.path.join(ROOT, "cache", "v9_base_compare")


def post_stream(url: str, payload: dict, timeout: int = 300):
    """流式请求，逐块 yield dict。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line.decode("utf-8"))
            except Exception:
                continue


def run_perf(base: str, model: str, prompt: str, runs: int) -> list[dict]:
    results = []
    for i in range(runs):
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "think": False,
            "options": {"temperature": 0.2, "num_predict": 200},
        }
        t0 = time.time()
        ttft = None
        n_tok = 0
        last = None
        try:
            for ch in post_stream(base.rstrip("/") + "/api/chat", payload):
                if ch.get("message", {}).get("content"):
                    if ttft is None:
                        ttft = time.time() - t0
                    n_tok += 1
                    last = ch
                if ch.get("done"):
                    gen_tokens = ch.get("eval_count") or n_tok
                    gen_ns = ch.get("eval_duration") or 0
                    total = time.time() - t0
                    results.append({
                        "run": i + 1,
                        "ttft_s": round(ttft, 3) if ttft else None,
                        "total_s": round(total, 2),
                        "tokens": gen_tokens,
                        "tok_per_s": round(gen_tokens / (gen_ns / 1e9), 2) if gen_ns else None,
                        "thinking": bool(str(last.get("message", {}).get("content", ""))
                                         .startswith("<think>") if last else False),
                        "text": str(last.get("message", {}).get("content", ""))[:200] if last else "",
                    })
                    break
        except Exception as exc:  # noqa: BLE001
            results.append({"run": i + 1, "error": "%s: %s" % (type(exc).__name__, exc)})
    return results


def run_mm(base: str, model: str) -> dict:
    """多模态：图片编码后提问，检查是否真的认出内容。"""
    if not os.path.exists(IMG):
        return {"error": "测试图不存在: %s" % IMG}
    b64 = base64.b64encode(open(IMG, "rb").read()).decode("ascii")
    asks = [
        ("图中写了哪些字？把文字原样念出来。", ["YHLZ", "2049", "红色", "方块"]),
        ("图里有几个蓝色方块？什么颜色和形状的图形各有多少？", ["3", "三", "蓝", "方"]),
    ]
    out = []
    for q, keys in asks:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": q, "images": [b64]}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.1, "num_predict": 300},
        }
        t0 = time.time()
        try:
            req = urllib.request.Request(
                base.rstrip("/") + "/api/chat",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read().decode("utf-8"))
            ans = str((d.get("message") or {}).get("content") or "")
            hits = [k for k in keys if k in ans]
            out.append({"q": q, "answer": ans[:400], "hits": hits,
                        "ok": len(hits) >= 2, "sec": round(time.time() - t0, 2)})
        except Exception as exc:  # noqa: BLE001
            out.append({"q": q, "error": "%s: %s" % (type(exc).__name__, exc)})
    return {"image": os.path.relpath(IMG, ROOT), "asks": out}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.5:2b")
    ap.add_argument("--base-url", default="http://127.0.0.1:11434")
    ap.add_argument("--runs", type=int, default=2)
    args = ap.parse_args()

    prompt = "用一句话介绍一下你自己，然后讲一个关于雪的笑话。"
    print("=" * 70)
    print("Qwen3.5 冒烟测试 ｜ %s" % args.model)
    print("=" * 70)

    print("\n【一、性能】warm-up 1 次 + 正式 %d 次" % args.runs)
    run_perf(args.base_url, args.model, "你好", 1)   # warm-up（含加载）
    perf = run_perf(args.base_url, args.model, prompt, args.runs)
    for r in perf:
        if "error" in r:
            print("  run%d 失败: %s" % (r["run"], r["error"]))
        else:
            print("  run%d  TTFT=%.2fs  总=%.2fs  %s tok  %.1f tok/s"
                  % (r["run"], r["ttft_s"] or 0, r["total_s"], r["tokens"],
                     r["tok_per_s"] or 0))

    print("\n【二、多模态】同一张图问两题")
    mm = run_mm(args.base_url, args.model)
    for a in mm.get("asks", []):
        if "error" in a:
            print("  ❌ %s" % a["error"])
        else:
            print("  %s\n     答: %s\n     命中: %s  -> %s"
                  % (a["q"], a["answer"][:160].replace("\n", " "),
                     a["hits"], "✅ 有" if a["ok"] else "⚠️ 弱"))

    os.makedirs(OUT_DIR, exist_ok=True)
    tag = args.model.replace(":", "_").replace("/", "_")
    p = os.path.join(OUT_DIR, "smoke_%s.json" % tag)
    with io.open(p, "w", encoding="utf-8") as fh:
        json.dump({"model": args.model, "base_url": args.base_url,
                   "perf": perf, "multimodal": mm}, fh, ensure_ascii=False, indent=1)
    print("\n结果已存: %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
