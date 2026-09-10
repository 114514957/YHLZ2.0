"""Vector memory layer (ledger 0226): semantic recall complement for L2.

SQLite stays the source of truth (approval/downgrade/evidence untouched); this
adds an id->embedding side-table for semantic (换说法) recall. Scope makes it
extendable to l1_summary / l3 / diary later.

Model: BAAI/bge-small-zh-v1.5 (CPU, local). Store: cache/embvec.db
"""
from __future__ import annotations

import pathlib
import re
import sqlite3
import threading

import numpy as np

_PROJECT = pathlib.Path(__file__).resolve().parent.parent
MODEL_DIR = _PROJECT / "models" / "emb" / "bge-small-zh"
VEC_DB = _PROJECT / "cache" / "embvec.db"
MEMORY_DB = _PROJECT / "cache" / "memstore" / "memstore.db"
_lock = threading.RLock()
_model = None
_tokenizer = None
DIM = 512


def _load_model():
    global _model, _tokenizer
    if _model is None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        _tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))
        _model = AutoModel.from_pretrained(str(MODEL_DIR))
        _model.eval()
    return _model, _tokenizer


def embed(texts: list[str]) -> np.ndarray:
    """Mean-pooled, L2-normalised embeddings (list[n] -> (n,DIM))."""
    import torch

    if not texts:
        return np.zeros((0, DIM), dtype="float32")
    model, tok = _load_model()
    with torch.no_grad():
        enc = tok(texts, padding=True, truncation=True,
                  max_length=256, return_tensors="pt")
        out = model(**enc).last_hidden_state
        # mean pooling ignoring padding
        mask = enc["attention_mask"].unsqueeze(-1).float()
        pooled = (out * mask).sum(1) / mask.sum(1).clamp_min(1e-9)
    pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
    return pooled.cpu().numpy().astype("float32")


def _conn() -> sqlite3.Connection:
    VEC_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(VEC_DB))
    con.execute("CREATE TABLE IF NOT EXISTS vec("
                "id TEXT PRIMARY KEY, scope TEXT NOT NULL, "
                "vec BLOB NOT NULL)")
    cols = {r[1] for r in con.execute("PRAGMA table_info(vec)")}
    if "text" not in cols:
        try:
            con.execute("ALTER TABLE vec ADD COLUMN text TEXT")
        except Exception:
            pass
    con.commit()
    return con


def vec_add(scope: str, item_id: str, text: str) -> bool:
    text = str(text or "").strip()
    if not text or not item_id:
        return False
    try:
        v = embed([text])[0]
        with _lock:
            con = _conn()
            try:
                con.execute(
                    "INSERT OR REPLACE INTO vec(id,scope,vec,text)"
                    " VALUES(?,?,?,?)",
                    (str(item_id), str(scope), v.tobytes(), text[:500]))
                con.commit()
            finally:
                con.close()
        return True
    except Exception:
        return False


def semantic_any(query: str, scopes: list[str] | None = None,
                 top: int = 6, min_score: float = 0.42) -> list[dict]:
    """Generic semantic search across scopes (text returned from the vec table,
    no memory-db join needed) — used for diary / future l1/l3 scopes."""
    raw = str(query or "").strip()
    if not raw:
        return []
    variants = [raw, _topic(raw)]
    qvs = []
    for v in variants:
        try:
            qvs.append(embed([v])[0])
        except Exception:
            pass
    if not qvs:
        return []
    best: dict[str, float] = {}
    rows_by_id: dict[str, dict] = {}
    with _lock:
        con = _conn()
        try:
            for scope in (scopes or ["diary"]):
                for iid, blob, txt in con.execute(
                        "SELECT id, vec, text FROM vec WHERE scope=?",
                        (str(scope),)):
                    rows_by_id[iid] = {"id": iid, "scope": scope,
                                       "text": str(txt or "")}
                    v = np.frombuffer(blob, dtype="float32")
                    if v.size != DIM:
                        continue
                    for qv in qvs:
                        s = float(np.dot(qv, v))
                        if s > best.get(iid, -1.0):
                            best[iid] = s
        finally:
            con.close()
    out = []
    for iid, s in sorted(best.items(), key=lambda x: x[1], reverse=True):
        if s < min_score:
            continue
        it = dict(rows_by_id[iid]); it["score"] = round(s, 3)
        out.append(it)
        if len(out) >= top:
            break
    return out


def vec_search(scope: str, query: str, top: int = 8) -> list[tuple[str, float]]:
    """Cosine top-k ids over the scope (vectors pre-normalised -> dot)."""
    q = str(query or "").strip()
    if not q:
        return []
    try:
        qv = embed([q])[0]
    except Exception:
        return []
    with _lock:
        con = _conn()
        try:
            rows = con.execute(
                "SELECT id, vec FROM vec WHERE scope=?",
                (str(scope),)).fetchall()
        finally:
            con.close()
    scored = []
    for iid, blob in rows:
        v = np.frombuffer(blob, dtype="float32")
        if v.size != DIM:
            continue
        scored.append((iid, float(np.dot(qv, v))))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top]


_TAIL = re.compile(r"[吗呢吧啊呀嘛的了哦噢～~，。！？!?、\s]+$")
_ASK = re.compile(r"(你觉得|你认为|你有什么想法|你有什么建议|你说呢|怎么办|"
                  r"该如何|如何|能不能|可不可以|可以吗|好吗|行吗|是吧|对吧|"
                  r"有啥想法|有什么看法)")


def _topic(q: str) -> str:
    """Crude topic extraction so question/pleasantry wording doesn't skew the
    embedding (e.g. '想养成点好习惯，你有什么想法？' -> '想养成点好习惯')."""
    t = _ASK.sub(" ", str(q or ""))
    t = _TAIL.sub("", t.strip())
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) >= 4 else str(q or "")


def semantic_l2(query: str, top: int = 8,
                min_score: float = 0.35) -> list[dict]:
    """Semantic search over L2 -> full item dicts from the memory db.

    Uses both the raw query and a topic-stripped variant, keeping the best
    score per item (mitigates wording noise like 提问/客套)."""
    raw = str(query or "").strip()
    if not raw:
        return []
    variants = [raw]
    t = _topic(raw)
    if t and t != raw:
        variants.append(t)
    best: dict[str, float] = {}
    for v in variants:
        for iid, sc in vec_search("l2", v, top=top * 2):
            if sc > best.get(iid, -1.0):
                best[iid] = sc
    hits = sorted(best.items(), key=lambda x: x[1], reverse=True)[: top * 2]
    if not hits:
        return []
    ids = [i for i, _ in hits]
    score = dict(hits)
    con = sqlite3.connect(str(MEMORY_DB))
    try:
        qmarks = ",".join("?" for _ in ids)
        rows = con.execute(
            f"SELECT id, type, importance, status, summary "
            f"FROM l2_items WHERE id IN ({qmarks})", ids).fetchall()
    except Exception:
        rows = []
    finally:
        con.close()
    byid = {r[0]: r for r in rows}
    out = []
    for i in ids:
        if i not in byid:
            continue
        s = score[i]
        if s < min_score:
            continue
        r = byid[i]
        out.append({"id": i, "type": r[1], "importance": r[2],
                    "status": r[3], "summary": r[4], "score": round(s, 3)})
        if len(out) >= top:
            break
    return out
