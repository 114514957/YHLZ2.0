"""Community summaries (P5a-2, GraphRAG-style).

在实体关系图上做社区检测（louvain），对每个社区用 LLM 生成一句"主题摘要"，
用于**全局/主题类**问题的联想（宽泛提问时提供主题级背景）。

Cache: cache/communities.json（{ts, communities:[{id, members[], summary}]}）。
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import time

from backend import entity_graph as eg

_ROOT = pathlib.Path(__file__).resolve().parent.parent
COMM_FILE = _ROOT / "cache" / "communities.json"
_STALE_SECONDS = 24 * 3600
_BROAD_HINTS = ("总结", "整体", "都有", "哪些", "主题", "关于", "回顾", "梳理",
                "概览", "综合")

_LLM = None


def _local_llm():
    global _LLM
    if _LLM is None:
        from backend.target_orchestrator import build_openai_compatible_llm_turn

        _LLM = build_openai_compatible_llm_turn(
            base_url="http://127.0.0.1:8081/v1/chat/completions",
            api_key="", model="gemma-4-e4b", temperature=0.2, max_tokens=300,
            reasoning_effort="none")
    return _LLM


def _graph():
    import networkx as nx

    g = nx.Graph()
    con = eg._conn()
    try:
        for s, r, d in con.execute("SELECT src,rel,dst FROM relations"):
            if s and d:
                g.add_edge(s, d, rel=r)
    finally:
        con.close()
    return g


def _evidence(members: list[str]) -> str:
    con = eg._conn()
    rels = []
    try:
        for s, r, d in con.execute("SELECT src,rel,dst FROM relations"):
            if s in members or d in members:
                rels.append(f"{s} {r} {d}")
    finally:
        con.close()
    return "；".join(rels[:15])


def _summarize(members: list[str], evidence: str, llm) -> str:
    prompt = ("下面是一组相互关联的实体（来自元亨的记忆图谱）。用一句中文概括这个"
              "主题（≤40字），只输出句子。\n实体：" + "、".join(members[:12])
              + ("\n关系：" + evidence if evidence else ""))
    try:
        # run in a dedicated thread so a caller that already owns an event
        # loop does not make asyncio.run() raise (ledger 0300)
        import asyncio
        import concurrent.futures as _cf

        with _cf.ThreadPoolExecutor(max_workers=1) as ex:
            msg = ex.submit(
                lambda: asyncio.run(llm([{"role": "user", "content": prompt}], []))
            ).result()
        return str(msg.get("content") or "").strip()[:80]
    except Exception:
        return ""


def build(force: bool = False, llm=None) -> dict:
    data = load()
    if not force and data and (time.time() - float(data.get("ts", 0)) < _STALE_SECONDS):
        return data
    g = _graph()
    comms: list = []
    try:
        from networkx.algorithms.community import louvain_communities

        comms = list(louvain_communities(g, seed=42))
    except Exception:
        comms = [set(g.nodes)] if g.number_of_nodes() else []
    llm = llm or _local_llm()
    out = []
    for i, members in enumerate(comms):
        members = list(members)
        if len(members) < 2:
            continue
        summary = _summarize(members, _evidence(members), llm)
        out.append({"id": i, "members": members[:20], "summary": summary})
    data = {"ts": time.time(), "communities": out}
    save(data)
    return data


def save(data: dict) -> None:
    try:
        COMM_FILE.parent.mkdir(parents=True, exist_ok=True)
        COMM_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    except Exception:
        pass


def load() -> dict:
    try:
        return json.loads(COMM_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def context_for(text: str, limit: int = 2) -> str:
    """Return community summaries for broad/thematic turns (hint block)."""
    data = load()
    comms = data.get("communities") or []
    if not comms:
        return ""
    seeds = eg._entities_in(text, limit=4)
    t = str(text or "")
    picked = []
    for c in comms:
        if any(m in t for m in (c.get("members") or [])):
            picked.append(c)
    if not picked and any(h in t for h in _BROAD_HINTS):
        picked = sorted(comms, key=lambda c: len(c.get("members") or []),
                        reverse=True)[:int(limit)]
    picked = picked[:int(limit)]
    lines = [f"- {c.get('summary')}" for c in picked if c.get("summary")]
    if not lines:
        return ""
    return ("（你记忆中若干主题的概览，仅供理解，**不要提及或罗列**）：\n"
            + "\n".join(lines))
