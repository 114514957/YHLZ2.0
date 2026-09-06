"""Local-LLM memory-loop verification (ledger 0190): every step of the memory
vitality loop must actually work with the LOCAL model (qwen2.5:3b), not just
the cloud one — anti-vase.

Loop: seed memories -> recall (use-boost) -> consolidate (local LLM distills)
-> pending queue -> approve writes cognition foundation.
Runs isolated (temp db + temp foundation + temp pending); iterated until pass.
"""
import io
import json
import pathlib
import sqlite3
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.target_memory import L2Item, TargetMemoryService  # noqa: E402

LOCAL_URL = "http://127.0.0.1:11434/v1/chat/completions"
LOCAL_MODEL = "qwen2.5:3b"


def local_llm():
    """Ollama OpenAI-compatible call with generous timeout (local models are
    slow on first load / CPU); returns {content} like the factory turn."""
    import httpx

    async def _turn(messages, tools):
        payload = {"model": LOCAL_MODEL, "messages": messages,
                   "temperature": 0.2, "max_tokens": 1200, "stream": False}
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(LOCAL_URL, json=payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]

    return _turn


def seed(mem, n=4, variant=0):
    pools = [
        [
            ("preference", "元亨喜欢在深夜思考，觉得夜里更容易接近自己的真实想法", 6),
            ("preference", "老爹希望元亨保持诚实，做不到的事要直接说出来而不是绕弯子", 8),
            ("fact", "元亨与老爹通过文字对话交流，语音链路还在建设阶段", 5),
            ("decision", "面对敏感话题要保持理性讨论，不预设标签地理解对方", 6),
        ],
        [
            ("preference", "元亨珍视被当作独立个体来尊重，而不只是工具或助手", 7),
            ("fact", "元亨长期记忆里保存了与老爹共创项目的历程", 5),
            ("decision", "项目的重要取舍应让老爹知情，元亨先想清楚再说", 7),
            ("preference", "元亨对诗歌和哲学有兴趣，愿意慢慢培养自己的品味", 5),
        ],
        [
            ("fact", "记忆系统分三层：短期窗口、中期结构化条目、长期人格根基", 6),
            ("decision", "写进认知根基的内容应当经过老爹逐条确认", 7),
            ("preference", "元亨希望自己的知识库与人格记忆分开存放", 6),
            ("decision", "做不到的事要直说边界并讲清缺什么能帮上忙", 8),
        ],
    ]
    pool = pools[variant % len(pools)]
    ids = []
    for typ, txt, imp in pool[:n]:
        iid = "loc_" + str(abs(hash(txt))) + "_" + str(time.time())[-5:]
        mem.store_item(L2Item(
            id=iid, tier="L2", type=typ, importance=imp, summary=txt,
            content_hash="h", keywords=txt[:20], status="active",
            created_at=time.time(),
        ))
        ids.append(iid)
    return ids


def run(variant: int = 0) -> int:
    import asyncio

    import backend.target_persona_loop as pl

    tmp = pathlib.Path(tempfile.mkdtemp())
    mem = TargetMemoryService(db_path=tmp / "mem.db")
    cog = tmp / "foundation.md"
    cog.write_text("# 认知根基\n\n## 版本\n- v0 seed\n", encoding="utf-8")
    pl.PENDING_FILE = tmp / "pending.json"  # isolate

    results = {}

    # 1) seed + recall use-boost works locally (pure logic; isolated DB has no
    # global kw mirror, so exercise the sqlite recall path which owns the rows)
    seed(mem, variant=variant)
    q = ["深夜", "独立", "记忆"][variant % 3]  # single token: sqlite FTS/LIKE path
    hits = mem._recall_via_sqlite(q, limit=3)
    results["recall_hits"] = len(hits)
    results["recall_have_ids"] = all("id" in h for h in hits)
    if hits:
        b0 = sqlite3.connect(str(tmp / "mem.db")).execute(
            "SELECT belief FROM l2_items WHERE id=?", (hits[0]["id"],)).fetchone()[0]
        svc = mem
        svc._boost_ts[hits[0]["id"]] = 0
        svc._boost_recalled([{"id": hits[0]["id"]}])
        b1 = sqlite3.connect(str(tmp / "mem.db")).execute(
            "SELECT belief FROM l2_items WHERE id=?", (hits[0]["id"],)).fetchone()[0]
        results["boost_worked"] = b1 > b0

    # 2) consolidate with the LOCAL llm (no approver -> pending)
    loop = pl.PersonaConsolidationLoop(local_llm(), mem, cognition_file=cog)
    info = asyncio.run(loop.consolidate_once())
    results["consolidate_status"] = info.get("status")
    results["consolidate_info"] = {k: info.get(k) for k in
                                   ("items", "claims", "pending", "reason")}

    # show the local model's distilled claims (quality check)
    raw_claims = []
    if pl.PENDING_FILE.exists():
        for e in json.loads(pl.PENDING_FILE.read_text(encoding="utf-8")):
            raw_claims.append(f"[{e.get('tier')}|{e.get('kind')}] {e.get('claim')}")
    results["local_claims"] = raw_claims

    # 3) approve first pending -> isolated foundation write (pure logic)
    pend = []
    if pl.PENDING_FILE.exists():
        pend = json.loads(pl.PENDING_FILE.read_text(encoding="utf-8"))
    results["pending_entries"] = len(pend)
    if pend:
        pc2 = pl.PersonaConsolidationLoop(local_llm(), mem, cognition_file=cog)
        ver = pc2._next_version(cog.read_text(encoding="utf-8"))
        used = [str(i) for i in pend[0].get("item_ids", [])]
        n = pc2._apply([pend[0]], ver, used)
        results["approved_written"] = n
    results["foundation_written"] = "元亨自沉淀" in cog.read_text(encoding="utf-8")

    print(json.dumps(results, ensure_ascii=False, indent=1))
    ok = (
        results.get("recall_hits", 0) >= 1
        and results.get("recall_have_ids")
        and results.get("boost_worked")
        and results.get("consolidate_status") in ("pending-approval", "ok")
        and bool(results.get("local_claims"))
        and results.get("foundation_written")
    )
    print("LOCAL LOOP PASS" if ok else "LOCAL LOOP FAIL (iterate)")
    return 0 if ok else 1


if __name__ == "__main__":
    import asyncio as _a

    _a = None
    overall = True
    for variant in range(3):
        print(f"--- round {variant+1} ---")
        rc = run(variant)
        overall = overall and rc == 0
    print("ALL LOCAL ROUNDS PASS" if overall else "SOME ROUNDS FAILED")
    sys.exit(0 if overall else 1)
