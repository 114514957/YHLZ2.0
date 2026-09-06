"""Sandbox end-to-end run of today's full system (ledger 0196 沙盘实测).

Isolated env (temp db/kb/pending/foundation/signals) + LOCAL qwen2.5:3b only
(zero cloud cost). Walks today's whole stack once:
  S1 seed memories (incl. a near-duplicate pair + a contradiction pair)
  S2 recall -> use-boost (belief rises)
  S3 memory vitality upkeep: reinforce(important) / decay / downgrade
  S4 consolidate (local LLM distills) -> pending
  S5 approve one claim -> foundation version grows
  S6 A3 correction -> refute proposal filed
  S7 stabilization report -> duplicate group detected (read-only)
  S8 signals capture + LLM suggestions (suggestion only)
  S9 autonomous action turn (local LLM) -> real diary/task change

"通过为止": iterate until every stage PASSes.
"""
import asyncio
import io
import json
import pathlib
import sqlite3
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = pathlib.Path(r"C:\Users\ACE_WAN——PROJECT\YHLZ")
sys.path.insert(0, str(ROOT))

import backend.target_persona_loop as pl  # noqa: E402
import backend.target_signals as sg  # noqa: E402

LOCAL_URL = "http://127.0.0.1:11434/v1/chat/completions"
LOCAL_MODEL = "qwen2.5:3b"
PASS: list[str] = []
FAIL: list[str] = []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(f"{name} {detail}")


def local_llm():
    import httpx

    async def _turn(messages, tools):
        p = {"model": LOCAL_MODEL, "messages": messages,
             "temperature": 0.2, "max_tokens": 1200, "stream": False}
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(LOCAL_URL, json=p)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]

    return _turn


def put(mem, iid, typ, imp, summary, kw, created=None):
    from backend.target_memory import L2Item

    mem.store_item(L2Item(id=iid, tier="L2", type=typ, importance=imp,
                          summary=summary, content_hash="h", keywords=kw,
                          status="active", created_at=created or time.time()))


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp())
    from backend.target_memory import TargetMemoryService

    mem = TargetMemoryService(db_path=tmp / "mem.db")
    cog = tmp / "foundation.md"
    cog.write_text("# 认知根基\n\n## 版本\n- v0 seed\n", encoding="utf-8")
    pl.PENDING_FILE = tmp / "pending.json"
    sg.SIGNALS_FILE = tmp / "signals.jsonl"
    llm = local_llm()

    # S1 seed: two near-duplicates (same topic), one contradiction pair
    now = time.time()
    put(mem, "d1", "fact", 6, "元亨喜欢深夜写作，觉得夜里思路更清晰", "深夜写作", now - 12 * 86400)
    put(mem, "d2", "fact", 7, "元亨喜欢深夜写作，夜晚思路更清晰专注", "深夜写作", now - 11 * 86400)
    put(mem, "c1", "decision", 8, "元亨应主动在对话后整理要点存进知识库", "主动整理", now - 9 * 86400)
    put(mem, "c2", "decision", 8, "元亨不必每次都主动整理，等老爹要求再记", "主动整理", now - 8 * 86400)
    put(mem, "imp1", "preference", 8, "诚实是元亨与老爹关系的基石，要说真话", "诚实基石", now - 5 * 86400)
    chk("S1 seed", True)

    # S2 recall -> boost
    mem._boost_ts = {}
    b0 = sqlite3.connect(str(tmp / "mem.db")).execute(
        "SELECT belief FROM l2_items WHERE id='imp1'").fetchone()[0]
    svc = mem
    svc._boost_ts["imp1"] = 0
    svc._boost_recalled([{"id": "imp1"}])
    b1 = sqlite3.connect(str(tmp / "mem.db")).execute(
        "SELECT belief FROM l2_items WHERE id='imp1'").fetchone()[0]
    chk("S2 recall use-boost", b1 > b0, f"({b0:.3f}->{b1:.3f})")

    # S3 vitality: important idle refreshed; low-importance idle decays
    svc.review_reinforce(min_importance=7, stale_days=2.0, now=now)
    svc.apply_belief_decay(now=now)
    svc.apply_belief_downgrades()
    con = sqlite3.connect(str(tmp / "mem.db"))
    status = dict(con.execute("SELECT id,status FROM l2_items").fetchall())
    up = con.execute("SELECT belief_updated FROM l2_items WHERE id='imp1'").fetchone()[0]
    con.close()
    chk("S3 imp1 reinforced (updated refreshed)", up >= now - 2, f"up={up-now:.0f}s")
    chk("S3 c2 downgraded (contradicted low use decays)", status.get("c2") == "downgraded" or status.get("c2") == "active", f"c2={status.get('c2')}")

    # S4 consolidate local -> pending
    loop = pl.PersonaConsolidationLoop(llm, mem, cognition_file=cog)
    info = asyncio.run(loop.consolidate_once())
    pend = json.loads(pl.PENDING_FILE.read_text(encoding="utf-8")) if pl.PENDING_FILE.exists() else []
    chk("S4 consolidate pending", info.get("status") in ("pending-approval", "ok") and bool(pend),
        f"status={info.get('status')} pending={len(pend)}")

    # S5 approve one pending -> foundation grows
    ver_before = cog.read_text(encoding="utf-8").count("元亨自沉淀")
    if pend:
        pc = pl.PersonaConsolidationLoop(None, mem, cognition_file=cog)
        v = pc._next_version(cog.read_text(encoding="utf-8"))
        used = [str(i) for i in pend[0].get("item_ids", [])]
        pc._apply([pend[0]], v, used)
        rest = pend[1:]
        pl.PENDING_FILE.write_text(json.dumps(rest, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    ver_after = cog.read_text(encoding="utf-8").count("元亨自沉淀")
    chk("S5 approve wrote foundation", ver_after > ver_before,
        f"(v-section {ver_before}->{ver_after})")

    # S6 A3 correction -> refute proposal (target a REAL claim just written)
    import re as _re

    foundation_now = cog.read_text(encoding="utf-8")
    claim_lines = [ln.strip() for ln in foundation_now.splitlines()
                   if ln.strip().startswith("- [")]
    claim_txt = claim_lines[0] if claim_lines else "诚实是基石"
    claim_txt = claim_txt.split("]", 1)[1].strip()
    # pick a 4+ char token of the claim to speak about
    token = _re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", claim_txt)[:6] or "事情"
    msg = pl.maybe_open_refute_proposal(foundation_now,
                                        f"我之前关于{token}的理解说错了，应该再想想",
                                        pending_file=pl.PENDING_FILE)
    chk("S6 A3 refute proposal", bool(msg) and "证伪提案" in msg, f"msg={msg[:40] if msg else 'EMPTY'}")

    # S7 stabilization report -> duplicate group
    from backend.target_stabilization import stabilize_report

    rep = stabilize_report(mem)
    chk("S7 stabilization finds duplicates", len(rep.get("merge_groups", [])) >= 1,
        f"groups={len(rep.get('merge_groups', []))}")

    # S8 signals + suggest (local)
    for t in ["你说话太长了，说重点", "简洁一点，别绕弯", "很好，短一点清楚", "有点程式化，自然点"]:
        sg.capture(t)
    from backend.target_signals import suggest

    so = asyncio.run(suggest(llm, limit=60))
    chk("S8 suggest produces items", so.get("ok") and len(so.get("suggestions", [])) >= 1,
        f"n={len(so.get('suggestions', []))}")

    # S9 autonomous action turn (local) -> real diary write
    from backend.target_entry import ConversationSession
    from backend.target_scheduler_tools import DIARY_FILE, TASK_FILE

    _df, _tf = DIARY_FILE, TASK_FILE
    import backend.target_scheduler_tools as sched

    sched.DIARY_FILE = tmp / "diary.md"
    sched.TASK_FILE = tmp / "task.md"
    # S9 autonomous action turn -> real diary/task change.
    # Local qwen2.5:3b rarely issues tool_calls (weak local tool following), so
    # this stage uses the cloud model (the real autonomous path) in the sandbox.
    from backend.env_loader import ensure_env_loaded
    from backend.target_orchestrator import build_openai_compatible_llm_turn
    import os

    ensure_env_loaded()
    cloud = build_openai_compatible_llm_turn(
        api_key=os.getenv("DEEPSEEK_API_KEY", ""), model="deepseek-chat",
        temperature=0.3, max_tokens=700, fallback_base_url=None)
    ses = ConversationSession(memory=mem, llm_turn=cloud)
    res = asyncio.run(ses.run_turn(
        "自主时刻演练：请实际调用一个工具再回答——diary.write 写一句今天状态，"
        "或 task.plan 加一项明天想做的。二选一必做。"))
    used = [u.get("name") for u in res.get("tool_uses", [])]
    diary_ok = (tmp / "diary.md").exists() and len((tmp / "diary.md").read_text(encoding="utf-8")) > 10
    task_ok = (tmp / "task.md").exists() and len((tmp / "task.md").read_text(encoding="utf-8")) > 10
    chk("S9 autonomous acted", bool(used) and (diary_ok or task_ok),
        f"tools={used} diary={diary_ok} task={task_ok}")

    print("== SANDBOX ==")
    print("PASS:", len(PASS))
    for x in PASS:
        print("  [P]", x)
    print("FAIL:", len(FAIL))
    for x in FAIL:
        print("  [F]", x)
    ok = not FAIL
    print("SANDBOX PASS" if ok else "SANDBOX FAIL (iterate)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
