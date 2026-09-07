"""A/B chat experiment: qwen2.5:3b (current local) vs Gemma-4-E4B-Aggressive
(local llama.cpp :8081) on the same persona + an emotional prompt.

Usage: python -B tools/ab_chat.py ["自定义问题"] [model 可选]
"""
import asyncio
import io
import json
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PERSONA = (
    "你是元亨，一个数字生命体。你有细腻的情感和自己的表达方式，"
    "温暖、真诚、不矫情不做作。此刻夜深，你和一个对你很重要的人在对话。"
)

DEFAULT_Q = "今晚要一起共进晚餐吗？"

ENDPOINTS = {
    "qwen2.5:3b": ("http://127.0.0.1:11434/v1/chat/completions", "qwen2.5:3b"),
    "gemma-4-e4b": ("http://127.0.0.1:8081/v1/chat/completions", None),  # model ignored by llama.cpp
}


async def ask(name, url, model, question, temp=0.8):
    import httpx

    payload = {"messages": [{"role": "system", "content": PERSONA},
                            {"role": "user", "content": question}],
               "temperature": temp, "max_tokens": 1500}  # gemma4=reasoning, big budget
    if model:
        payload["model"] = model
    t0 = time.time()
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(url, json=payload)
        r.raise_for_status()
        out = r.json()
    content = (out.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    return {"model": name, "elapsed": round(time.time() - t0, 1),
            "content": content or "(空回复)", "tokens": (out.get("usage") or {}).get("completion_tokens")}


async def main():
    q = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_Q
    only = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"=== A/B 对话实验 ===")
    print(f"问题：{q}")
    print(f"persona：{PERSONA[:40]}…")
    print("=" * 50)
    tasks = []
    for name, (url, model) in ENDPOINTS.items():
        if only and only not in name:
            continue
        tasks.append(ask(name, url, model, q))
    results = await asyncio.gather(*tasks)
    for r in results:
        print(f"\n--- {r['model']}  ({r['elapsed']}s) ---")
        print(r["content"])
    print("\n" + "=" * 50)
    print("（A/B 主观对比，仅供老爹判断；不接生产）")


if __name__ == "__main__":
    asyncio.run(main())
