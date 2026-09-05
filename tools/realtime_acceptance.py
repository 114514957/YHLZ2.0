"""Realtime acceptance (ledger 0153): REAL DeepSeek dialog rounds.

C1: time question -> tool
C2: preference stated -> model triggers memory.save -> approver approves
C3: NEW session asks the preference -> recall hit -> correct answer
B1: belief trajectory on the saved item (recall corroboration, contradiction)
C4: proactive_tick with real model
"""

from __future__ import annotations

import asyncio
import io
import sys

sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ")


def _setup() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


async def main() -> int:
    _setup()
    from backend.env_loader import ensure_env_loaded

    ensure_env_loaded()
    from backend.target_entry import ConversationSession
    from backend.target_scheduler_tools import SAVE_APPROVAL_POLICY

    pref_text = "用户习惯每天七点起床，晚上十一点前睡"

    async def allow(info):
        return True

    # C1 time
    s1 = ConversationSession()
    r1 = await s1.run_turn("现在几点了？")
    c1_ok = any(u["name"] == "system_time" and u["ok"] for u in r1["tool_uses"]) and "2026" in r1["answer"]
    print(f"C1 time: {'PASS' if c1_ok else 'FAIL'} tools={[u['name'] for u in r1['tool_uses']]}")
    print(f"   answer: {r1['answer'][:80]}")

    # C2 preference save (approver grants)
    s2 = ConversationSession(approver=allow)
    r2 = await s2.run_turn(f"帮我记住一个习惯：{pref_text}（请保存到长期记忆）")
    saved = any(u["name"] == "memory_save" and u["ok"] for u in r2["tool_uses"])
    l2_before = s2.memory.health()["l2_items"]
    print(f"C2 save: {'PASS' if saved else 'FAIL'} tools={[u['name'] for u in r2['tool_uses']]} l2={l2_before}")

    # locate the stored item (newest first, full scan)
    import sqlite3

    con = sqlite3.connect(s2.memory.db_path)
    rows = con.execute(
        "SELECT id, summary FROM l2_items "
        "WHERE summary LIKE '%7点%' OR summary LIKE '%七点%' OR summary LIKE '%起床%' "
        "ORDER BY created_at DESC LIMIT 3"
    ).fetchall()
    con.close()
    target_id = rows[0][0] if rows else None
    target = {"id": target_id} if target_id else None
    c2_ok = saved and target is not None
    if target:
        b0 = s2.memory.belief_report(target["id"])
        print(f"   item={target['id']} belief0={b0['belief']} evidence={b0['evidence_count']}")

    # B1 belief trajectory (real recall already corroborated it; then contradict)
    if target:
        b_hit = s2.memory.belief_report(target["id"])
        s2.memory.observe_hit(target["id"], strength=0.5)
        b_hit2 = s2.memory.belief_report(target["id"])
        b_contra = s2.memory.observe_contradiction(target["id"])
        print(f"B1 belief: start={b_hit['belief']} after_hit={b_hit2['belief']} after_contra={b_contra:.4f} "
              f"{'PASS' if b_hit2['belief'] > b_hit['belief'] and b_contra < b_hit2['belief'] else 'FAIL'}")

    # C3 persistence across a NEW session
    s3 = ConversationSession()
    r3 = await s3.run_turn("我一般几点起床睡觉？查一下记忆。")
    c3_ok = ("七点" in r3["answer"] or "7" in r3["answer"]) and ("11" in r3["answer"] or "十一" in r3["answer"] or "23" in r3["answer"])
    print(f"C3 persist: {'PASS' if c3_ok else 'FAIL'}")
    print(f"   answer: {r3['answer'][:120]}")

    # C4 proactive tick
    s4 = ConversationSession()
    r4 = await s4.proactive_tick()
    print(f"C4 proactive: answer_len={len(r4['answer'])} tools={[u['name'] for u in r4['tool_uses']]} "
          f"{'PASS' if r4['answer'].strip() else 'FAIL'}")
    print(f"   answer: {r4['answer'][:120]}")

    passed = sum([c1_ok, c2_ok, c3_ok])
    print(f"\n=== C1-C3: {passed}/3 (all required); C4 informational ===")
    return 0 if passed == 3 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
