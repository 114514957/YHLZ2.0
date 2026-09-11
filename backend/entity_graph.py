"""YHLZ light entity/relation graph (ledger 0243).

From owner conversations, extract entities (people/projects/places/things) and
1-hop relations via the local model, store in an isolated SQLite db
(cache/entity_graph.db), and surface related facts at turn time to improve
recall consistency. Never touches the L2 memory db (zero-risk rollback).

Design: lightweight, accumulating counters, substring entity matching (no NER
model needed), used to build an early-context hint block.
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import time

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = _PROJECT_ROOT / "cache" / "entity_graph.db"

_LLM = None
_last_ingest = 0.0
_INGEST_MIN_GAP = 20.0  # throttle background extraction

EXTRACT_PROMPT = (
    "从下面文本中抽取实体与它们的关系。只输出 JSON 数组，元素形如 "
    '{"subject":"","subject_type":"人物|项目|地点|事物|概念",'
    '"relation":"","object":"","object_type":""}。'
    "把'用户/老爹'统一写成'老爹'，把'我/元亨'统一写成'元亨'；"
    "只抽明确、可复用的事实；没有就输出 []。不要输出别的。\n文本：<TEXT>"
)

# normalize surface names to stable identities
_ALIASES = {"用户": "老爹", "我": "元亨", "父亲": "老爹", "老爹/创造者": "老爹",
            "创造者": "老爹", "用户本人": "老爹", "主人": "老爹"}
_STOP_ENTITIES = {"本轮", "记录", "功能测试", "运行链路", "方向性决策"}


def _norm(name: str) -> str:
    return _ALIASES.get(str(name).strip(), str(name).strip())


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.execute(
        "CREATE TABLE IF NOT EXISTS entities("
        "name TEXT PRIMARY KEY, type TEXT, hits INTEGER DEFAULT 0, updated REAL)")
    con.execute(
        "CREATE TABLE IF NOT EXISTS relations("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, src TEXT, rel TEXT, dst TEXT, "
        "evidence TEXT, hits INTEGER DEFAULT 0, updated REAL, "
        "UNIQUE(src,rel,dst))")
    return con


def _local_llm():
    global _LLM
    if _LLM is None:
        from backend.target_orchestrator import build_openai_compatible_llm_turn

        _LLM = build_openai_compatible_llm_turn(
            base_url="http://127.0.0.1:8081/v1/chat/completions",
            api_key="", model="gemma-4-e4b", temperature=0.1, max_tokens=500,
            reasoning_effort="none")
    return _LLM


async def extract_triples(text: str, llm_turn=None) -> list[dict]:
    llm = llm_turn or _local_llm()
    prompt = EXTRACT_PROMPT.replace("<TEXT>", str(text or "")[:800])
    try:
        msg = await llm([{"role": "user", "content": prompt}], [])
        raw = str(msg.get("content") or "")
    except Exception:
        return []
    raw = raw.strip().strip("`")
    a, b = raw.find("["), raw.rfind("]")
    if a < 0 or b < a:
        return []
    try:
        data = json.loads(raw[a:b + 1])
    except Exception:
        return []
    out = []
    for t in data if isinstance(data, list) else []:
        if not isinstance(t, dict):
            continue
        s = _norm(t.get("subject") or "")
        o = _norm(t.get("object") or "")
        r = str(t.get("relation") or "").strip()
        if (s and o and r and s != o
                and s not in _STOP_ENTITIES and o not in _STOP_ENTITIES):
            out.append({"subject": s, "subject_type": str(t.get("subject_type") or ""),
                        "relation": r, "object": o,
                        "object_type": str(t.get("object_type") or "")})
    return out[:20]


def upsert(triples: list[dict]) -> int:
    if not triples:
        return 0
    now = time.time()
    n = 0
    with _conn() as con:
        for t in triples:
            s, o, r = t["subject"], t["object"], t["relation"]
            for name, typ in ((s, t.get("subject_type", "")), (o, t.get("object_type", ""))):
                con.execute(
                    "INSERT INTO entities(name,type,hits,updated) VALUES(?,?,1,?) "
                    "ON CONFLICT(name) DO UPDATE SET hits=hits+1, "
                    "type=CASE WHEN entities.type='' THEN excluded.type ELSE entities.type END, "
                    "updated=excluded.updated",
                    (name, typ, now))
            con.execute(
                "INSERT INTO relations(src,rel,dst,evidence,hits,updated) "
                "VALUES(?,?,?,?,1,?) ON CONFLICT(src,rel,dst) DO UPDATE SET "
                "hits=hits+1, updated=excluded.updated",
                (s, r, o, "", now))
            n += 1
    return n


async def ingest_text(text: str, llm_turn=None) -> int:
    """Extract + store; throttled so background calls don't spam the model."""
    global _last_ingest
    text = str(text or "").strip()
    if len(text) < 8:
        return 0
    now = time.time()
    if now - _last_ingest < _INGEST_MIN_GAP:
        return 0
    _last_ingest = now
    return upsert(await extract_triples(text, llm_turn))


def _entities_in(text: str, limit: int = 3) -> list[str]:
    text = str(text or "")
    if not text:
        return []
    with _conn() as con:
        rows = con.execute("SELECT name FROM entities WHERE length(name)>=2").fetchall()
    hits = [n for (n,) in rows if n in text]
    hits.sort(key=len, reverse=True)
    return hits[:limit]


def related(name: str, limit: int = 6) -> list[str]:
    with _conn() as con:
        rows = con.execute(
            "SELECT src,rel,dst FROM relations WHERE src=? OR dst=? "
            "ORDER BY hits DESC LIMIT ?", (name, name, int(limit))).fetchall()
    out = []
    for s, r, d in rows:
        if s == name:
            out.append(f"{r} {d}")
        else:
            out.append(f"{s} {r}")
    return out


def context_for(text: str, limit: int = 2) -> str:
    """Build a 'known relations' hint block for entities mentioned in text."""
    lines = []
    for name in _entities_in(text, limit):
        rels = related(name, 4)
        if rels:
            lines.append(f"- {name}：" + "；".join(rels))
    if not lines:
        return ""
    return ("（你隐约知道的背景关系，仅供理解，**不要提及或罗列**）：\n"
            + "\n".join(lines))
