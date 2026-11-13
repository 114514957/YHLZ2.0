"""Vector memory layer (ledger 0226): semantic recall complement for L2.

SQLite stays the source of truth (approval/downgrade/evidence untouched); this
adds an id->embedding side-table for semantic (换说法) recall. Scope makes it
extendable to l1_summary / l3 / diary later.

Model: BAAI/bge-small-zh-v1.5 (CPU, local). Store: cache/embvec.db
"""
from __future__ import annotations

import os
import pathlib
import re
import sqlite3
import threading
import time

import numpy as np

_PROJECT = pathlib.Path(__file__).resolve().parent.parent
MODEL_DIR = _PROJECT / "models" / "emb" / "bge-small-zh"
VEC_DB = _PROJECT / "cache" / "embvec.db"
MEMORY_DB = _PROJECT / "cache" / "memstore" / "memstore.db"
_lock = threading.RLock()
_model = None
_tokenizer = None
_ready = False
_warming = False
DIM = 512


def semantic_ready() -> bool:
    """True once the embedding model is loaded and usable in this process."""
    return bool(_ready)


def warm_semantic() -> None:
    """Load the embedding model in the background (never blocks a turn).

    Loading costs ~67 s on this machine, so it must never happen inside a
    turn. ``auto`` mode consults :func:`semantic_ready` and stays on the
    lexical path until this thread finishes.
    """
    global _warming
    if _ready or _warming:
        return
    try:
        from backend.memory_resource_policy import semantic_mode

        if semantic_mode() == "off":
            return
    except Exception:
        return
    _warming = True

    def _load():
        global _ready, _warming
        try:
            _load_model(force=True)
            _ready = True
        except Exception:
            _ready = False
        finally:
            _warming = False

    threading.Thread(target=_load, daemon=True).start()


def _load_model(force: bool = False):
    from backend.memory_resource_policy import semantic_model_allowed, MemoryWorkDeferred
    if not force and not semantic_model_allowed():
        raise MemoryWorkDeferred("semantic model disabled; lexical memory remains available")
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
    if not texts:
        return np.zeros((0, DIM), dtype="float32")
    model, tok = _load_model()
    import torch
    with torch.no_grad():
        enc = tok(texts, padding=True, truncation=True,
                  max_length=256, return_tensors="pt")
        out = model(**enc).last_hidden_state
        # mean pooling ignoring padding
        mask = enc["attention_mask"].unsqueeze(-1).float()
        pooled = (out * mask).sum(1) / mask.sum(1).clamp_min(1e-9)
    pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
    return pooled.cpu().numpy().astype("float32")


def embed_cls(texts: list[str], max_length: int = 512) -> np.ndarray:
    """CLS-pooled, L2-normalised embeddings（BGE 检索用法；台账用，和记忆的 mean 池分开）。

    共享同一个模型实例，避免进程里加载两份 92MB 权重。
    """
    if not texts:
        return np.zeros((0, DIM), dtype="float32")
    model, tok = _load_model(force=True)
    import torch
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), 16):
            chunk = texts[i:i + 16]
            enc = tok(chunk, padding=True, truncation=True,
                      max_length=max_length, return_tensors="pt")
            cls = model(**enc).last_hidden_state[:, 0]
            cls = torch.nn.functional.normalize(cls, p=2, dim=1)
            out.append(cls.cpu().numpy().astype("float32"))
    return np.vstack(out)


def ensure_model() -> bool:
    """同步加载模型（给非记忆的调用方：台账语义检索预热）。"""
    global _ready
    try:
        _load_model(force=True)
        _ready = True
        return True
    except Exception:  # noqa: BLE001
        return False


def _migrate_pk(con: sqlite3.Connection) -> None:
    """向量表主键 id → (id, scope)（0499）。

    旧结构以 ``id`` 单列为主键：不同库（主库 / 群记忆 / 测试）出现**同名 id**
    时，后写的会直接**顶掉**先写的向量——分 scope 也挡不住，查 A 库会拿到
    B 库的向量（而文本来自 A 库 = 相似度与文本对不上）。就地重建搬数据。
    """
    info = con.execute("PRAGMA table_info(vec)").fetchall()
    if not info:
        return
    pk_cols = [r[1] for r in sorted((r for r in info if r[5]), key=lambda r: r[5])]
    if pk_cols == ["id", "scope"]:
        return
    con.execute("ALTER TABLE vec RENAME TO vec_old")
    con.execute("CREATE TABLE vec(id TEXT NOT NULL, scope TEXT NOT NULL, "
                "vec BLOB NOT NULL, text TEXT, PRIMARY KEY(id, scope))")
    cols = {r[1] for r in con.execute("PRAGMA table_info(vec_old)")}
    tx = "text" if "text" in cols else "NULL"
    con.execute(f"INSERT OR REPLACE INTO vec(id,scope,vec,text) "
                f"SELECT id,scope,vec,{tx} FROM vec_old")
    con.execute("DROP TABLE vec_old")


def _conn() -> sqlite3.Connection:
    VEC_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(VEC_DB))
    con.execute("CREATE TABLE IF NOT EXISTS vec("
                "id TEXT NOT NULL, scope TEXT NOT NULL, "
                "vec BLOB NOT NULL, text TEXT, PRIMARY KEY(id, scope))")
    cols = {r[1] for r in con.execute("PRAGMA table_info(vec)")}
    if "text" not in cols:
        try:
            con.execute("ALTER TABLE vec ADD COLUMN text TEXT")
        except Exception:
            pass
    _migrate_pk(con)
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


def _threshold_method() -> str:
    """W1 (ledger 1174): relative | percentile | fixed (env YHLZ_VEC_THRESHOLD)."""
    method = str(os.getenv("YHLZ_VEC_THRESHOLD", "relative")).strip().lower()
    return method if method in ("relative", "percentile", "fixed") else "relative"


def pick_threshold(scores, *, top1: float | None = None, method: str | None = None,
                   lo: float = 0.29, hi: float = 0.95,
                   floor: float = 0.0) -> float:
    """Per-query score cutoff, clamped — borrowed from A_memorix's threshold.

    relative (default): ``max(top1 - 0.08, mean + 1σ)`` — 0983 D4, calibrated to
    our bge-small corpus (pairwise mean cos ≈ 0.50, so a fixed 0.42 barely
    filters: measured 2–179 hits).
    percentile: 75th percentile of this result set (A_memorix's default).
    fixed: the caller's own constant (previous behaviour).

    Every mode is clamped into ``[lo, hi]`` (A_memorix's 0.29/0.95), and
    ``floor`` keeps a caller's stricter minimum when it has one.
    """
    vals = [float(s) for s in scores if s is not None]
    if not vals:
        return float(hi)
    method = method or _threshold_method()
    if method == "fixed":
        return float(floor) if floor else float(lo)
    if method == "percentile":
        thr = float(np.percentile(vals, 75))
    else:
        top = float(top1 if top1 is not None else max(vals))
        thr = max(top - 0.08, float(np.mean(vals)) + float(np.std(vals)), float(floor))
    return float(min(hi, max(lo, thr)))


def select_hits(scored: list[tuple[str, float]], top: int,
                min_score: float = 0.0, *, min_results: int = 4,
                method: str | None = None) -> list[tuple[str, float]]:
    """Rank, cut by the dynamic threshold, then keep at least ``min_results``."""
    if not scored:
        return []
    ranked = sorted(scored, key=lambda x: float(x[1]), reverse=True)
    if _threshold_method() == "fixed" or method == "fixed":
        cut = float(min_score or 0.0)
    else:
        cut = pick_threshold([s for _, s in ranked], top1=float(ranked[0][1]),
                             floor=float(min_score or 0.0), method=method)
    hits = [x for x in ranked if float(x[1]) >= cut][:max(1, top)]
    if len(hits) < min_results:
        hits = ranked[: max(1, min(top, min_results))]
    return hits


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
    for iid, s in select_hits(list(best.items()), top, min_score):
        it = dict(rows_by_id[iid]); it["score"] = round(float(s), 3)
        out.append(it)
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


_RERANK_DIR = _PROJECT / "models" / "emb" / "bge-reranker-base"
_rr = {"model": None, "tok": None, "loading": False}


def warm_reranker() -> None:
    """Load the reranker in the background (never blocks a turn)."""
    from backend.memory_resource_policy import semantic_model_allowed
    if not semantic_model_allowed():
        return
    if _rr["model"] is not None or _rr["loading"]:
        return
    import threading

    def _load():
        try:
            if not semantic_model_allowed():
                return
            from transformers import (AutoModelForSequenceClassification,
                                      AutoTokenizer)

            _rr["loading"] = True
            _rr["tok"] = AutoTokenizer.from_pretrained(str(_RERANK_DIR))
            _rr["model"] = AutoModelForSequenceClassification.from_pretrained(
                str(_RERANK_DIR))
            _rr["model"].eval()
        except Exception:
            pass
        finally:
            _rr["loading"] = False

    threading.Thread(target=_load, daemon=True).start()


def rerank(query: str, docs: list[str]) -> list[float]:
    """Cross-encoder rerank scores (BAAI/bge-reranker-base, CPU).
    Non-blocking: on first use it kicks off background loading and returns
    zeros for now (caller keeps its vector/literal order)."""
    q = str(query or "").strip()
    ds = [str(d or "") for d in (docs or [])]
    from backend.memory_resource_policy import semantic_model_allowed
    if not semantic_model_allowed():
        raise RuntimeError("reranker disabled; preserve lexical scores")
    if not q or not ds:
        return [0.0 for _ in ds]
    if _rr["model"] is None:
        warm_reranker()
        return [0.0 for _ in ds]
    try:
        import torch

        pairs = [[q, d] for d in ds]
        with torch.no_grad():
            enc = _rr["tok"](pairs, padding=True, truncation=True,
                             max_length=256, return_tensors="pt")
            logits = _rr["model"](**enc).logits.view(-1)
            return [float(x) for x in torch.sigmoid(logits)]
    except Exception:
        return [0.0 for _ in ds]


def l2_scope(db_path=None) -> str:
    """L2 向量按**库**分 scope（0499）。

    默认库保持 ``"l2"``（不动既有缓存，避免无谓重嵌入）；其它库（群记忆/测试）
    用 ``"l2@<库名>"``。此前所有库共用 scope ``"l2"`` → 同名 id 会互相覆盖，
    且不同库的条目被写进同一张表后永远查不到（静默失效 + 污染）。
    """
    p = pathlib.Path(db_path) if db_path else MEMORY_DB
    try:
        if p.resolve() == MEMORY_DB.resolve():
            return "l2"
    except Exception:
        pass
    stem = re.sub(r"[^\w\-]+", "_", p.stem)[:40] or "db"
    return "l2@" + stem


def _date_str(ts) -> str:
    """条目日期（离线校验/召回上下文用；与 target_memory._date_str 同口径）。"""
    try:
        v = float(ts or 0)
        return time.strftime("%Y-%m-%d", time.localtime(v)) if v > 0 else ""
    except Exception:
        return ""


def semantic_l2(query: str, top: int = 8,
                min_score: float = 0.35,
                db_path=None,
                include_invalid: bool = False) -> list[dict]:
    """Semantic search over L2 -> full item dicts from the memory db.

    Uses both the raw query and a topic-stripped variant, keeping the best
    score per item (mitigates wording noise like 提问/客套).
    ``db_path`` 指定要 join 的库（默认主库）；scope 由 :func:`l2_scope` 决定。
    ``include_invalid``：默认**排除软失效条目**（M1 契约：默认读只看现状；
    旧实现没过滤 → 被取代的旧事实会经语义路径漏回召回）。
    """
    raw = str(query or "").strip()
    if not raw:
        return []
    scope = l2_scope(db_path)
    variants = [raw]
    t = _topic(raw)
    if t and t != raw:
        variants.append(t)
    best: dict[str, float] = {}
    for v in variants:
        for iid, sc in vec_search(scope, v, top=top * 2):
            if sc > best.get(iid, -1.0):
                best[iid] = sc
    hits = select_hits(list(best.items()), top, min_score)
    if not hits:
        return []
    ids = [i for i, _ in hits]
    score = dict(hits)
    where = "" if include_invalid else " AND COALESCE(invalid_at,0)=0"
    con = sqlite3.connect(str(db_path or MEMORY_DB))
    try:
        qmarks = ",".join("?" for _ in ids)
        rows = con.execute(
            f"SELECT id, type, importance, status, summary, "
            f"COALESCE(NULLIF(valid_at,0), created_at) "
            f"FROM l2_items WHERE id IN ({qmarks}){where}", ids).fetchall()
    except Exception:
        rows = []
    finally:
        con.close()
    byid = {r[0]: r for r in rows}
    out = []
    for i in ids:
        if i not in byid:
            continue
        # W1: threshold (dynamic or fixed) was already applied by select_hits;
        # re-checking against the caller's constant would undo the dynamic cut.
        s = score[i]
        r = byid[i]
        out.append({"id": i, "type": r[1], "importance": r[2],
                    "status": r[3], "summary": r[4], "score": round(float(s), 3),
                    "date": _date_str(r[5])})
        if len(out) >= top:
            break
    return out
