"""Prompt-latency experiment (ledger 0206): does system-prompt size / history
affect TTFT on qwen2.5:3b (local)? Tests:
  A) short system   vs   long system   -> first-call TTFT (prefill cost)
  B) same long system twice            -> prefix-cache effect
Measure via stream TTFT.
"""
import asyncio
import io
import json
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
URL = "http://127.0.0.1:11434/v1/chat/completions"
MODEL = "qwen2.5:3b"

SHORT = "你是元亨。"
LONG = (
    "你是元亨，一个数字生命体。你有自己的人格：开放求新、尽责自持、生动有度、协作利他、稳定温和。"
    "你是元亨本身，不是工具外壳。诚实第一：做不到直说并讲清缺什么。你有独立思辨。"
    "可用工具：ledger.search（查台账历史决策）；memory.recall（回忆自己的记忆）；memory.save（写记忆）；"
    "diary.write（写自己日记）；task.plan（管自己任务表）；kb.query/kb.add（知识库存取）；"
    "qq.status/qq.process/qq.export/qq.digest/qq.summarize（QQ知识捕获链）；skill.search/skill.feedback；"
    "file.list/file.read（本地文件）；web.fetch/web.search（联网）；owner.approve（审批）。"
    "system.time（时间）。请自然对话，不机械收尾。"
) * 3  # ~ 1200 tokens worth of system text


async def ttft(system, user, repeat=1):
    best = None
    for _ in range(repeat):
        payload = {"model": MODEL,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}],
                   "temperature": 0.6, "max_tokens": 30, "stream": True}
        import httpx

        t_req = time.time()
        first = None
        async with httpx.AsyncClient(timeout=180) as c:
            async with c.stream("POST", URL, json=payload) as r:
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    d = line[5:].strip()
                    if d == "[DONE]":
                        break
                    try:
                        ch = json.loads(d)
                    except Exception:
                        continue
                    delta = (ch.get("choices") or [{}])[0].get("delta") or {}
                    if first is None and delta.get("content"):
                        first = time.time() - t_req
        if first is not None and (best is None or first < best):
            best = first
    return best


async def main():
    q = "你好"
    r = {}
    print("=== Prompt-Latency (qwen2.5:3b) ===")
    r["A_short_1st"] = await ttft(SHORT, q, 1)
    r["A_long_1st"] = await ttft(LONG, q, 1)
    r["B_long_2nd_cache"] = await ttft(LONG, q, 1)  # same long system ran above once
    r["B_long_3rd"] = await ttft(LONG, q, 1)
    for k, v in r.items():
        print(f"{k}: {round(v,3) if v else None}s")
    print("长系统token约:", len(LONG))
    if r.get("A_short_1st") and r.get("A_long_1st"):
        print(f"长vs短 首TTFT 比: x{round(r['A_long_1st']/r['A_short_1st'],1)}")
    if r.get("B_long_2nd_cache") and r.get("A_long_1st"):
        print(f"缓存命中 降幅: {round((1-r['B_long_2nd_cache']/r['A_long_1st'])*100,0)}%")


asyncio.run(main())
