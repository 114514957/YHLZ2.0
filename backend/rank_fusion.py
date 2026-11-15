"""Reciprocal Rank Fusion for memory recall (W2, ledger 1174).

Why: `contextual_recall` merges four channels whose raw scores are not on the
same scale (cosine vs BM25 vs the placeholder constant 0.45 that used to be
assigned to literal/BM25 hits). Sorting those together is meaningless — measured
in 0983, the order collapsed to insertion order once the reranker stopped
rewriting every score.

RRF only needs **ranks**, so channels with incomparable scores can be fused
honestly:

    score(d) = Σ_i  w_i / (k + rank_i(d)),  rank starts at 1

k=60 is the value from our own design (0983 D3) and from A_memorix's fusion.
Env:
    YHLZ_RRF=off            disable fusion (previous behaviour)
    YHLZ_RRF_K=60           rank constant
    YHLZ_RRF_WEIGHTS        "semantic:1,literal:1,diary:1,bm25:1"
"""
from __future__ import annotations

import os

DEFAULT_K = 60


def enabled() -> bool:
    return str(os.getenv("YHLZ_RRF", "on")).strip().lower() not in ("0", "off", "false", "no")


def rank_k() -> int:
    try:
        return max(1, int(os.getenv("YHLZ_RRF_K", str(DEFAULT_K))))
    except Exception:
        return DEFAULT_K


def weights_for(names: list[str]) -> list[float]:
    raw = str(os.getenv("YHLZ_RRF_WEIGHTS", "") or "").strip()
    table: dict[str, float] = {}
    if raw:
        for part in raw.split(","):
            if ":" in part:
                key, _, value = part.partition(":")
                try:
                    table[key.strip()] = float(value)
                except ValueError:
                    continue
    return [float(table.get(n, 1.0)) for n in names]


def rrf(lists: list[list[str]], weights: list[float] | None = None,
        k: int | None = None) -> list[tuple[str, float]]:
    """Fuse ranked id lists into one ranking.

    Each id contributes once per list, at its best (first) rank in that list.
    Unknown/duplicate ids inside one list are ignored after their first rank.
    """
    k = rank_k() if k is None else max(1, int(k))
    weights = list(weights or [1.0] * len(lists))
    scores: dict[str, float] = {}
    for index, ids in enumerate(lists):
        weight = weights[index] if index < len(weights) else 1.0
        if weight <= 0:
            continue
        seen: set[str] = set()
        rank = 0
        for iid in ids:
            key = str(iid)
            if not key or key in seen:
                continue
            seen.add(key)
            rank += 1
            scores[key] = scores.get(key, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def fuse(channels: dict[str, list[str]], weights: list[float] | None = None,
         k: int | None = None) -> dict[str, float]:
    """Convenience wrapper: channel-name keyed lists -> id -> fused score."""
    names = [name for name, ids in channels.items() if ids]
    if not names:
        return {}
    lists = [channels[name] for name in names]
    return dict(rrf(lists, weights=weights or weights_for(names), k=k))
