"""QQ knowledge extraction pipeline: candidates jsonl -> cloud LLM refine -> L2 knowledge.

Cloud-only refinement (user decision: local prefilter, cloud refine).
Cursor-based: processed candidate lines are tracked, failures leave the cursor
untouched so batches retry.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re
import sys
import time

BASE = pathlib.Path(__file__).resolve().parent.parent
CAND_DIR = BASE / "cache" / "qqwatch"
STATE_FILE = CAND_DIR / "state.json"
L2_DB = BASE / "cache" / "memstore" / "memstore.db"

EXTRACT_PROMPT = """你是技术知识捕获精炼器。输入来自 QQ 技术/AI 群聊的候选消息（JSONL）。
从中抽取**纯技术/方法论内容**，例如：技术原理与要点、架构与实现方法、工具/框架/模型的用法与参数、踩坑经验、可操作的技术建议。
严格丢弃一切非技术内容：闲聊、情绪、评价、广告、资源求问（求链接/求资源本身）、生活话题、仅观点无技术量的讨论。
输出纯 JSON（不要 markdown fence）：{"items": [{"point": "一句话精炼技术要点(≤80字)", "quote": "原文字段中支撑它的短引用(≤60字)", "cat": "tech|method"}]}
宁可少而精。若无技术内容输出 {"items": []}。"""

SYSTEM_MSG = {"role": "system", "content": EXTRACT_PROMPT}


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"processed_lines": 0}


def _save_state(st: dict) -> None:
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def read_pending_candidates(max_items: int = 12) -> tuple[list[dict], int]:
    """Read unprocessed candidate lines; return (items, total_lines)."""
    st = _load_state()
    f = CAND_DIR / "all.jsonl"
    if not f.exists():
        return [], 0
    lines = f.read_text(encoding="utf-8").splitlines()
    pending = []
    for i, line in enumerate(lines[st["processed_lines"]:], start=st["processed_lines"]):
        if len(pending) >= max_items:
            break
        try:
            pending.append(json.loads(line))
        except Exception:
            continue
    return pending, len(lines)


def parse_llm_json(text: str) -> dict:
    """Strip fences/spurious text around JSON output."""
    t = text.strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise ValueError("no JSON object in LLM output")
    return json.loads(m.group(0))


def build_user_message(items: list[dict]) -> str:
    blocks = []
    for it in items:
        g = it.get("group_id", "")
        t = (it.get("text") or "").strip().replace("\n", " ")[:600]
        blocks.append(json.dumps({"group": g, "msg": t}, ensure_ascii=False))
    return "\n".join(blocks)


async def extract(items: list[dict], llm_turn) -> list[dict]:
    """Run cloud refinement on a batch -> normalized item list."""
    if not items:
        return []
    resp = await llm_turn(
        [SYSTEM_MSG, {"role": "user", "content": build_user_message(items)}],
        [],
    )
    content = resp.get("content") or ""
    parsed = parse_llm_json(content)
    out = []
    for it in (parsed.get("items") or [])[:40]:
        point = str(it.get("point", "")).strip()
        if not point or len(point) < 8:
            continue
        out.append({
            "point": point[:120],
            "quote": str(it.get("quote", ""))[:100],
            "cat": str(it.get("cat", "tech"))[:12] if it.get("cat") in ("tech", "method") else "tech",
        })
    return out


def store_items(items: list[dict], *, group_id: str = "", ts: int = 0,
                db_path: pathlib.Path | None = None) -> int:
    """Persist refined points into the Yuanheng KB (ledger 0179: knowledge
    lives in the KB, not in the persona memory pool). Returns stored count."""
    from backend.yuanheng_kb import kb_add

    n = 0
    for it in items:
        cat = str(it.get("cat", "tech")) if it.get("cat") in ("tech", "method") else "tech"
        res = kb_add(
            it["point"],
            category=cat,
            source=f"qq:g{group_id}:t{ts}",
            detail=it.get("quote", ""),
            created_at=float(ts or 0),
        )
        if res.startswith("已入库"):
            n += 1
    return n


def build_llm_turn(max_tokens: int = 1200):
    """Cloud-only (no local fallback) DeepSeek turn for extraction."""
    import os

    from backend.env_loader import ensure_env_loaded
    from backend.target_orchestrator import build_openai_compatible_llm_turn

    ensure_env_loaded()
    key = os.getenv("DEEPSEEK_API_KEY", "")
    return build_openai_compatible_llm_turn(
        api_key=key, model="deepseek-chat", temperature=0.1,
        max_tokens=int(max_tokens), fallback_base_url=None,
    )


async def run_batch(max_items: int = 12, dry: bool = False,
                    llm_turn: Any = None) -> dict:
    st = _load_state()
    start_cursor = int(st.get("processed_lines", 0))
    items, total_lines = read_pending_candidates(max_items)
    if not items:
        return {"processed": 0, "stored": 0, "lines": total_lines, "reason": "no-candidates"}
    refined = await extract(items, llm_turn if llm_turn is not None else build_llm_turn())
    src_grp = str(items[0].get("group_id", "") or "")
    src_ts = int(items[0].get("ts", 0) or 0)
    stored = 0 if dry else store_items(refined, group_id=src_grp, ts=src_ts)
    if not dry:
        # advance cursor by the lines actually consumed (never to file end)
        _save_state({"processed_lines": start_cursor + len(items)})
    return {"processed": len(items), "refined": len(refined), "stored": stored, "lines": total_lines}


def digest(date_str: str | None = None, db_path: pathlib.Path | None = None) -> pathlib.Path:
    """Daily human-readable digest of that day's KB knowledge (QQ-sourced)."""
    import sqlite3

    from backend.yuanheng_kb import DEFAULT_KB_DB

    date_str = date_str or time.strftime("%Y-%m-%d")
    day_start, day_end = date_str + " 00:00", date_str + " 23:59"
    ts0 = time.mktime(time.strptime(day_start, "%Y-%m-%d %H:%M"))
    ts1 = ts0 + 86400
    con = sqlite3.connect(str(DEFAULT_KB_DB))
    rows = con.execute(
        "SELECT summary, source, category, created FROM kb_items "
        "WHERE status='active' AND created>=? AND created<? ORDER BY created",
        (ts0, ts1),
    ).fetchall()
    con.close()
    out_dir = BASE / "docs" / "知识汇编"
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"QQ-{date_str}.md"
    with open(f, "w", encoding="utf-8") as fp:
        fp.write(f"# QQ 知识汇编 {date_str}\n\n")
        if not rows:
            fp.write("（当日无捕获条目）\n")
        cats = {}
        for summary, _src, cat, _created in rows:
            cats.setdefault(cat or "tech", []).append(f"- {summary}\n")
        for cat, lines in cats.items():
            fp.write(f"## {cat}\n\n" + "".join(lines) + "\n")
    return f


async def digest_async(date_str: str | None = None,
                       db_path: pathlib.Path | None = None) -> str:
    return str(digest(date_str, db_path))


SUMMARY_PROMPT = """你是技术知识主编。输入一批从 QQ 技术群筛选出的知识条目（前缀 [QQtech]/[QQmethod]）。
任务：按技术主题聚类并产出一份**有提炼价值的主题总结**，供元亨（数字生命体）与其老爹阅读学习。
要求：
1. 归纳 4-8 个主题（如：模型架构与稀疏化 / 推理部署与工程 / Agent 与记忆设计 / 学习与认知 / …），主题名要精准；
2. 每主题下列"要点"：把同主题条目浓缩成 2-6 条有信息量的陈述（可保留关键技术名词与数字，丢弃重复与口水）；
3. 每主题末给一行"启发"：该主题对本项目（数字生命/本地语音智能体）值得借鉴的一句话结论。
输出纯 JSON（不要 markdown fence）：
{"topics": [{"topic": "主题名", "points": ["要点1", "要点2"], "takeaway": "一句启发"}]}
宁精勿滥。"""


async def summarize(db_path: pathlib.Path | None = None) -> dict:
    """Cluster all KB knowledge items into topic summaries (cloud only)."""
    import sqlite3

    from backend.yuanheng_kb import DEFAULT_KB_DB

    con = sqlite3.connect(str(DEFAULT_KB_DB))
    rows = con.execute(
        "SELECT summary, category, created FROM kb_items "
        "WHERE status='active' ORDER BY created"
    ).fetchall()
    con.close()
    if not rows:
        return {"topics": 0, "reason": "no-knowledge"}
    payload = "\n".join(f"- [{c}] {s}" for s, c, _ in rows)
    if len(payload) > 60000:
        payload = payload[:60000]
    resp = await build_llm_turn(max_tokens=4000)(
        [{"role": "system", "content": SUMMARY_PROMPT},
         {"role": "user", "content": payload}],
        [],
    )
    parsed = parse_llm_json(resp.get("content") or "")
    topics = (parsed.get("topics") or [])[:8]
    for t in topics:
        t["points"] = [str(p)[:200] for p in (t.get("points") or [])[:6]]
        t["takeaway"] = str(t.get("takeaway") or "")[:200]
    out_dir = BASE / "docs" / "知识汇编"
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"QQ-主题总结-{time.strftime('%Y-%m-%d')}.md"
    with open(f, "w", encoding="utf-8") as fp:
        fp.write(f"# QQ 技术知识主题总结（{len(rows)} 条 → {len(topics)} 主题）\n\n")
        for t in topics:
            fp.write(f"## {t['topic']}\n\n")
            for p in t["points"]:
                fp.write(f"- {p}\n")
            if t["takeaway"]:
                fp.write(f"\n> 启发：{t['takeaway']}\n\n")
    return {"topics": len(topics), "source_items": len(rows), "file": str(f)}


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "digest":
        f = digest(sys.argv[2] if len(sys.argv) > 2 else None)
        print("digest:", f)
        return 0
    if cmd == "summarize":
        res = asyncio.run(summarize())
        print(json.dumps(res, ensure_ascii=False))
        return 0
    res = asyncio.run(run_batch())
    print("result:", json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
    except Exception:
        pass
    sys.exit(main())
