"""记忆图谱 v2（2026-11-18）——MaiBot A_Memorix / HippoRAG2 思路的元亨版。

问题（旧 entity_graph 实测）：632 实体/752 关系，头部是「计划表→到点→09:30+daily」
「老爹→需要配合→跑工具」「尝试更新计划→失败」这类过程噪音；没有段落节点、没有证据、
没有置信度/时间，只做 1-hop 提示。

v2 的结构：
  docs(段落) ── mentions ── entities(实体)
                relations(实体间关系，带 evidence / confidence / doc_id / 时间)
检索：实体命中（名字/别名）→ 关系事实（按置信度×热度×新鲜度）→（可选）PPR 扩散。
写入：LLM OpenIE 抽取 + **证据子串校验** + 泛指/代词/工具噪音过滤 + 文档哈希幂等。

旧图 `cache/entity_graph.db` 完全不动；`YHLZ_KG_V2=0` 一键回滚到旧 context。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = _ROOT / "cache" / "kg" / "kg_v2.db"

_LLM = None
_last_ingest = 0.0
_INGEST_MIN_GAP = 8.0

EXTRACT_PROMPT = (
    "你是长期记忆图谱抽取器。从文本中抽取**长期有效、可复用**的事实三元组。\n"
    "规则：\n"
    "1) 实体只抽人物/项目/地点/事物/概念；不要抽“你/我/他/她/它/大家/这个/那个/"
    "事情/问题/计划/任务/工具/步骤/时间/失败/成功”等泛指或过程词。\n"
    "2) 关系用简短动词（是/负责/喜欢/住在/属于/依赖/创建/使用/讨厌…），"
    "优先覆盖：身份（A 是 B）、归属（A 属于 B）、喜好/厌恶、职责（A 负责 B）、"
    "长期项目状态；不要输出同义反复（如“稳态 是 内在的稳定性”）。\n"
    "3) 每条必须附 evidence：原文中连续的一段话（≤60字），**不得改写**。\n"
    "4) 只抽明确陈述的事实；推测、过程、工具调用、临时计划、本轮动作不要。\n"
    "5) confidence 0-1，表示这条事实的可靠程度。\n"
    "6) 只抽**跨轮仍然成立**的事实；不要抽本轮动作/排查过程"
    "（挖出/修正/完成/发现/误判/改/加/跑/测/查/处理/提交/部署）。\n"
    "输出 JSON 数组（必须以 [ 开头、] 结尾，不要逐行输出对象），元素："
    '{"subject":"","subject_type":"人物|项目|地点|事物|概念",'
    '"relation":"","object":"","object_type":"","evidence":"","confidence":0.8}\n'
    "没有就输出 []。不要输出别的。\n文本：<TEXT>"
)

_ALIASES = {
    "用户": "老爹", "用户本人": "老爹", "主人": "老爹", "父亲": "老爹",
    "创造者": "老爹", "老爹/创造者": "老爹", "我": "元亨", "我自己": "元亨",
    "你": "元亨", "元亨自己": "元亨",
}
# 代词 / 泛指 / 过程噪音：命中即拒绝
_BAD_ENTITY = re.compile(
    r"^(你|我|他|她|它|我们|你们|他们|她们|大家|有人|自己|对方|这个|那个|这里|那里|"
    r"事情|问题|东西|计划|任务|工具|步骤|方法|时候|时间|结果|内容|部分|地方|状态|"
    r"失败|成功|操作|功能|记录|文档|系统|计划表|跑工具|本轮|当前|上面|下面)$")
_BAD_NAME = re.compile(r"^[\d\W_]+$|^\d{1,2}[:：]\d{2}|daily|周[一二三四五六日]|"
                       r"^(今天|明天|昨天|刚才|现在|true|false|none|null|是|否)$|"
                       r"\.(py|exe|db|json|md|wav|onnx|ckpt|log|bat|ps1)$|"
                       r"^[A-Z][A-Z0-9_]{4,}$", re.I)
_STOP_REL = {"", "有", "做", "进行", "发生", "出现", "挖出", "发现", "修正",
             "修复", "完成", "误判", "改", "加", "跑", "测", "查", "处理",
             "提交", "部署", "删除", "移动", "合并", "写", "说", "问", "回复",
             "提到", "尝试"}


def norm_name(name: str) -> str:
    s = str(name or "").strip().strip("，。！？、；：\"'“”‘’()（）[]【】 ")
    s = re.sub(r"\s+", "", s)
    return _ALIASES.get(s, s)


def _bad_entity(name: str) -> bool:
    return (not name or len(name) < 2 or len(name) > 24
            or bool(_BAD_ENTITY.match(name)) or bool(_BAD_NAME.search(name)))


@contextmanager
def _conn():
    path = Path(os.getenv("YHLZ_KG_DB", "")) if os.getenv("YHLZ_KG_DB") else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=20)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS docs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          hash TEXT UNIQUE, text TEXT NOT NULL, source TEXT DEFAULT '',
          ts REAL NOT NULL, meta TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS entities(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT UNIQUE NOT NULL, type TEXT DEFAULT '',
          hits INTEGER DEFAULT 1, confidence REAL DEFAULT 0.5,
          first_seen REAL, last_seen REAL);
        CREATE TABLE IF NOT EXISTS relations(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          src INTEGER NOT NULL, rel TEXT NOT NULL, dst INTEGER NOT NULL,
          evidence TEXT DEFAULT '', doc_id INTEGER,
          confidence REAL DEFAULT 0.5, hits INTEGER DEFAULT 1,
          first_seen REAL, last_seen REAL,
          UNIQUE(src, rel, dst));
        CREATE TABLE IF NOT EXISTS mentions(
          doc_id INTEGER NOT NULL, entity_id INTEGER NOT NULL,
          PRIMARY KEY(doc_id, entity_id));
        CREATE INDEX IF NOT EXISTS idx_rel_src ON relations(src);
        CREATE INDEX IF NOT EXISTS idx_rel_dst ON relations(dst);
    """)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _local_llm():
    global _LLM
    if _LLM is None:
        from backend.target_orchestrator import build_openai_compatible_llm_turn

        # 2026-11-18：记忆抽取走**本机 llama**（8081），不再用 llm_endpoint 的云端配置
        # （云端 DNS 不通时旧 entity_graph 一直静默抽空）。
        base = os.getenv("YHLZ_KG_LLM_BASE",
                         "http://127.0.0.1:8081/v1/chat/completions")
        _LLM = build_openai_compatible_llm_turn(
            base_url=base, api_key="",
            model=os.getenv("YHLZ_KG_LLM_MODEL", "gemma-4-e4b"),
            temperature=0.1, max_tokens=650, reasoning_effort="none")
    return _LLM


def _llm_off() -> bool:
    return str(os.getenv("YHLZ_KG_LLM", "1")).strip().lower() in (
        "0", "false", "off", "no")


def _norm_text(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(s or "")).lower()


def _valid(t: dict, text: str) -> dict | None:
    s = norm_name(t.get("subject"))
    o = norm_name(t.get("object"))
    r = str(t.get("relation") or "").strip()
    ev = str(t.get("evidence") or "").strip()
    try:
        conf = float(t.get("confidence") or 0.6)
    except Exception:  # noqa: BLE001
        conf = 0.6
    conf = max(0.0, min(1.0, conf))
    if _bad_entity(s) or _bad_entity(o) or s == o:
        return None
    if not r or len(r) > 20 or r in _STOP_REL:
        return None
    # 证据必须是原文子串（归一化后），否则视为模型编造
    if len(ev) < 4 or _norm_text(ev) not in _norm_text(text):
        return None
    if conf < 0.35:
        return None
    return {"subject": s, "subject_type": str(t.get("subject_type") or "")[:8],
            "relation": r, "object": o, "object_type": str(t.get("object_type") or "")[:8],
            "evidence": ev[:120], "confidence": round(conf, 3)}


def _parse_items(raw: str) -> list:
    """兼容三种输出：JSON 数组 / 每行一个 JSON 对象 / {"triples":[...]}。"""
    raw = str(raw or "").strip().strip("`").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("triples", "items", "data", "relations"):
                if isinstance(data.get(key), list):
                    return data[key]
    except Exception:  # noqa: BLE001
        pass
    a, b = raw.find("["), raw.rfind("]")
    if 0 <= a < b:
        try:
            data = json.loads(raw[a:b + 1])
            if isinstance(data, list):
                return data
        except Exception:  # noqa: BLE001
            pass
    dec = json.JSONDecoder()
    out, idx = [], 0
    while idx < len(raw):
        pos = raw.find("{", idx)
        if pos < 0:
            break
        try:
            obj, end = dec.raw_decode(raw[pos:])
        except Exception:  # noqa: BLE001
            idx = pos + 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
        idx = pos + end
    return out


async def extract_triples(text: str, llm_turn=None) -> list[dict]:
    """LLM 抽取 + 证据/噪音校验。自定义 llm_turn 时跳过推理闸门（测试用）。"""
    text = str(text or "")[:1500]
    if len(text) < 8:
        return []
    if llm_turn is None:
        if _llm_off():
            return []
        llm = _local_llm()
        try:
            from backend.text_memory_inference_gate import inference_gate
            async with inference_gate().slot(background=True):
                msg = await llm([{"role": "user",
                                  "content": EXTRACT_PROMPT.replace("<TEXT>", text)}], [])
        except Exception:  # noqa: BLE001
            return []
    else:
        try:
            msg = await llm_turn([{"role": "user",
                                   "content": EXTRACT_PROMPT.replace("<TEXT>", text)}], [])
        except Exception:  # noqa: BLE001
            return []
    raw = str((msg or {}).get("content") or "").strip().strip("`")
    data = _parse_items(raw)
    out, seen = [], set()
    for t in data if isinstance(data, list) else []:
        if not isinstance(t, dict):
            continue
        v = _valid(t, text)
        if not v:
            continue
        key = (v["subject"], v["relation"], v["object"])
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
        if len(out) >= 12:
            break
    return out


def _entity(con: sqlite3.Connection, name: str, typ: str, now: float) -> int:
    row = con.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
    if row:
        con.execute(
            "UPDATE entities SET hits=hits+1, last_seen=?, "
            "type=CASE WHEN type='' THEN ? ELSE type END, "
            "confidence=MIN(1.0, confidence+0.02) WHERE id=?",
            (now, typ, row[0]))
        return int(row[0])
    cur = con.execute(
        "INSERT INTO entities(name,type,hits,confidence,first_seen,last_seen) "
        "VALUES(?,?,1,0.6,?,?)", (name, typ, now, now))
    return int(cur.lastrowid)


def upsert(triples: list[dict], text: str, source: str = "", ts: float | None = None) -> int:
    """段落 + 三元组落库；同一段落幂等，同一关系累计 hits。"""
    text = str(text or "").strip()
    if not triples or not text:
        return 0
    now = float(ts or time.time())
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    n = 0
    with _conn() as con:
        row = con.execute("SELECT id FROM docs WHERE hash=?", (h,)).fetchone()
        if row:
            doc_id = int(row[0])
            con.execute("UPDATE docs SET ts=? WHERE id=?", (now, doc_id))
        else:
            doc_id = int(con.execute(
                "INSERT INTO docs(hash,text,source,ts) VALUES(?,?,?,?)",
                (h, text[:4000], source, now)).lastrowid)
        for t in triples:
            sid = _entity(con, t["subject"], t.get("subject_type", ""), now)
            did = _entity(con, t["object"], t.get("object_type", ""), now)
            for eid in (sid, did):
                con.execute("INSERT OR IGNORE INTO mentions(doc_id,entity_id) VALUES(?,?)",
                            (doc_id, eid))
            old = con.execute(
                "SELECT id,confidence,hits FROM relations WHERE src=? AND rel=? AND dst=?",
                (sid, t["relation"], did)).fetchone()
            if old:
                con.execute(
                    "UPDATE relations SET hits=hits+1, last_seen=?, "
                    "confidence=MAX(confidence,?), doc_id=?, "
                    "evidence=CASE WHEN length(?)>length(evidence) THEN ? ELSE evidence END "
                    "WHERE id=?",
                    (now, t["confidence"], doc_id, t["evidence"], t["evidence"], old[0]))
            else:
                con.execute(
                    "INSERT INTO relations(src,rel,dst,evidence,doc_id,confidence,hits,"
                    "first_seen,last_seen) VALUES(?,?,?,?,?,?,1,?,?)",
                    (sid, t["relation"], did, t["evidence"], doc_id,
                     t["confidence"], now, now))
            n += 1
    return n


async def ingest(text: str, source: str = "", llm_turn=None, ts: float | None = None,
                 force: bool = False) -> int:
    """抽取 + 落库；同进程内节流，避免每轮都打模型。回填时传 force=True。"""
    global _last_ingest
    text = str(text or "").strip()
    if len(text) < 8:
        return 0
    now = time.time()
    if llm_turn is None and not force and now - _last_ingest < _INGEST_MIN_GAP:
        return 0
    _last_ingest = now
    triples = await extract_triples(text, llm_turn=llm_turn)
    return upsert(triples, text, source=source, ts=ts)


def _entities_in(con: sqlite3.Connection, text: str, limit: int = 3) -> list[tuple[int, str]]:
    t = _norm_text(text)
    if not t:
        return []
    rows = con.execute("SELECT id,name FROM entities").fetchall()
    hits = [(int(i), n) for i, n in rows if len(n) >= 2 and _norm_text(n) in t]
    hits.sort(key=lambda x: -len(x[1]))
    return hits[:limit]


def facts_for(con: sqlite3.Connection, eid: int, limit: int = 8) -> list[dict]:
    now = time.time()
    rows = con.execute(
        "SELECT s.name,r.rel,d.name,r.evidence,r.confidence,r.hits,r.last_seen "
        "FROM relations r JOIN entities s ON s.id=r.src JOIN entities d ON d.id=r.dst "
        "WHERE r.src=? OR r.dst=? ORDER BY r.confidence DESC, r.hits DESC, r.last_seen DESC "
        "LIMIT ?", (eid, eid, int(limit))).fetchall()
    out = []
    for s, rel, d, ev, conf, hits, last in rows:
        age_days = max(0.0, (now - float(last or now)) / 86400)
        fresh = max(0.4, 1.0 - age_days / 180.0)
        out.append({"src": s, "rel": rel, "dst": d, "evidence": ev,
                    "confidence": round(float(conf), 3), "hits": int(hits),
                    "score": round(float(conf) * (1 + min(int(hits), 5) * 0.08) * fresh, 4)})
    out.sort(key=lambda x: -x["score"])
    return out


def context_for(text: str, limit: int = 3) -> str:
    """给一轮对话的「已知事实」提示块；无命中返回空串。"""
    with _conn() as con:
        seeds = _entities_in(con, text, limit=3)
        if not seeds:
            return ""
        facts, seen = [], set()
        for eid, name in seeds:
            for f in facts_for(con, eid, limit=6):
                key = (f["src"], f["rel"], f["dst"])
                if key in seen:
                    continue
                seen.add(key)
                facts.append(f)
        facts.sort(key=lambda x: -x["score"])
        if not facts:
            return ""
        lines = []
        for f in facts[: max(1, int(limit)) * 2]:
            lines.append(f"- {f['src']} {f['rel']} {f['dst']}")
        return ("（你记得的长期事实，仅供理解，**不要提及或罗列**）：\n"
                + "\n".join(lines))


def stats() -> dict:
    with _conn() as con:
        out = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
               for t in ("docs", "entities", "relations", "mentions")}
        out["top_entities"] = con.execute(
            "SELECT name,hits FROM entities ORDER BY hits DESC LIMIT 8").fetchall()
        out["recent_relations"] = con.execute(
            "SELECT s.name,r.rel,d.name,r.evidence,r.confidence FROM relations r "
            "JOIN entities s ON s.id=r.src JOIN entities d ON d.id=r.dst "
            "ORDER BY r.last_seen DESC LIMIT 5").fetchall()
    return out


def prune(min_confidence: float = 0.4, max_age_days: float = 365.0) -> int:
    """删低置信 + 过旧且没再出现的孤立关系（段落保留）。"""
    cutoff = time.time() - max_age_days * 86400
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM relations WHERE confidence < ? AND hits <= 1 AND last_seen < ?",
            (float(min_confidence), cutoff))
        return cur.rowcount


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) > 1 and sys.argv[1] == "context":
        print(context_for(" ".join(sys.argv[2:])) or "（无命中）")
    else:
        s = stats()
        print(json.dumps(s, ensure_ascii=False, indent=1, default=str))
