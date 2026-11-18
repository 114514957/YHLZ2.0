# -*- coding: utf-8 -*-
"""召回加严（v2）：只在**有把握**时注入记忆块。

设计依据（台账 1233/1235）：
  旧实现 `contextual_recall` 用字符 2-gram 子串匹配、无相关性门槛、Top-N 直接注入，
  实测"真用户发言命中 66.7%，其中 62% 明显无关"（有效约 25%）。

v2 的四条：
  1. **只取 her/owner 两层**（分层见 backend/memory_roles.py）——工程流水账不进注入
  2. **3-gram ≥2** 才算相关（原为 2-gram 任意命中）
  3. **碎片过滤**：去掉 `元亨:` 前缀/群标签后 <8 字的不参与
  4. **相关性门槛**：共享 3-gram 数 ≥ min_shared（默认 2），按分数排序取前 N

刻意**宁缺勿滥**：注入噪音比不注入更伤（会把口吻带成项目经理）。
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from typing import Any, Optional

from backend.memory_roles import classify, is_injectable

__all__ = ["recall_strict", "load_pool", "INJECT_TYPES"]

INJECT_TYPES = ("preference", "event", "decision")
MIN_BODY_CHARS = 8
DEFAULT_MIN_SHARED = 2
STOP_GRAMS = {"什么", "怎么", "为什", "么样", "是不", "不是", "可以", "现在", "今天",
              "一个", "这个", "那个", "我们", "你们", "他们"}
_TAG = re.compile(r"^(?:\[[^\]]{1,60}\])?\s*")
_PREFIX = re.compile(r"^元亨[:：]\s*")
_NONWORD = re.compile(r"[\s\W_]+")
# 2026-11-18：@ 标签可以出现在正文**中间**，不只是开头
_AT = re.compile(r"\[\[at:\s*\d+\]\]")
# 纯应答/语气词：够长也不算记忆
_FILLER = re.compile(
    r"^(?:在|嗯+|哦+|啊+|好|好的|好了|行|可以|对|是|是的|没事|收到|明白|知道了|"
    r"哈哈+|嘿+|谢谢|ok|OK)[。！？.!~～\s]*$")


def _clean(text: str) -> str:
    t = _TAG.sub("", str(text or ""))
    t = _PREFIX.sub("", t)
    t = _AT.sub("", t)
    return t.strip()


def _core(text: str) -> str:
    """去掉标签/前缀/@标签后的**正文**，用来判断"够不够当一条记忆"。"""
    return _AT.sub("", _clean(text)).strip()


def _grams(s: str, n: int = 3) -> set[str]:
    s = _NONWORD.sub("", s)
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def load_pool(db_path: os.PathLike | str,
              now: Optional[float] = None,
              types: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """从 memstore 载入可注入候选池（active + 类型 + 非碎片 + her/owner）。

    `types` 默认 INJECT_TYPES；传 None 用默认，传更宽的集合可做实验
    （2026-11-15 实测：`fact` 里全是实质记忆，被默认类型过滤掉会让召回结构性偏低）。
    """
    keep_types = tuple(types) if types is not None else INJECT_TYPES
    ts = time.time() if now is None else now
    con = sqlite3.connect(str(db_path), timeout=1.0)
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "select id,type,importance,summary,source,status,keywords,role "
            "from l2_items").fetchall()
    finally:
        con.close()

    pool: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if str(d.get("status") or "") != "active":
            continue
        if str(d.get("type") or "") not in keep_types:
            continue
        if int(d.get("importance") or 0) < 4:
            continue
        body = _clean(d.get("summary") or "")
        core = _core(d.get("summary") or "")
        if len(_NONWORD.sub("", core)) < MIN_BODY_CHARS:
            continue
        if _FILLER.match(core):
            continue
        # 2026-11-16（台账 1285）：优先用**库里落好的** role（tools/memory_role_migrate.py）；
        # 旧库没有该列/空值时，才现场跑规则分类。
        role = str(d.get("role") or "").strip()
        if not role:
            role, _why = classify(d)
        if not is_injectable(role):
            continue
        # 2026-11-18：**黄金样本不进召回池**。实测 r06 命中 gld_113 抢走了真记忆的位置
        # ——黄金样本是人格锚点，不是"关于老爹的事实"。YHLZ_POOL_SKIP_GOLD=0 可回退。
        if (str(os.getenv("YHLZ_POOL_SKIP_GOLD", "1")).lower() not in ("0", "off", "false")
                and str(d.get("id") or "").startswith("gld_")):
            continue
        pool.append({"id": d["id"], "text": body, "role": role,
                     "type": d.get("type"), "importance": d.get("importance"),
                     "keywords": str(d.get("keywords") or ""),
                     "grams": _grams(body), "_loaded_at": ts})
    return pool


def recall_strict(query: str, *, pool: list[dict[str, Any]], limit: int = 3,
                  min_shared: int = DEFAULT_MIN_SHARED) -> list[dict[str, Any]]:
    """严格召回：共享 3-gram ≥ min_shared 才返回，按共享数降序。"""
    q = str(query or "").strip()
    if len(q) < 6:
        return []
    qg = _grams(q) - STOP_GRAMS
    if len(qg) < 2:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for it in pool:
        shared = len(qg & it["grams"])
        if shared >= min_shared:
            scored.append((shared, it))
    scored.sort(key=lambda x: (-x[0], -(int(x[1].get("importance") or 0))))
    out = []
    for shared, it in scored[:limit]:
        out.append({"id": it["id"], "summary": it["text"], "score": shared,
                    "role": it["role"], "type": it.get("type")})
    return out
