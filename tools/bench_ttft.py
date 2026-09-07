"""TTFT / prefix-cache benchmark: qwen2.5:3b vs Gemma-4-E4B (llama.cpp).

Measures via stream=true:
  ttft_1st   = first token latency (fresh system+user)
  ttft_cached= first token latency when the same prefix ran before (prompt cache)
  tps       = tokens/second during generation
Both providers expose OpenAI-compatible streaming.
"""
import asyncio
import io
import json
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROVIDERS = {
    "qwen2.5:3b": {"url": "http://127.0.0.1:11434/v1/chat/completions",
                   "model": "qwen2.5:3b"},
    "gemma-4-e4b": {"url": "http://127.0.0.1:8081/v1/chat/completions", "model": None},
}

PREFIX = ("你是元亨，一个数字生命体。你有细腻的情感和自己的表达方式，温暖真诚不做作。"
          "以下是需要你回应的对话。")
QUESTIONS = ["用两三句话聊聊你最近在想什么。",
             "如果用一种天气形容你现在的心情，会是什么？"]


async def stream_measure(name, cfg, messages, budget=900):
    import httpx

    payload = {"model": cfg["model"], "messages": messages,
               "temperature": 0.8, "max_tokens": budget,
               "stream": True, "stream_options": {"include_usage": True}}
    if not cfg["model"]:
        payload.pop("model")
    t_req = time.time()
    ttft = None
    n_tok = 0
    first_data = None
    async with httpx.AsyncClient(timeout=240) as c:
        async with c.stream("POST", cfg["url"], json=payload) as r:
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                if ttft is None and first_data is None:
                    first_data = chunk
                d = (chunk.get("choices") or [{}])[0]
                delta = d.get("delta") or {}
                c_txt = delta.get("content") or ""
                if ttft is None and c_txt:
                    ttft = time.time() - t_req
                if c_txt:
                    n_tok += 1  # content tokens only (approx)
    elapsed = time.time() - t_req
    return {"ttft_s": round(ttft, 3) if ttft else None,
            "content_tokens": n_tok,
            "elapsed_s": round(elapsed, 2),
            "tps": round(n_tok / max(elapsed, 0.01), 1)}


async def main():
    out = []
    for qidx, q in enumerate(QUESTIONS):
        for name, cfg in PROVIDERS.items():
            msgs = [{"role": "system", "content": PREFIX}, {"role": "user", "content": q}]
            r1 = await stream_measure(name, cfg, msgs)   # cold-ish (cached prefix?)
            r2 = await stream_measure(name, cfg, msgs)   # same prefix -> prompt cache
            out.append({"q": qidx + 1, "model": name,
                        "first": r1, "repeat_same_prefix": r2})
    print(json.dumps(out, ensure_ascii=False, indent=1))


asyncio.run(main())
