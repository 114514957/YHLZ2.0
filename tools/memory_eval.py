"""Memory evaluation baseline (ledger 0439): LoCoMo B-mode + self scenes.

B-mode = our answerer (DeepSeek) + our judge (DeepSeek), so figures are an
INTERNAL baseline, NOT comparable to the frozen-protocol vendor numbers.

Usage:
  python tools/memory_eval.py scenes
  python tools/memory_eval.py locomo --conversations 2 --questions 15
  python tools/memory_eval.py locomo --download   # fetch locomo10.json first

Dataset: LoCoMo (CC BY-NC 4.0, snap-research/locomo) — fetched locally to
data/eval/ (data/ is gitignored; never redistributed).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import sys
import tempfile
import time
import urllib.request

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backend.target_kw_index import KeywordIndex  # noqa: E402
from backend.target_memory import L2Item, TargetMemoryService  # noqa: E402

DATA = _ROOT / "data" / "eval" / "locomo10.json"
URL = ("https://raw.githubusercontent.com/snap-research/locomo/main/"
       "data/locomo10.json")


# ---------------- LoCoMo ----------------
def ensure_dataset(allow_download: bool) -> pathlib.Path:
    if DATA.exists():
        return DATA
    if not allow_download:
        raise SystemExit(f"dataset missing: {DATA} (run with --download)")
    DATA.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading LoCoMo -> {DATA}")
    with urllib.request.urlopen(URL, timeout=120) as r:
        DATA.write_bytes(r.read())
    return DATA


def _sessions(conv: dict) -> list[tuple[str, list[dict]]]:
    out = []
    for key in sorted((k for k in conv if re.fullmatch(r"session_\d+", str(k))),
                      key=lambda k: int(str(k).split("_")[1])):
        turns = conv.get(key)
        if isinstance(turns, list):
            out.append((str(key), turns))
    return out


def _llm_turn():
    from backend.qqextract import build_llm_turn

    return build_llm_turn(max_tokens=400)


def _ask(llm, prompt: str) -> str:
    async def _go():
        return await llm([{"role": "user", "content": prompt}], [])

    try:
        msg = asyncio.run(_go())
        return str(msg.get("content") or "").strip()
    except Exception as exc:  # noqa: BLE001
        return f"[llm-error {type(exc).__name__}]"


ANSWER_PROMPT = (
    "You answer questions about a long conversation. Use ONLY the context "
    "below. If the answer is not there, reply exactly: unknown. Keep the "
    "answer short (a phrase or one sentence).\n\nContext:\n{ctx}\n\n"
    "Question: {q}\nAnswer:")

JUDGE_PROMPT = (
    "You are a strict grader. Given a question, the gold answer, and a model "
    "answer, reply with EXACTLY one word: CORRECT, PARTIAL, or WRONG.\n"
    "CORRECT = same fact (dates/order matter, wording may differ).\n"
    "PARTIAL = some correct element but incomplete.\n"
    "WRONG = different fact, refusal, or unknown.\n\n"
    "Question: {q}\nGold: {g}\nModel: {m}\nVerdict:")


def run_locomo(args) -> dict:
    data = json.loads(ensure_dataset(args.download).read_text(encoding="utf-8"))
    llm = _llm_turn()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="yhlz_eval_"))
    results: list[dict] = []
    for si, sample in enumerate(data[: max(1, args.conversations)]):
        conv = sample.get("conversation") or {}
        svc = TargetMemoryService(db_path=tmp / f"m{si}.db",
                                  kw_index=KeywordIndex(tmp / f"k{si}.db"))
        # eval ingestion: raw turns only, no adjudication/causal side effects
        svc._auto_adjudicate = lambda item: None  # type: ignore[method-assign]
        svc._auto_link_causal = lambda item: None  # type: ignore[method-assign]
        n_turns = 0
        for sname, turns in _sessions(conv):
            # LoCoMo session timestamps are essential for temporal questions
            stamp = str(conv.get(f"{sname}_date_time") or "").strip()
            for ti, t in enumerate(turns):
                text = str(t.get("text") or "").strip()
                if not text:
                    continue
                spk = str(t.get("speaker") or "?")
                body = f"[{stamp}] {spk}: {text}" if stamp else f"{spk}: {text}"
                item = L2Item(
                    id=f"eval_{si}_{sname}_{ti}",
                    tier="L2", type="fact", importance=5,
                    summary=body[:400], content_hash="",
                    keywords=text[:60], created_at=time.time(),
                    source="eval")
                svc.store_item(item)
                n_turns += 1
        qas = (sample.get("qa") or [])[: max(1, args.questions)]
        for qa in qas:
            q = str(qa.get("question") or "")
            gold = str(qa.get("answer") or "")
            hits = svc.recall(q, limit=10)
            ctx = "\n".join(f"- {h['summary'][:300]}" for h in hits) or "(no hits)"
            pred = _ask(llm, ANSWER_PROMPT.format(ctx=ctx, q=q))
            verdict = _ask(llm, JUDGE_PROMPT.format(q=q, g=gold, m=pred))
            v = verdict.strip().upper().split()[0] if verdict.strip() else "?"
            results.append({"sample": si, "cat": qa.get("category"),
                            "q": q[:80], "pred": pred[:80], "verdict": v,
                            "hits": len(hits)})
            print(f"[{len(results)}] cat={qa.get('category')} {v} | {q[:60]}")
    total = len(results) or 1
    corr = sum(1 for r in results if r["verdict"] == "CORRECT")
    part = sum(1 for r in results if r["verdict"] == "PARTIAL")
    by_cat: dict = {}
    for r in results:
        c = str(r["cat"])
        d = by_cat.setdefault(c, {"n": 0, "correct": 0, "partial": 0})
        d["n"] += 1
        d["correct"] += 1 if r["verdict"] == "CORRECT" else 0
        d["partial"] += 1 if r["verdict"] == "PARTIAL" else 0
    return {"mode": "locomo-B", "n": total, "correct": corr, "partial": part,
            "accuracy": corr / total, "by_cat": by_cat, "results": results}


# ---------------- self scenes (deterministic, no LLM) ----------------
def run_scenes(_args) -> dict:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="yhlz_scenes_"))
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    svc = TargetMemoryService(db_path=tmp / "m.db", kw_index=KeywordIndex(tmp / "k.db"))

    def it(iid, summary, **kw):
        base = dict(tier="L2", type="fact", importance=5, summary=summary,
                    content_hash=iid, keywords=summary[:40],
                    created_at=time.time())
        base.update(kw)
        return L2Item(id=iid, **base)

    # 1) cross-session recall
    svc.store_item(it("s1", "老爹周末打算去修相机", source="老爹"))
    hits = svc.recall("相机")
    check("跨会话回忆", any(h["id"] == "s1" for h in hits))

    # 2) fact update: default = new only, as-of = old
    #    (neutral wording so the M2 auto-supersede does not fire first)
    t0 = time.time()
    old = it("f1", "老爹在A公司上班", source="老爹", valid_at=t0)
    svc.store_item(old)
    new = it("f2", "老爹在B公司上班", source="老爹", valid_at=t0 + 100)
    svc.store_item(new)
    svc.supersede("f1", "f2", when=t0 + 50)
    now_hits = [h["id"] for h in svc.recall("公司")]
    past_hits = [h["id"] for h in svc.recall("公司", as_of=t0 + 25)]
    check("事实更新(默认只见新)", "f2" in now_hits and "f1" not in now_hits,
          str(now_hits))
    check("as-of 时间旅行(旧账可回溯)", "f1" in past_hits, str(past_hits))

    # 3) causal why via rule auto-link
    svc.store_item(it("c2", "机房温度报警持续了十分钟", source="老爹"))
    svc.store_item(it("c1", "因为机房温度报警所以服务器宕机了", source="老爹"))
    why = svc.why("c1")
    check("因果自动连边+why", any(r["relation"] == "cause" for r in why),
          str(why)[:120])

    # 4) A1 external stays speculation + no auto edge
    svc.store_item(it("g1", "群里说显卡降价了", source="群聊"))
    svc.store_item(it("g2", "因为显卡降价所以装机量涨了", source="群聊"))
    st = svc._item_brief("g1")["stance"]
    ext_edges = [e for e in svc.causal_list() if e["dst_id"] == "g2"]
    check("A1外部标speculation", st == "speculation", st)
    check("外部因果不自动激活",
          bool(ext_edges) and all(e["status"] != "active" for e in ext_edges),
          str([e["status"] for e in ext_edges]))

    # 5) voice episode provenance
    eid = svc.add_episode(channel="console", kind="voice", source="老爹",
                          raw_ref="probe.wav", summary="买瓶醋")
    eps = svc.list_episodes(channel="console")
    check("语音episode可回溯", bool(eid) and eps and
          eps[0]["raw_ref"] == "probe.wav")

    passed = sum(1 for c in checks if c["ok"])
    return {"mode": "scenes", "n": len(checks), "correct": passed,
            "partial": 0, "accuracy": passed / max(1, len(checks)),
            "by_cat": {}, "results": checks}


# ---------------- report ----------------
def write_report(res: dict, out: pathlib.Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# 记忆评测基线（{res['mode']}）", "",
             f"- 时间：{time.strftime('%Y-%m-%d %H:%M')}",
             f"- 模式：{res['mode']}"
             + ("（内部基线：DeepSeek answerer + DeepSeek judge，"
                "不可与冻结协议厂商数字直接比较）" if res["mode"] != "scenes"
                else "（确定性检查，无 LLM 判官）"),
             f"- 样本：{res['n']}；正确：{res['correct']}；部分：{res['partial']}；"
             f"准确率：**{res['accuracy']:.1%}**", ""]
    if res["by_cat"]:
        lines.append("| 类别 | 条数 | 正确 | 部分 |")
        lines.append("|---|---|---|---|")
        for cat, d in sorted(res["by_cat"].items()):
            lines.append(f"| {cat} | {d['n']} | {d['correct']} | {d['partial']} |")
        lines.append("")
    lines.append("## 明细（前 30）")
    for r in res["results"][:30]:
        if res["mode"] == "scenes":
            mark = "✅" if r["ok"] else "❌"
            lines.append(f"- {mark} {r['name']} {r['detail']}")
        else:
            lines.append(f"- cat{r['cat']} {r['verdict']} | Q: {r['q']} | "
                         f"A: {r['pred']}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report -> {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    p1 = sub.add_parser("locomo")
    p1.add_argument("--conversations", type=int, default=2)
    p1.add_argument("--questions", type=int, default=15)
    p1.add_argument("--download", action="store_true")
    p1.add_argument("--out", default="")
    p2 = sub.add_parser("scenes")
    p2.add_argument("--out", default="")
    a = ap.parse_args()
    res = run_locomo(a) if a.mode == "locomo" else run_scenes(a)
    out = pathlib.Path(a.out) if a.out else (
        _ROOT / "docs" / "报告" /
        f"记忆评测基线_{time.strftime('%Y-%m-%d')}_{res['mode'].split('-')[0]}.md")
    write_report(res, out)
    print(json.dumps({"mode": res["mode"], "n": res["n"],
                      "correct": res["correct"], "partial": res["partial"],
                      "accuracy": round(res["accuracy"], 4)},
                     ensure_ascii=False))
    return 0 if res["accuracy"] >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
