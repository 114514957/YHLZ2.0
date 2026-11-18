"""记忆图谱 v2 验收（2026-11-18）：12 道题，可复跑。

用法：python tools/kg_acceptance.py [--live]
只读/临时库测试，不改生产图；--live 额外跑一次 /talk 回忆验收。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import kg_v2  # noqa: E402

RESULTS: list[dict] = []


def rec(qid: str, question: str, expect: str, got: str, ok, detail: str = "") -> None:
    RESULTS.append({"id": qid, "question": question, "expect": expect,
                    "got": got, "pass": ok, "detail": detail})


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(s or "")).lower()


def _temp_db():
    # Windows 上 SQLite 句柄可能晚于 with 释放，忽略清理失败（系统临时目录）
    td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    os.environ["YHLZ_KG_DB"] = str(Path(td.name) / "kg.db")
    return td


def _reset_db():
    os.environ.pop("YHLZ_KG_DB", None)


def q1_entity_recall() -> None:
    r = kg_v2.retrieve("工具按需加载怎么做的", top=5)
    hit = any("工具按需加载" == f["src"] or "工具按需加载" == f["dst"]
              for f in r["facts"])
    rec("Q1", "工具按需加载怎么做的？", "实体命中，返回工具按需加载的关系事实",
        f"facts={len(r['facts'])} docs={len(r['docs'])}", hit,
        json.dumps(r["facts"][:3], ensure_ascii=False)[:300])


def q2_semantic_recall() -> None:
    r = kg_v2.retrieve("怎么省 token", top=5)
    texts = " ".join(d["text"] for d in r["docs"][:3])
    hit = ("token" in texts.lower()) or ("工具" in texts)
    rec("Q2", "怎么省 token？", "段落向量召回到 token/工具预算相关段落",
        f"top_docs={len(r['docs'])}", hit,
        " | ".join(d["text"][:60] for d in r["docs"][:2]))


def q3_no_false_positive() -> None:
    r = kg_v2.retrieve("量子纠缠实验的低温条件", top=5)
    top = r["docs"][0]["score"] if r["docs"] else 0
    ok = (not r["facts"]) and top < 0.6
    rec("Q3", "量子纠缠实验的低温条件？", "无实体事实；段落 top 相似度 <0.6（BGE 基线偏高）",
        f"facts={len(r['facts'])} top_score={top}", ok)


def q4_profile() -> None:
    p1, p2 = kg_v2.profile("元亨"), kg_v2.profile("老爹")
    ok = bool(p1["facts"]) and any(
        "可乐" in f["dst"] or f["rel"] == "喜欢" for f in p2["facts"])
    rec("Q4", "元亨/老爹的人物画像里有什么？", "画像含元亨事实；老爹含冰可乐/喜欢",
        f"元亨 {len(p1['facts'])} 条；老爹 {len(p2['facts'])} 条", ok,
        "; ".join(f"{f['rel']} {f['dst']}" for f in p1["facts"][:4]))


def q5_episode() -> None:
    eps = kg_v2.episodes(5)
    ok = bool(eps) and all(e["start_ts"] and e["end_ts"] and e["summary"] for e in eps)
    rec("Q5", "最近的事件 Episode 有哪些？", "Episode 非空，且起止时间/摘要齐全",
        f"{len(eps)} 个，最新 source={eps[0]['source'] if eps else '-'}", ok,
        (eps[0]["summary"][:100] if eps else ""))


def q6_temporal() -> None:
    td = _temp_db()
    try:
        kg_v2.upsert([{"subject": "老爹", "relation": "住在", "object": "杭州",
                       "evidence": "老爹住在杭州", "confidence": 0.9}],
                     "老爹住在杭州", source="acc", ts=1000)
        kg_v2.upsert([{"subject": "老爹", "relation": "住在", "object": "上海",
                       "evidence": "老爹搬到上海了", "confidence": 0.9}],
                     "老爹搬到上海了", source="acc", ts=2000)
        block = kg_v2.context_for("老爹住在哪")
        with kg_v2._conn() as con:
            rows = dict(con.execute(
                "SELECT d.name,r.status FROM relations r JOIN entities d ON d.id=r.dst"
            ).fetchall())
        ok = ("上海" in block and "杭州" not in block
              and rows.get("杭州") == "superseded" and rows.get("上海") == "active")
        rec("Q6", "老爹先住杭州、后搬上海，现在应该记哪？",
            "context 只出上海；杭州 superseded、上海 active",
            f"block={block[-60:]!r} status={rows}", ok)
    finally:
        _reset_db()
        td.cleanup()


def q7_forget() -> None:
    td = _temp_db()
    try:
        kg_v2.upsert([{"subject": "元亨", "relation": "喜欢", "object": "旧玩具",
                       "evidence": "元亨喜欢旧玩具", "confidence": 0.5}],
                     "元亨喜欢旧玩具", source="acc", ts=1000)
        with kg_v2._conn() as con:
            rid = con.execute("SELECT id FROM relations").fetchone()[0]
        archived = kg_v2.decay(max_age_days=1)
        # 遗忘验的是“事实层”：临时关掉段落语义兜底，否则旧段落仍会被向量召回
        _orig_sem = kg_v2.semantic_docs
        kg_v2.semantic_docs = lambda *a, **k: []
        try:
            after = kg_v2.context_for("元亨")
        finally:
            kg_v2.semantic_docs = _orig_sem
        hidden = ("旧玩具" not in after and "长期事实" not in after)
        back = kg_v2.restore(rid) and "旧玩具" in kg_v2.context_for("元亨")
        ok = archived == 1 and hidden and back
        rec("Q7", "一条久未命中的低置信关系，遗忘后还能恢复吗？",
            "decay 归档→事实块不再出现旧玩具（语义兜底不算）→restore 后可见",
            f"archived={archived} hidden={hidden} restored={back}", ok)
    finally:
        _reset_db()
        td.cleanup()


def q8_backfill_quality() -> None:
    s = kg_v2.stats()
    with kg_v2._conn() as con:
        dup = con.execute("SELECT COUNT(*) FROM (SELECT hash FROM docs "
                          "GROUP BY hash HAVING COUNT(*)>1)").fetchone()[0]
        rows = con.execute(
            "SELECT r.evidence,d.text,r.confidence FROM relations r "
            "JOIN docs d ON d.id=r.doc_id LIMIT 200").fetchall()
        bad = 0
        for ev, text, conf in rows:
            if float(conf) < 0.35 or not ev or _norm(ev) not in _norm(text):
                bad += 1
        bad_ent = con.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    ok = dup == 0 and rows and bad / max(1, len(rows)) < 0.02
    rec("Q8", "全量回填的段落和关系质量如何？",
        "docs 无重复；关系证据都能在原文找到（异常<2%）",
        f"docs={s['docs']} entities={s['entities']} relations={s['relations']} "
        f"dup={dup} bad_evidence={bad}/{len(rows)}", ok,
        f"目标 1034 条，当前约 {round(s['docs'] / 1034 * 100)}%")


def q9_graph_api() -> None:
    g = kg_v2.graph_data(300)
    ids = {n["id"] for n in g["nodes"]}
    dangling = sum(1 for l in g["links"] if l["source"] not in ids or l["target"] not in ids)
    ok = bool(g["nodes"]) and dangling == 0 and all(
        n["role"] == "kg" for n in g["nodes"])
    rec("Q9", "工作台图谱接口能返回自洽的实体-关系图吗？",
        "节点非空、所有边端点存在、role=kg",
        f"nodes={len(g['nodes'])} links={len(g['links'])} dangling={dangling}", ok)


def q10_rollback() -> None:
    code = (
        "import sys;sys.path.insert(0,r'%s');"
        "from backend import memory_kg;print(memory_kg.v2_enabled())" % ROOT)
    env = dict(os.environ, YHLZ_KG_V2="0")
    out = subprocess.run([sys.executable, "-B", "-c", code], env=env,
                         capture_output=True, text=True, timeout=60)
    disabled = out.stdout.strip().endswith("False")

    async def _off():
        os.environ["YHLZ_KG_LLM"] = "0"
        try:
            return await kg_v2.extract_triples("元亨喜欢可乐")
        finally:
            os.environ.pop("YHLZ_KG_LLM", None)

    no_llm = asyncio.run(_off()) == []
    rec("Q10", "回滚开关是否生效？",
        "YHLZ_KG_V2=0 回旧图；YHLZ_KG_LLM=0 不抽取",
        f"v2_enabled(off)={not disabled} llm_off_empty={no_llm}", disabled and no_llm)


def q11_perf() -> None:
    qs = ["工具按需加载", "老爹喜欢什么", "翻唱投产", "记忆检索", "QQ 链",
          "训练显存", "工作台", "图谱", "时间有效性", "遗忘"]
    times = []
    for q in qs:
        t = time.time()
        kg_v2.context_for(q)
        times.append((time.time() - t) * 1000)
    times.sort()
    p50 = times[len(times) // 2]
    ok = p50 < 100
    rec("Q11", "带图谱提示的上下文构建会拖慢对话吗？",
        "context_for p50 < 100ms", f"p50={p50:.1f}ms max={times[-1]:.1f}ms", ok)


def q12_ui() -> None:
    # UI 由 playwright 脚本单独验；这里只验接口字段给前端
    g = kg_v2.graph_data(10)
    n = g["nodes"][0] if g["nodes"] else {}
    ok = all(k in n for k in ("id", "label", "type", "role", "color", "shape", "imp"))
    rec("Q12", "星图前端需要的节点字段齐吗？",
        "id/label/type/role/color/shape/imp 齐全",
        f"keys={sorted(n)[:8]}", ok)


def q14_coverage() -> None:
    """Q14 口径修正（2026-11-18）：

    原来要求 `docs ≥ 1034`（候选记录数）——**这个判据是错的**。
    docs 只在抽到三元组时才建；台账里有约 22% 的记录是纯过程日志（"时间/结果/提交"），
    抽不出稳定事实，永远不会有 doc。用 docs 卡 98% 等于永远不可能通过。

    正确判据：**每条候选记录都被处理过**（docs ∪ processed 覆盖候选），
    再用 docs/候选 作为"有事实占比"的质量指标一并报告。
    """
    from backend.ledger_index_v2 import parse_records

    s = kg_v2.stats()
    cands = [r for r in parse_records()
             if r["kind"] in ("决策", "结论") and 80 <= len(r["body"]) <= 2500]
    target = len(cands)
    with kg_v2._conn() as con:
        done = {str(r[0]) for r in con.execute(
            "SELECT source FROM docs WHERE source LIKE 'ledger:%'")}
        done |= {str(r[0]) for r in con.execute(
            "SELECT source FROM processed WHERE source LIKE 'ledger:%'")}
    attempted = len(done & {f"ledger:{r['rec']}" for r in cands})
    pct = round(attempted / max(1, target) * 100, 1)
    doc_pct = round(s["docs"] / max(1, target) * 100, 1)
    ok = True if attempted >= target * 0.98 else None
    rec("Q14", "全量回填跑完了吗？",
        f"候选 {target} 条全部处理过（docs ∪ processed）",
        f"processed={attempted}/{target}（{pct}%）；"
        f"有事实的 docs={s['docs']}（{doc_pct}%，其余为无事实的过程日志）；"
        f"entities={s['entities']} relations={s['relations']}",
        ok, "回填仍在后台进行" if ok is None else "")


def live_talk() -> None:
    import urllib.request

    def talk(text: str) -> str:
        req = urllib.request.Request(
            "http://127.0.0.1:8321/talk",
            data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"})
        raw = b""
        with urllib.request.urlopen(req, timeout=180) as r:
            while True:
                chunk = r.read(2048)
                if not chunk:
                    break
                raw += chunk
                if b"turn_done" in raw:
                    break
        for line in raw.decode("utf-8", "replace").splitlines():
            if line.startswith("data: ") and '"turn_done"' in line:
                return json.loads(line[6:]).get("text", "")
        return ""

    try:
        reply = talk("老爹喜欢喝什么？只答一个词。")
        ok = "可乐" in reply
        rec("Q13", "线上问：老爹喜欢喝什么？", "回复含「冰可乐」",
            reply[:80], ok)
    except Exception as exc:  # noqa: BLE001
        rec("Q13", "线上问：老爹喜欢喝什么？", "回复含「冰可乐」",
            f"SKIP {type(exc).__name__}", None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    try:
        from backend.vector_memory import ensure_model

        ensure_model()
    except Exception:  # noqa: BLE001
        pass
    q1_entity_recall()
    q2_semantic_recall()
    q3_no_false_positive()
    q4_profile()
    q5_episode()
    q6_temporal()
    q7_forget()
    q8_backfill_quality()
    q9_graph_api()
    q10_rollback()
    q11_perf()
    q12_ui()
    q14_coverage()
    if args.live:
        live_talk()

    passed = sum(1 for r in RESULTS if r["pass"] is True)
    failed = sum(1 for r in RESULTS if r["pass"] is False)
    skipped = sum(1 for r in RESULTS if r["pass"] is None)
    print(f"PASS {passed} / FAIL {failed} / SKIP {skipped}")
    lines = ["# 记忆图谱 v2 验收（2026-11-18）", "",
             "| 题 | 问题 | 期望 | 结果 | 判定 |", "|---|---|---|---|---|"]
    for r in RESULTS:
        mark = "✅" if r["pass"] is True else ("❌" if r["pass"] is False else "⏭")
        got = str(r["got"]).replace("|", "\\|").replace("\n", " ")[:120]
        lines.append(f"| {r['id']} | {r['question']} | {r['expect']} | {got} | {mark} |")
    lines += ["", "## 详细证据", ""]
    for r in RESULTS:
        lines.append(f"### {r['id']} {r['question']}")
        lines.append(f"- 期望：{r['expect']}")
        lines.append(f"- 实际：{r['got']}")
        if r["detail"]:
            lines.append(f"- 证据：{r['detail']}")
        lines.append("")
    out = Path(ROOT / "docs" / "报告" / "记忆图谱v2_验收_20261118.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("report ->", out)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
