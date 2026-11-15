# -*- coding: utf-8 -*-
"""记忆召回的语义索引（v2 第二段）。

设计（台账 1235/1238 的实验结论）：
  · 候选池 = active + **全类型** + role∈{her,owner} + 非碎片（177 条）
  · 闸门   = 长度≥8 且非工程指令 且 top1 相似度≥阈值（默认 0.45）
  · 相似度 = 512 维嵌入 cosine（`backend.vector_memory.embed_cls`，与台账同一套）
  · 索引   = `cache/memvec.db`：把 (id, 内容哈希, 向量) 存下来，内容没变就不重算

**降级**：嵌入模型不可用（`semantic_model_allowed()` 为假或加载失败）时，
自动回落到字符串 3-gram 严格召回，不让生产"没有记忆"。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Optional

from backend.memory_recall_v2 import (INJECT_TYPES, _NONWORD, _grams, load_pool,
                                      recall_strict)

__all__ = ["WIDE_TYPES", "ENG_QUERY", "SemanticIndex", "gate_allows",
           "semantic_recall", "default_paths"]

WIDE_TYPES = ("preference", "event", "decision", "fact", "knowledge", "context")
ENG_QUERY = re.compile(r"(报错|测试|重启|脚本|训练|评测|接口|端口|提交|部署|编译|显存|日志|"
                       r"命令|进程|配置|代码|文件|目录|函数|变量|bug|BUG|git|pip|npm)")
# 召回线索：明确在问过去/求证/指代
CUE_QUERY = re.compile(r"(记得|记住|记着|上次|之前|我说过|你说过|那[个件次]|后来|"
                       r"是什么|为什么|怎么回事|多少|谁|哪里|哪个|是不是|有没有|"
                       r"来着|讲过|说过|聊过)")
# 一般疑问：也算"可能在问事"，门槛放低一档
QUESTION_QUERY = re.compile(r"[?？]|吗|呢|怎么|什么|哪|多少|能不能|是不是|会不会|要不要")
SIM_MIN = 0.45          # 有线索时的门槛
SIM_HIGH = 0.70         # 无线索时必须极高，才敢注入
MIN_QUERY_CHARS = 6
MAX_RESULTS = 2
STOP_QUERIES = {"在吗", "嗯", "哦", "晚安", "早", "早啊", "哈哈", "哈哈哈哈", "在不在",
                "你吃饭了吗", "今天天气不错", "随便聊聊", "你说呢"}


def default_paths(root: os.PathLike | str | None = None) -> tuple[Path, Path]:
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    return (base / "cache" / "memstore" / "memstore.db", base / "cache" / "memvec.db")


def gate_allows(query: str, *, min_chars: int = MIN_QUERY_CHARS) -> tuple[bool, str]:
    """判断这句该不该去想起记忆。返回 (放行?, 理由)。

    顺序有讲究：**先判"是不是工程指令/寒暄"，再判长度**——
    否则"跑一下测试"(5 字)会被报成"太短"，掩盖真正原因。
    """
    q = str(query or "").strip()
    body = _NONWORD.sub("", q)
    if body in STOP_QUERIES or q in STOP_QUERIES:
        return False, "寒暄/应答"
    if ENG_QUERY.search(q):
        return False, "工程指令"
    if len(body) < min_chars:
        return False, "太短(%d<%d)" % (len(body), min_chars)
    return True, "ok"


def similarity_floor(query: str) -> tuple[float, str]:
    """这条问句该用哪个相似度门槛（两档制）。

    有召回线索/疑问 → SIM_MIN；纯陈述闲聊 → 必须 SIM_HIGH 才敢信。
    依据：台账 1238 实测，闲聊长句的 top1 相似度也能到 0.54–0.67，
    单靠余弦分不开"闲聊"与"要回忆"，所以要意图这一层。
    """
    q = str(query or "")
    if CUE_QUERY.search(q):
        return SIM_MIN, "有召回线索"
    if QUESTION_QUERY.search(q):
        return SIM_MIN, "疑问句"
    return SIM_HIGH, "无线索"


class SemanticIndex:
    """记忆向量索引。嵌入函数可注入（测试用假函数，不加载模型）。"""

    def __init__(self, path: os.PathLike | str, *,
                 embed_fn: Optional[Callable[[list[str]], Any]] = None) -> None:
        self.path = Path(path)
        self._embed_fn = embed_fn
        self._pool: list[dict[str, Any]] = []
        self._vecs: dict[str, Any] = {}
        self._np = None
        self._matrix = None
        self._ids: list[str] = []
        self.last_build = 0.0
        self.degraded = False

    # ── 内部 ────────────────────────────────────────────────────────
    def _embed(self, texts: list[str]):
        if self._embed_fn is not None:
            fn = self._embed_fn
        else:
            from backend.vector_memory import embed_cls as fn  # noqa: N813
        return fn(texts)

    def _ensure_np(self):
        if self._np is None:
            import numpy as np
            self._np = np
        return self._np

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.path))
        con.execute("""CREATE TABLE IF NOT EXISTS vec(
            id TEXT PRIMARY KEY, hash TEXT, dim INTEGER, vec BLOB, text TEXT,
            role TEXT, type TEXT, updated REAL)""")
        con.commit()
        return con

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]

    # ── 构建 / 载入 ────────────────────────────────────────────────
    def build(self, db_path: os.PathLike | str, *, types: tuple[str, ...] = WIDE_TYPES,
              force: bool = False) -> dict[str, Any]:
        """重建索引：内容没变（哈希相同）的条目复用旧向量。"""
        np = self._ensure_np()
        t0 = time.time()
        self._pool = load_pool(db_path, types=types)
        con = self._connect()
        try:
            old = {r[0]: (r[1], r[2]) for r in
                   con.execute("select id, hash, vec from vec").fetchall()}
            todo, urls = [], []
            for it in self._pool:
                h = self._hash(it["text"])
                if not force and it["id"] in old and old[it["id"]][0] == h:
                    continue
                todo.append(it)
                urls.append(it["text"])
            if urls:
                vecs = np.asarray(self._embed(urls), dtype=np.float32)
                for it, v in zip(todo, vecs):
                    con.execute(
                        "insert or replace into vec(id,hash,dim,vec,text,role,type,updated)"
                        " values(?,?,?,?,?,?,?,?)",
                        (it["id"], self._hash(it["text"]), int(v.shape[0]),
                         v.astype(np.float32).tobytes(), it["text"], it["role"],
                         it.get("type") or "", time.time()))
                con.commit()
            # 清理已不属于候选池的
            keep = {it["id"] for it in self._pool}
            for iid in list(old):
                if iid not in keep:
                    con.execute("delete from vec where id=?", (iid,))
            con.commit()
            rows = con.execute("select id, vec from vec").fetchall()
        finally:
            con.close()

        by_id = {it["id"]: it for it in self._pool}
        self._ids, mats = [], []
        for iid, blob in rows:
            if iid not in by_id:
                continue
            self._ids.append(iid)
            mats.append(np.frombuffer(blob, dtype=np.float32))
        self._matrix = (np.vstack(mats) if mats else np.zeros((0, 512), dtype=np.float32))
        if self._matrix.size:
            self._matrix /= (np.linalg.norm(self._matrix, axis=1, keepdims=True) + 1e-9)
        self.last_build = time.time() - t0
        self.degraded = False
        return {"pool": len(self._pool), "indexed": len(self._ids),
                "reused": max(0, len(self._pool) - len(urls)),
                "rebuilt": len(urls), "seconds": round(self.last_build, 2)}

    def load(self, db_path: os.PathLike | str, *,
             types: tuple[str, ...] = WIDE_TYPES) -> bool:
        """只载入现有索引（不重算）。返回是否可用。"""
        np = self._ensure_np()
        if not self.path.exists():
            return False
        self._pool = load_pool(db_path, types=types)
        con = sqlite3.connect(str(self.path))
        try:
            rows = con.execute("select id, vec from vec").fetchall()
        finally:
            con.close()
        by_id = {it["id"]: it for it in self._pool}
        self._ids, mats = [], []
        for iid, blob in rows:
            if iid in by_id:
                self._ids.append(iid)
                mats.append(np.frombuffer(blob, dtype=np.float32))
        if not mats:
            return False
        self._matrix = np.vstack(mats)
        self._matrix /= (np.linalg.norm(self._matrix, axis=1, keepdims=True) + 1e-9)
        return True

    # ── 查询 ───────────────────────────────────────────────────────
    def search(self, query: str, *, sim_min: float | None = None,
               limit: int = MAX_RESULTS) -> list[dict[str, Any]]:
        ok, _why = gate_allows(query)
        if not ok or self._matrix is None or not len(self._ids):
            return []
        floor, _reason = similarity_floor(query)
        th = floor if sim_min is None else max(float(sim_min), 0.0)
        np = self._ensure_np()
        q = np.asarray(self._embed([query]), dtype=np.float32)[0]
        q /= (np.linalg.norm(q) + 1e-9)
        sims = self._matrix @ q
        order = np.argsort(-sims)[:max(limit, 1) * 3]
        by_id = {it["id"]: it for it in self._pool}
        out = []
        for j in order:
            if sims[j] < th:
                break
            iid = self._ids[int(j)]
            it = by_id.get(iid)
            if not it:
                continue
            out.append({"id": iid, "summary": it["text"], "score": float(sims[j]),
                        "role": it["role"], "type": it.get("type")})
            if len(out) >= limit:
                break
        return out


def semantic_recall(query: str, *, index: Optional[SemanticIndex], db_path,
                    min_shared: int = 2, limit: int = MAX_RESULTS) -> list[dict[str, Any]]:
    """生产入口：语义优先，模型不可用则回落到字符串严格召回。"""
    if index is not None and not index.degraded:
        try:
            got = index.search(query, limit=limit)
            if got:
                return got
            ok, _ = gate_allows(query)
            if ok:
                return []      # 闸门放行但确实没有相关记忆 → 不回退，避免噪声
        except Exception:  # noqa: BLE001
            index.degraded = True
    pool = load_pool(db_path, types=WIDE_TYPES)
    return recall_strict(query, pool=pool, limit=limit, min_shared=min_shared)
