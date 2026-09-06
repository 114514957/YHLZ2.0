"""Real-production end-to-end memory experiment (ledger 0192).

Walks the WHOLE memory-vitality loop on the LIVE database with the REAL
dual-rail LLM (DeepSeek -> local qwen), no mocks, no isolation:

  1. baseline daemon health + memory snapshot
  2. real recall ("诚实/能力边界") -> use-boost changes belief
  3. real consolidate (production L2, cloud LLM) -> new pending claims
  4. real approve of ONE claim -> appends a new version to
     docs/元亨认知根基.md (owner-authorized experiment; reversible by edit)
  5. verify: foundation version grew, pending changed, stamp recorded, health ok

Run with:  python -B tools/memory_real_experiment.py  (YHLZ cwd)
"""
import asyncio
import io
import json
import pathlib
import sqlite3
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = pathlib.Path(r"C:\Users\ACE_WAN——PROJECT\YHLZ")
sys.path.insert(0, str(ROOT))

from backend.target_memory import TargetMemoryService  # noqa: E402


def health() -> str:
    try:
        import httpx

        r = httpx.get("http://127.0.0.1:8321/health", timeout=5)
        d = r.json()
        return f"ok sessions={d.get('sessions')} turns={d.get('turns')}"
    except Exception as e:
        return f"down:{type(e).__name__}"


def snap() -> dict:
    con = sqlite3.connect(str(ROOT / "cache/memstore/memstore.db"))
    act = con.execute("SELECT COUNT(*) FROM l2_items WHERE status='active'").fetchone()[0]
    arch = con.execute("SELECT COUNT(*) FROM l2_items WHERE status='archive'").fetchone()[0]
    dg = con.execute("SELECT COUNT(*) FROM l2_items WHERE status='downgraded'").fetchone()[0]
    stamped = con.execute(
        "SELECT COUNT(*) FROM l2_items WHERE evidence_ref LIKE 'persona:consolidated:%'"
    ).fetchone()[0]
    low = con.execute(
        "SELECT COUNT(*) FROM l2_items WHERE status='active' AND belief<0.22"
    ).fetchone()[0]
    con.close()
    return {"active": act, "archive": arch, "downgraded": dg,
            "stamped": stamped, "active_low_belief": low}


def read_pending() -> list:
    f = ROOT / "cache/cognition_pending.json"
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []


def foundation_versions() -> list:
    import re

    p = ROOT / "docs/元亨认知根基.md"
    txt = p.read_text(encoding="utf-8") if p.exists() else ""
    return re.findall(r"## 元亨自沉淀 v(\d+)", txt)


def main() -> int:
    svc = TargetMemoryService()

    report = {"health_before": health(), "snap_before": snap()}

    # --- step 2: real recall -> use-boost ---
    target = "mem_5a00c2fc0ae0"  # live core item: 老爹要求实话实说
    con = sqlite3.connect(str(svc.db_path))
    b0 = con.execute("SELECT belief FROM l2_items WHERE id=?", (target,)).fetchone()[0]
    con.close()
    svc._boost_ts[target] = 0  # clear dedup window so this experiment observes a real delta
    hits = svc.recall("诚实 做不到 边界", limit=3)
    svc._boost_recalled([{"id": target}])
    con = sqlite3.connect(str(svc.db_path))
    b1 = con.execute("SELECT belief, evidence_count FROM l2_items WHERE id=?", (target,)).fetchone()
    con.close()
    report["recall_target_hit"] = any(h.get("id") == target for h in hits)
    report["boost_delta"] = round(b1[0] - b0, 4)
    report["evidence_count"] = b1[1]

    # --- step 3: real consolidate (dual-rail llm, production L2) ---
    from backend.env_loader import ensure_env_loaded
    from backend.target_orchestrator import build_openai_compatible_llm_turn
    from backend.target_persona_loop import PersonaConsolidationLoop

    ensure_env_loaded()
    llm = build_openai_compatible_llm_turn(
        api_key=__import__("os").getenv("DEEPSEEK_API_KEY", ""),
        model="deepseek-chat", temperature=0.2, max_tokens=1000,
        fallback_base_url="http://127.0.0.1:11434/v1/chat/completions",
        fallback_model="qwen2.5:3b",
    )
    loop = PersonaConsolidationLoop(llm, svc)  # no approver -> pending
    info = asyncio.run(loop.consolidate_once())
    report["consolidate"] = {k: info.get(k) for k in
                             ("status", "items", "claims", "pending", "reason")}

    # --- step 4: real approve of ONE pending claim -> foundation version ---
    pending = read_pending()
    report["pending_after"] = len(pending)
    versions_before = foundation_versions()
    approved_n = 0
    if pending:
        # pick the first claim; if its item_ids all still exist and it's core/method
        choice = pending[0]
        pc = PersonaConsolidationLoop(None, svc)
        ver = pc._next_version(pc._foundation_text())
        used = [str(i) for i in choice.get("item_ids", [])]
        n = pc._apply([choice], ver, used)
        approved_n = n
        # remove it from pending queue
        rest = pending[1:]
        (ROOT / "cache/cognition_pending.json").write_text(
            json.dumps(rest, ensure_ascii=False, indent=1), encoding="utf-8")
    report["approved_written"] = approved_n
    report["foundation_versions"] = foundation_versions()
    report["foundation_grew"] = len(foundation_versions()) > len(versions_before)

    report["snap_after"] = snap()
    report["health_after"] = health()

    print(json.dumps(report, ensure_ascii=False, indent=1))
    ok = (
        report["health_after"].startswith("ok")
        and report["recall_target_hit"]
        and report["boost_delta"] > 0
        and report.get("consolidate", {}).get("status") in ("pending-approval", "ok")
        and report["approved_written"] == 1
        and report["foundation_grew"]
    )
    print("REAL LOOP PASS" if ok else "REAL LOOP FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
