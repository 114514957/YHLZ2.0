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
_LLM_BATCH = None
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
# 单值关系：同一主语的新值会让旧值失效（不是删除，标记 superseded）
_FUNCTIONAL = {"喜欢", "讨厌", "住在", "位于", "属于", "负责", "是", "生日",
               "年龄", "职业", "拥有"}


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
          ts REAL NOT NULL, meta TEXT DEFAULT '', emb BLOB);
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
          status TEXT DEFAULT 'active', valid_from REAL, valid_to REAL,
          superseded_by INTEGER, protected INTEGER DEFAULT 0,
          UNIQUE(src, rel, dst));
        CREATE TABLE IF NOT EXISTS mentions(
          doc_id INTEGER NOT NULL, entity_id INTEGER NOT NULL,
          PRIMARY KEY(doc_id, entity_id));
        CREATE TABLE IF NOT EXISTS episodes(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, start_ts REAL, end_ts REAL,
          summary TEXT DEFAULT '', doc_ids TEXT DEFAULT '', created REAL,
          UNIQUE(source, start_ts, end_ts));
        CREATE TABLE IF NOT EXISTS profiles(
          name TEXT PRIMARY KEY, facts TEXT DEFAULT '', updated REAL);
        CREATE TABLE IF NOT EXISTS processed(
          source TEXT PRIMARY KEY, ts REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_rel_src ON relations(src);
        CREATE INDEX IF NOT EXISTS idx_rel_dst ON relations(dst);
    """)
    # 旧库迁移：docs 没有 emb 列时补上（只加列，不动数据）
    try:
        con.execute("ALTER TABLE docs ADD COLUMN emb BLOB")
    except sqlite3.OperationalError:
        pass
    added_status = False
    for col, decl in (("status", "TEXT DEFAULT 'active'"),
                      ("valid_from", "REAL"), ("valid_to", "REAL"),
                      ("superseded_by", "INTEGER"),
                      ("protected", "INTEGER DEFAULT 0")):
        try:
            con.execute(f"ALTER TABLE relations ADD COLUMN {col} {decl}")
            if col == "status":
                added_status = True
        except sqlite3.OperationalError:
            pass
    # 只在刚加列时回填一次；平时连接不写库（避免拿写锁，验收 Q7 的根因）
    if added_status:
        con.execute("UPDATE relations SET status='active' WHERE status IS NULL")
        con.execute("UPDATE relations SET valid_from=first_seen "
                    "WHERE valid_from IS NULL")
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
            temperature=0.1, max_tokens=180, reasoning_effort="none")
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
                    "confidence=MAX(confidence,?), doc_id=?, status='active', "
                    "valid_to=NULL, "
                    "evidence=CASE WHEN length(?)>length(evidence) THEN ? ELSE evidence END "
                    "WHERE id=?",
                    (now, t["confidence"], doc_id, t["evidence"], t["evidence"], old[0]))
            else:
                if t["relation"] in _FUNCTIONAL:
                    con.execute(
                        "UPDATE relations SET status='superseded', valid_to=? "
                        "WHERE src=? AND rel=? AND dst<>? AND status='active'",
                        (now, sid, t["relation"], did))
                con.execute(
                    "INSERT INTO relations(src,rel,dst,evidence,doc_id,confidence,hits,"
                    "first_seen,last_seen,status,valid_from) "
                    "VALUES(?,?,?,?,?,?,1,?,?,'active',?)",
                    (sid, t["relation"], did, t["evidence"], doc_id,
                     t["confidence"], now, now, now))
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


def facts_for(con: sqlite3.Connection, eid: int, limit: int = 8,
              include_history: bool = False) -> list[dict]:
    now = time.time()
    where = "r.src=? OR r.dst=?"
    if not include_history:
        where = f"({where}) AND COALESCE(r.status,'active')='active'"
    rows = con.execute(
        "SELECT s.name,r.rel,d.name,r.evidence,r.confidence,r.hits,r.last_seen "
        "FROM relations r JOIN entities s ON s.id=r.src JOIN entities d ON d.id=r.dst "
        "WHERE " + where + " ORDER BY r.confidence DESC, r.hits DESC, r.last_seen DESC "
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


def embed_docs(limit: int = 200) -> int:
    """给还没有向量的段落补 embedding（共享 memory 的 BGE，CLS 池化）。"""
    limit = max(1, min(int(limit), 2000))
    with _conn() as con:
        rows = con.execute("SELECT id,text FROM docs WHERE emb IS NULL LIMIT ?",
                           (limit,)).fetchall()
    if not rows:
        return 0
    try:
        from backend.vector_memory import embed_cls

        vecs = embed_cls([r[1][:1200] for r in rows])
    except Exception:  # noqa: BLE001
        return 0
    with _conn() as con:
        for (did, _text), vec in zip(rows, vecs):
            con.execute("UPDATE docs SET emb=? WHERE id=?", (vec.tobytes(), did))
    return len(rows)


def semantic_docs(query: str, top: int = 6) -> list[dict]:
    """段落向量召回（DPR 的本地版）；没有向量时尽力补一批。"""
    if not str(query or "").strip():
        return []
    try:
        from backend.vector_memory import semantic_ready
    except Exception:  # noqa: BLE001
        return []
    if not semantic_ready():
        return []
    embed_docs(limit=200)
    with _conn() as con:
        rows = con.execute("SELECT id,text,emb FROM docs WHERE emb IS NOT NULL").fetchall()
    if not rows:
        return []
    import numpy as np
    from backend.vector_memory import embed_cls

    try:
        q = embed_cls([query])[0]
    except Exception:  # noqa: BLE001
        return []
    scored = []
    for did, text, blob in rows:
        vec = np.frombuffer(blob, dtype=np.float32)
        scored.append((float(np.dot(q, vec)), int(did), str(text)))
    scored.sort(key=lambda x: -x[0])
    return [{"doc_id": did, "score": round(score, 4), "text": text[:320]}
            for score, did, text in scored[:max(1, int(top))]]


def retrieve(query: str, top: int = 5) -> dict:
    """双路召回：实体关系事实 + 段落向量，返回证据（供工具/调试）。"""
    with _conn() as con:
        seeds = _entities_in(con, query, limit=3)
        facts, seen = [], set()
        for eid, _name in seeds:
            for f in facts_for(con, eid, limit=8):
                key = (f["src"], f["rel"], f["dst"])
                if key in seen:
                    continue
                seen.add(key)
                facts.append(f)
    facts.sort(key=lambda x: -x["score"])
    docs = semantic_docs(query, top=max(top, 6))
    return {"query": str(query or ""), "seeds": [n for _, n in seeds],
            "facts": facts[:max(top, 5)], "docs": docs, "mode": "hybrid"}


def rebuild_episodes(gap_hours: float = 6.0) -> int:
    """按 source 把段落聚成 Episode（时间间隔 > gap_hours 切段），摘要取前几段摘录。"""
    gap = max(0.5, float(gap_hours)) * 3600
    with _conn() as con:
        rows = con.execute(
            "SELECT id, source, ts, text FROM docs ORDER BY source, ts").fetchall()
        con.execute("DELETE FROM episodes")
        episodes, cur = [], []
        for did, source, ts, text in rows:
            if cur and (ts - cur[-1][2] > gap or source != cur[-1][1]):
                episodes.append(cur)
                cur = []
            cur.append((did, source, ts, text))
        if cur:
            episodes.append(cur)
        now = time.time()
        for group in episodes:
            source = group[0][1] or ""
            start, end = group[0][2], group[-1][2]
            summary = "；".join(str(g[3])[:100] for g in group[:3])
            if len(group) > 3:
                summary += f"（共{len(group)}段）"
            con.execute(
                "INSERT OR REPLACE INTO episodes(source,start_ts,end_ts,summary,"
                "doc_ids,created) VALUES(?,?,?,?,?,?)",
                (source, start, end, summary[:600],
                 ",".join(str(g[0]) for g in group), now))
        return len(episodes)


def episodes(limit: int = 10, source: str = "") -> list[dict]:
    with _conn() as con:
        if source:
            rows = con.execute(
                "SELECT id,source,start_ts,end_ts,summary,doc_ids FROM episodes "
                "WHERE source=? ORDER BY start_ts DESC LIMIT ?",
                (source, int(limit))).fetchall()
        else:
            rows = con.execute(
                "SELECT id,source,start_ts,end_ts,summary,doc_ids FROM episodes "
                "ORDER BY start_ts DESC LIMIT ?", (int(limit),)).fetchall()
    return [{"id": r[0], "source": r[1], "start_ts": r[2], "end_ts": r[3],
             "summary": r[4], "doc_ids": r[5]} for r in rows]


def rebuild_profiles(top: int = 50) -> int:
    """给最活跃的实体生成人物/实体画像快照（JSON：关系 + 证据）。"""
    now = time.time()
    n = 0
    with _conn() as con:
        ents = con.execute("SELECT id,name FROM entities ORDER BY hits DESC LIMIT ?",
                           (int(top),)).fetchall()
        for eid, name in ents:
            facts = facts_for(con, int(eid), limit=12)
            con.execute("INSERT OR REPLACE INTO profiles(name,facts,updated) VALUES(?,?,?)",
                        (name, json.dumps(facts, ensure_ascii=False), now))
            n += 1
    return n


def profile(name: str) -> dict:
    name = norm_name(name)
    with _conn() as con:
        row = con.execute("SELECT facts,updated FROM profiles WHERE name=?",
                          (name,)).fetchone()
        if not row:
            eid = con.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
            if not eid:
                return {"name": name, "facts": [], "updated": 0}
            facts = facts_for(con, int(eid[0]), limit=12)
            con.execute("INSERT OR REPLACE INTO profiles(name,facts,updated) VALUES(?,?,?)",
                        (name, json.dumps(facts, ensure_ascii=False), time.time()))
            return {"name": name, "facts": facts, "updated": time.time()}
    try:
        facts = json.loads(row[0] or "[]")
    except Exception:  # noqa: BLE001
        facts = []
    return {"name": name, "facts": facts, "updated": row[1]}


def decay(max_age_days: float = 180.0, min_hits: int = 1,
          max_conf: float = 0.6) -> int:
    """遗忘：久未命中、低置信、没被保护的关系标 archived（不删除，可 restore）。"""
    cutoff = time.time() - max(1.0, float(max_age_days)) * 86400
    with _conn() as con:
        cur = con.execute(
            "UPDATE relations SET status='archived' WHERE status='active' "
            "AND protected=0 AND hits<=? AND confidence<? AND last_seen<?",
            (int(min_hits), float(max_conf), cutoff))
        return cur.rowcount


def restore(rel_id: int) -> bool:
    with _conn() as con:
        cur = con.execute(
            "UPDATE relations SET status='active', valid_to=NULL WHERE id=?",
            (int(rel_id),))
        return cur.rowcount > 0


def forget(rel_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("UPDATE relations SET status='archived' WHERE id=?",
                          (int(rel_id),))
        return cur.rowcount > 0


def protect(rel_id: int, on: bool = True) -> bool:
    with _conn() as con:
        cur = con.execute("UPDATE relations SET protected=? WHERE id=?",
                          (1 if on else 0, int(rel_id)))
        return cur.rowcount > 0


def maintenance() -> dict:
    with _conn() as con:
        rows = con.execute(
            "SELECT COALESCE(status,'active'), COUNT(*) FROM relations GROUP BY 1"
        ).fetchall()
        stale = con.execute(
            "SELECT COUNT(*) FROM relations WHERE status='active' AND hits<=1 "
            "AND last_seen < ?", (time.time() - 180 * 86400,)).fetchone()[0]
        protected = con.execute(
            "SELECT COUNT(*) FROM relations WHERE protected=1").fetchone()[0]
    return {"by_status": {r[0]: int(r[1]) for r in rows},
            "stale_active": int(stale), "protected": int(protected)}


def purge_archived(max_age_days: float = 365.0) -> int:
    """真正删除归档超过 max_age_days 的关系（默认一年，谨慎）。"""
    cutoff = time.time() - max(1.0, float(max_age_days)) * 86400
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM relations WHERE status='archived' AND last_seen<?", (cutoff,))
        return cur.rowcount


_KG_COLORS = {"人物": "#e74c3c", "项目": "#2ecc71", "地点": "#3498db",
              "事物": "#f39c12", "概念": "#9b59b6", "关系": "#95a5a6"}


def graph_data(limit: int = 300) -> dict:
    """给工作台星图的 v2 视图：实体节点 + 关系边（带关系名/置信度）。"""
    limit = max(20, min(int(limit), 1000))
    with _conn() as con:
        ents = con.execute(
            "SELECT id,name,type,hits FROM entities ORDER BY hits DESC LIMIT ?",
            (limit,)).fetchall()
        ids = {int(e[0]) for e in ents}
        rels = con.execute(
            "SELECT src,rel,dst,confidence,hits FROM relations "
            "WHERE COALESCE(status,'active')='active' "
            "ORDER BY confidence*hits DESC LIMIT ?", (limit * 2,)).fetchall()
        nodes = []
        for eid, name, typ, hits in ents:
            facts = facts_for(con, int(eid), limit=3)
            text = name
            if facts:
                text += "：" + "；".join(f"{f['rel']} {f['dst']}" for f in facts)
            nodes.append({
                "id": f"kg:{eid}", "label": name, "text": text,
                "type": typ or "实体", "role": "kg",
                "imp": min(int(hits or 1), 9),
                "color": _KG_COLORS.get(typ or "", "#7f8c8d"),
                "shape": "circle", "kw": [],
            })
    links = []
    for src, rel, dst, conf, hits in rels:
        if int(src) not in ids or int(dst) not in ids:
            continue
        links.append({"source": f"kg:{src}", "target": f"kg:{dst}",
                      "w": round(float(conf or 0.5) * (1 + min(int(hits or 1), 5) * 0.1), 2),
                      "rel": rel})
    types = {}
    for n in nodes:
        types[n["type"]] = types.get(n["type"], 0) + 1
    return {"nodes": nodes, "links": links,
            "stats": {"nodes": len(nodes), "links": len(links), "types": types,
                      "source": "kg_v2"}}


BATCH_PROMPT = (
    "下面有 {n} 段文本，用 ### 文本0 / ### 文本1 … 分隔。\n"
    "对每段抽取**长期有效、可复用**的事实三元组。输出一个 JSON 数组，每条严格是：\n"
    '{{"doc":0,"subject":"","subject_type":"","relation":"","object":"",'
    '"object_type":"","evidence":"","confidence":0.9}}\n'
    "规则：\n"
    "- doc = 这段文本的序号；subject/object 只抽人物/项目/地点/事物/概念，不要代词/泛指/文件名；\n"
    "- relation 用简短动词（是/负责/喜欢/住在/属于/依赖/创建…）；\n"
    "- evidence 必须是**对应那段文本里连续的原句**（≤60字），不得改写；\n"
    "- 只抽明确陈述的事实；推测、过程、工具调用、临时计划不要；\n"
    "- 没有就输出 []；不要输出别的。\n\n{docs}"
)


def _auto_evidence(text: str, subject: str, obj: str) -> str:
    """批量抽取模型常省 evidence：从原文找含主/宾的句子当证据（绝不生成新句子）。"""
    for sent in re.split(r"[。！？；\n]", str(text or "")):
        sent = sent.strip()
        if len(sent) < 4:
            continue
        if subject and obj and subject in sent and obj in sent:
            return sent[:80]
    for sent in re.split(r"[。！？；\n]", str(text or "")):
        sent = sent.strip()
        if subject and subject in sent and len(sent) >= 4:
            return sent[:80]
    return ""


async def extract_batch(texts: list[str], llm_turn=None) -> list[list[dict]]:
    """批量抽取：一次 prompt 处理多段，按 doc 序号切回；失败返回空列表。"""
    global _LLM_BATCH
    texts = [str(t or "")[:500] for t in texts]
    if not texts:
        return []
    docs = "\n\n".join(f"### 文本{i}\n{t}" for i, t in enumerate(texts))
    prompt = BATCH_PROMPT.replace("{n}", str(len(texts))).replace("{docs}", docs)
    if llm_turn is None:
        if _llm_off():
            return [[] for _ in texts]
        if _LLM_BATCH is None:
            from backend.target_orchestrator import build_openai_compatible_llm_turn

            base = os.getenv("YHLZ_KG_LLM_BASE",
                             "http://127.0.0.1:8081/v1/chat/completions")
            _LLM_BATCH = build_openai_compatible_llm_turn(
                base_url=base, api_key="",
                model=os.getenv("YHLZ_KG_LLM_MODEL", "gemma-4-e4b"),
                temperature=0.1, max_tokens=1600, reasoning_effort="none")
        try:
            from backend.text_memory_inference_gate import inference_gate
            async with inference_gate().slot(background=True):
                msg = await _LLM_BATCH([{"role": "user", "content": prompt}], [])
        except Exception:  # noqa: BLE001
            return [[] for _ in texts]
    else:
        try:
            msg = await llm_turn([{"role": "user", "content": prompt}], [])
        except Exception:  # noqa: BLE001
            return [[] for _ in texts]
    items = _parse_items(str((msg or {}).get("content") or ""))
    out: list[list[dict]] = [[] for _ in texts]
    for t in items:
        if not isinstance(t, dict):
            continue
        try:
            idx = int(t.get("doc") or 0)
        except Exception:  # noqa: BLE001
            continue
        if not (0 <= idx < len(texts)):
            continue
        if not str(t.get("evidence") or "").strip():
            ev = _auto_evidence(texts[idx], norm_name(t.get("subject")),
                                norm_name(t.get("object")))
            if ev:
                t = {**t, "evidence": ev}
        v = _valid(t, texts[idx])
        if v:
            out[idx].append(v)
    return out


def mark_processed(source: str) -> None:
    """记录“这段已抽过”（即使 0 三元组也算），回填不再重跑。"""
    with _conn() as con:
        con.execute("INSERT OR REPLACE INTO processed(source,ts) VALUES(?,?)",
                    (str(source), time.time()))


def context_for(text: str, limit: int = 3) -> str:
    """给一轮对话的「已知事实」提示块；无命中返回空串。"""
    facts: list[dict] = []
    with _conn() as con:
        seeds = _entities_in(con, text, limit=3)
        if not seeds:
            return ""
        seen = set()
        for eid, _name in seeds:
            for f in facts_for(con, eid, limit=6):
                key = (f["src"], f["rel"], f["dst"])
                if key in seen:
                    continue
                seen.add(key)
                facts.append(f)
    facts.sort(key=lambda x: -x["score"])
    if facts:
        lines = [f"- {f['src']} {f['rel']} {f['dst']}"
                 for f in facts[: max(1, int(limit)) * 2]]
        return ("（你记得的长期事实，仅供理解，**不要提及或罗列**）：\n"
                + "\n".join(lines))
    # 没有实体命中时，才用段落向量补一条（且模型必须已在内存里热着，
    # 不能在聊天回合里触发 10s+ 的冷加载）。注意：必须在连接关闭后调用，
    # 否则内层 embed_docs 会撞上外层写锁（2026-11-18 验收 Q7 暴露）。
    try:
        from backend.vector_memory import semantic_ready

        if not semantic_ready():
            return ""
    except Exception:  # noqa: BLE001
        return ""
    docs = semantic_docs(text, top=2)
    lines = [f"- {d['text'][:90]}" for d in docs if d["score"] >= 0.45]
    if not lines:
        return ""
    return ("（由记忆片段联想到的旧事，仅供理解，**不要提及或罗列**）：\n"
            + "\n".join(lines[: limit]))


def stats() -> dict:
    with _conn() as con:
        out = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
               for t in ("docs", "entities", "relations", "mentions",
                         "episodes", "profiles")}
        out["docs_with_emb"] = con.execute(
            "SELECT COUNT(*) FROM docs WHERE emb IS NOT NULL").fetchone()[0]
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
    elif len(sys.argv) > 1 and sys.argv[1] == "retrieve":
        print(json.dumps(retrieve(" ".join(sys.argv[2:])), ensure_ascii=False,
                         indent=1, default=str))
    elif len(sys.argv) > 1 and sys.argv[1] == "episodes":
        print("built", rebuild_episodes())
        print(json.dumps(episodes(10), ensure_ascii=False, indent=1))
    elif len(sys.argv) > 1 and sys.argv[1] == "profile":
        print(json.dumps(profile(" ".join(sys.argv[2:])), ensure_ascii=False, indent=1))
    elif len(sys.argv) > 1 and sys.argv[1] == "maintenance":
        print(json.dumps(maintenance(), ensure_ascii=False, indent=1))
    elif len(sys.argv) > 1 and sys.argv[1] == "decay":
        print("archived", decay())
    else:
        s = stats()
        print(json.dumps(s, ensure_ascii=False, indent=1, default=str))
