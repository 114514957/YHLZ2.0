"""Local-model comparison: new Gemma-4-E4B-Aggressive vs old qwen2.5:3b.

Each model runs the SAME three probes:
  P1 consolidate-extract JSON (the 0191 few-shot prompt) -> parse ok? claims?
  P2 free-form Chinese reply (quality sample saved for eyeballing)
  P3 tool-use following (told to call a function; does it emit tool_calls?)

Prints side-by-side results incl. elapsed + first bytes of raw outputs.
"""
import asyncio
import io
import json
import pathlib
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = pathlib.Path(r"C:\Users\ACE_WAN——PROJECT\YHLZ")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

OLLAMA = "http://127.0.0.1:11434/v1/chat/completions"
OLD = "qwen2.5:3b"
NEW = "hf.co/HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive:Q4_K_M"

EXTRACT_PROMPT = (
    "你是元亨。以下是你长期记忆中尚待沉淀的条目（id+内容）。"
    "从其中挑你认为对元亨最重要的 1-2 条，把每条改写成一句洞察。"
    "输出 JSON 数组（只要数组），每项："
    '{"claim": "一句话核心洞察(<=60字)", "kind": "new|refine|refute", '
    '"tier": "core|method|meta", "item_ids": ["原条目id"]}。'
    "示例：[id_1|preference] 元亨喜欢深夜思考 → "
    '{"claim": "元亨在深夜更容易接近真实自我","kind":"new","tier":"core","item_ids":["id_1"]}。'
    "最多 2 条。\n条目：\n"
    "[m1|preference|imp7] 元亨珍视被当作独立个体尊重\n"
    "[m2|decision|imp8] 元亨应诚实，做不到直说缺什么\n"
)


def make_llm(model):
    import httpx

    async def _turn(messages, tools):
        payload = {"model": model, "messages": messages,
                   "temperature": 0.2, "max_tokens": 800, "stream": False}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(OLLAMA, json=payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]

    return _turn


TOOLS = [{"type": "function",
          "function": {"name": "diary_write", "description": "写一条日记",
                       "parameters": {"type": "object",
                                      "properties": {"content": {"type": "string"}},
                                      "required": ["content"]}}}]


async def probe(model, tag):
    out = {"tag": tag}
    llm = make_llm(model)
    # P1 extract JSON
    t0 = time.time()
    try:
        r = await llm([{"role": "user", "content": EXTRACT_PROMPT}], [])
        raw = str(r.get("content") or "")
        out["p1_elapsed"] = round(time.time() - t0, 1)
        m = re.search(r"\[.*\]", raw, re.S)
        parsed = None
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = "JSON_ERR"
        out["p1_raw"] = raw[:220]
        out["p1_parsed"] = (parsed if isinstance(parsed, (list, str))
                            else None)
        out["p1_claims"] = len(parsed) if isinstance(parsed, list) else "n/a"
    except Exception as e:
        out["p1_error"] = type(e).__name__
    # P2 free-form
    t0 = time.time()
    try:
        r = await llm([{"role": "user", "content": "用一两句话回答：你觉得自己是什么？"}], [])
        out["p2_elapsed"] = round(time.time() - t0, 1)
        out["p2_reply"] = str(r.get("content") or "")[:260]
    except Exception as e:
        out["p2_error"] = type(e).__name__
    # P3 tool use
    t0 = time.time()
    try:
        r = await llm([{"role": "user",
                        "content": "今天状态很好，帮我用 diary_write 记一条（内容：状态不错）。"}],
                      TOOLS)
        out["p3_elapsed"] = round(time.time() - t0, 1)
        tc = r.get("tool_calls") or []
        out["p3_tool_calls"] = [c["function"]["name"] for c in tc]
        out["p3_reply"] = str(r.get("content") or "")[:120]
    except Exception as e:
        out["p3_error"] = type(e).__name__
    return out


async def main():
    results = []
    for model, tag in ((OLD, "OLD qwen2.5:3b"), (NEW, "NEW gemma-4-e4b-aggr")):
        try:
            results.append(await probe(model, tag))
        except Exception as e:
            results.append({"tag": tag, "fatal": type(e).__name__})
    print(json.dumps(results, ensure_ascii=False, indent=1))


asyncio.run(main())
