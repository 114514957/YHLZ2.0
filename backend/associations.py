"""Association via activation spreading (P5a-1, HippoRAG-style).

在实体关系图上做 Personalized PageRank：从当前线索命中的实体出发，沿关系边
"激活扩散"，命中**关联但非字面相似**的记忆簇，供理解/联想使用（不照读）。

Uses networkx (installed). Graph is small (entities/relations), so PPR is cheap.
"""
from __future__ import annotations

import sqlite3

from backend import entity_graph as eg


def _graph():
    import networkx as nx

    g = nx.Graph()
    con = eg._conn()
    try:
        for s, r, d in con.execute("SELECT src,rel,dst FROM relations"):
            if s and d:
                g.add_edge(s, d, rel=r)
    finally:
        con.close()
    return g


def activate(seeds: list[str], top_k: int = 8) -> list[tuple[str, float]]:
    """Personalized PageRank from `seeds`; return [(entity, score)] excluding seeds."""
    import networkx as nx

    g = _graph()
    seeds = [s for s in (seeds or []) if s in g]
    if not seeds or g.number_of_nodes() == 0:
        return []
    pers = {n: (1.0 if n in seeds else 0.0) for n in g.nodes}
    try:
        pr = nx.pagerank(g, alpha=0.85, personalization=pers)
    except Exception:
        return []
    out = [(n, round(float(v), 5)) for n, v in pr.items() if n not in seeds]
    out.sort(key=lambda x: x[1], reverse=True)
    return out[: int(top_k)]


def _memories_mentioning(name: str, limit: int = 2) -> list[str]:
    from backend.target_memory import DEFAULT_DB

    try:
        con = sqlite3.connect(str(DEFAULT_DB))
        rows = con.execute(
            "SELECT summary FROM l2_items WHERE status!='archive' AND summary LIKE ? "
            "ORDER BY importance DESC LIMIT ?", ("%" + name + "%", int(limit))).fetchall()
        con.close()
        return [str(s) for (s,) in rows]
    except Exception:
        return []


def context_for(text: str, limit: int = 4) -> str:
    """Activation-spread associated memories for a turn (hint block, no reciting)."""
    seeds = eg._entities_in(text, limit=3)
    if not seeds:
        return ""
    act = activate(seeds, top_k=max(6, limit * 2))
    if not act:
        return ""
    lines: list[str] = []
    seen: set = set()
    for name, _score in act:
        for s in _memories_mentioning(name, 2):
            if s in seen:
                continue
            seen.add(s)
            lines.append("- " + s[:100])
            if len(lines) >= int(limit):
                break
        if len(lines) >= int(limit):
            break
    if not lines:
        return ""
    return ("（由联想扩散得到的旧记忆，仅供理解，**不要提及或罗列**）：\n"
            + "\n".join(lines))
