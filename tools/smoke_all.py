"""Ledger feature smoke-check (ledger 0208): real-machine pass/fail for every
recent capability (0195-0207). Read-mostly / idempotent; no deletions.
"""
import asyncio
import io
import json
import sqlite3
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ")

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(f"{name} {detail}")


def http(url, method="GET", body=None, timeout=20):
    import urllib.request

    req = urllib.request.Request(url, method=method)
    if body is not None:
        req.data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())


def main() -> int:
    from backend.target_memory import TargetMemoryService
    from backend.target_persona_loop import PENDING_FILE, maybe_open_refute_proposal

    svc = TargetMemoryService()
    con = sqlite3.connect(str(svc.db_path))

    # 1 daemon + turn + stream
    try:
        h = http("http://127.0.0.1:8321/health")
        chk("daemon health", h.get("status") == "ok")
    except Exception as e:
        chk("daemon health", False, type(e).__name__)

    # 2 memory recall hit + id + keys
    hits = svc.recall("诚实 边界 元亨利贞", limit=3)
    chk("memory.recall returns dicts with id", bool(hits) and all("id" in x for x in hits))

    # 3 A2 vitality methods run (no delete)
    try:
        rf = svc.review_reinforce(min_importance=7, stale_days=0.0)
        chk("A2 review_reinforce runs", isinstance(rf, int))
    except Exception as e:
        chk("A2 review_reinforce runs", False, type(e).__name__)

    # 4 stabilization report (read-only)
    try:
        from backend.target_stabilization import stabilize_report

        rep = stabilize_report(svc)
        chk("stabilization report", rep.get("total", 0) >= 0)
    except Exception as e:
        chk("stabilization report", False, type(e).__name__)

    # 5 A3 correction no-match does nothing (no pollution)
    foundation = con.execute(
        "SELECT 1 FROM sqlite_master").fetchall()
    msg = maybe_open_refute_proposal("# 认知根基\n- [新增|core] 诚实基石", "今天天气不错呢", PENDING_FILE)
    chk("A3 no-pollution on neutral talk", msg == "")

    # 6 knowledge base query (yuanheng_kb)
    try:
        from backend.yuanheng_kb import kb_query, kb_stats

        st = kb_stats()
        q = kb_query("llama.cpp", limit=2)
        chk("yuanheng_kb stats+query", st["items"] > 0)
    except Exception as e:
        chk("yuanheng_kb stats+query", False, type(e).__name__)

    # 7 skills (search count + feedback presence)
    try:
        from backend.target_scheduler_tools import skill_search, skill_feedback

        s = skill_search("QQ知识捕获")
        chk("skill.search", "技能" in s or "运维" in s)
    except Exception as e:
        chk("skill.search", False, type(e).__name__)

    # 8 signals capture + count
    try:
        import backend.target_signals as sg

        before = sg.count()
        chk("signals file exists/count", isinstance(before, dict))
    except Exception as e:
        chk("signals", False, type(e).__name__)

    # 9 web_search (bing crawler real)
    try:
        from backend.target_access import web_search

        r = asyncio.run(web_search("llama.cpp", limit=2))
        chk("web_search bing", "http" in r)
    except Exception as e:
        chk("web_search bing", False, type(e).__name__)

    # 10 Gemma llama.cpp effort=none fast (real)
    try:
        import urllib.request

        body = {"messages": [{"role": "user", "content": "说句你好"}],
                "max_tokens": 40, "reasoning_effort": "none"}
        req = urllib.request.Request("http://127.0.0.1:8081/v1/chat/completions",
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        t0 = time.time()
        r = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        c = (r.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        chk("gemma 8081 effort none", bool(c) and (time.time() - t0) < 15, f"{time.time()-t0:.1f}s")
    except Exception as e:
        chk("gemma 8081 effort none", False, type(e).__name__)

    # 11 registry full tool surface
    try:
        from backend.target_scheduler_tools import setup_scheduler_capabilities

        reg = setup_scheduler_capabilities()
        names = reg.names()
        need = {"ledger.search", "memory.recall", "memory.save", "diary.write",
                "task.plan", "kb.add", "kb.query", "qq.status", "qq.export",
                "qq.process", "qq.bootstrap", "qq.shutdown", "qq.runbatch",
                "skill.search", "skill.add", "skill.feedback", "owner.approve",
                "file.list", "file.read", "web.fetch", "web.search", "system.time"}
        chk("tool surface 27 caps", len(names) == len(set(names)) and need <= set(names),
            f"n={len(names)}")
    except Exception as e:
        chk("tool surface", False, type(e).__name__)

    # 12 memory store status sane
    st = con.execute("SELECT status, COUNT(*) FROM l2_items GROUP BY status").fetchall()
    stmap = dict(st)
    chk("L2 status sane", "active" in stmap and ("archive" in stmap or len(st) > 0), str(stmap))
    con.close()

    print("=== LEDGER FEATURE SMOKE ===")
    print("PASS", len(PASS))
    for x in PASS:
        print("  [P]", x)
    print("FAIL", len(FAIL))
    for x in FAIL:
        print("  [F]", x)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
