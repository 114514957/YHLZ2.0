"""台账语义检索（P1，2026-11-13）：复用 memory 的本地 BGE-small-zh + numpy 暴力余弦。

模型实例由 `backend.vector_memory` 统一持有（`embed_cls` 用 CLS 池化，BGE 检索用法），
不再单独加载第二份 92MB 权重；索引是千级记录 × 512 维，暴力余弦 <1ms，
暂不需要 sqlite-vec，超过 5 万条再换。

缓存：`ledger_v2.db` 的 `vec(hash PRIMARY KEY, dim, emb BLOB)`；按记录内容哈希增量。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "models" / "emb" / "bge-small-zh"
DB = ROOT / "cache" / "search" / "ledger_v2.db"
# 这版是 bge-small-zh（非 v1.5），实测加指令前缀反而把 1141 从第 1 挤到第 3，故不加。
QUERY_PREFIX = ""
MAX_CHARS = 1200

_warm_lock = threading.Lock()
_warming = False


def is_ready() -> bool:
    from backend.vector_memory import semantic_ready

    return semantic_ready()


def warm() -> bool:
    """后台加载模型（共享 memory 的实例）；已加载则直接返回。"""
    global _warming
    from backend.vector_memory import ensure_model, semantic_ready

    if semantic_ready():
        return True
    with _warm_lock:
        if _warming:
            return semantic_ready()
        _warming = True
    try:
        return ensure_model()
    finally:
        _warming = False


def embed_texts(texts: list[str], batch: int = 16) -> np.ndarray:
    """CLS pooling + L2 归一化（BGE），返回 (n, 512) float32。"""
    from backend.vector_memory import embed_cls

    if not texts:
        return np.zeros((0, 512), dtype=np.float32)
    return embed_cls([t[:MAX_CHARS] for t in texts])


def _vec_table(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS vec (
          hash TEXT PRIMARY KEY,
          dim INTEGER NOT NULL,
          emb BLOB NOT NULL,
          updated_at REAL NOT NULL
        )""")


def record_text(title: str, body: str) -> str:
    return (title or "") + "\n" + (body or "")[:MAX_CHARS]


def ensure_vec(db_path: Path | str = DB, *, limit_missing: int = 80) -> dict:
    """给缺失记录补向量；缺失超过 limit_missing 时只报告、不阻塞（交给后台）。"""
    db_path = Path(db_path)
    con = sqlite3.connect(str(db_path), timeout=30)
    _vec_table(con)
    rows = con.execute("SELECT hash, title, body FROM records").fetchall()
    have = {h for (h,) in con.execute("SELECT hash FROM vec")}
    missing = [(h, record_text(t, b)) for h, t, b in rows if h not in have]
    con.close()
    if not missing:
        return {"embedded": 0, "missing": 0}
    if limit_missing and len(missing) > limit_missing:
        return {"embedded": 0, "missing": len(missing), "skipped": True}
    t0 = time.time()
    embs = embed_texts([t for _, t in missing])
    con = sqlite3.connect(str(db_path), timeout=30)
    _vec_table(con)
    con.executemany(
        "INSERT OR REPLACE INTO vec(hash,dim,emb,updated_at) VALUES (?,?,?,?)",
        [(h, int(v.shape[0]), v.tobytes(), time.time())
         for (h, _), v in zip(missing, embs)])
    con.commit()
    con.close()
    return {"embedded": len(missing), "missing": 0,
            "elapsed_s": round(time.time() - t0, 1)}


def semantic_search(query: str, db_path: Path | str = DB,
                    top: int = 40) -> list[tuple[str, float]]:
    """返回 [(hash, cosine)]，按分数降序；表不存在/无数据时返回 []。"""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    con = sqlite3.connect(str(db_path), timeout=30)
    try:
        _vec_table(con)
        rows = con.execute("SELECT hash, dim, emb FROM vec").fetchall()
    except Exception:  # noqa: BLE001
        rows = []
    finally:
        con.close()
    if not rows:
        return []
    hashes = []
    mats = []
    for h, dim, blob in rows:
        hashes.append(h)
        mats.append(np.frombuffer(blob, dtype=np.float32).reshape(dim))
    mat = np.vstack(mats)
    q = embed_texts([QUERY_PREFIX + query])[0]
    scores = mat @ q
    order = np.argsort(-scores)[:top]
    return [(hashes[i], float(scores[i])) for i in order]
