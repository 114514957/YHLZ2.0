"""Local CI gate for YH (台账 1097): one command, no network, no writes.

Three checks:
  1. interpreter + deps  — are we in the venv, and do the key packages import?
  2. unit batches        — each batch in its own subprocess (avoids the known
                           import-order pollution between test modules);
  3. smoke (optional)    — stack health via tools/smoke.py --json.

Usage:
    .venv\\Scripts\\python.exe tools\\ci_check.py
    .venv\\Scripts\\python.exe tools\\ci_check.py --smoke

Exit 0 = all green; 1 = at least one check failed.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
TMP = ROOT / "cache" / "tmp"

CORE = [
    "backend.test_target_entry",
    "backend.test_target_schedule",
    "backend.test_target_capability_registry",
    "backend.test_target_orchestrator",
    "backend.test_console_text_routes",
    "backend.test_target_memory",
    "backend.test_qq_behavior",
    "backend.test_bili_tools",
    "backend.test_dev_runner_backend",
    "backend.test_prompt_structure",
    "backend.test_prompt_budget",
    "backend.test_target_prompts",
    "backend.test_session_migration",
    "backend.test_text_memory_inference_gate",
    "backend.test_memory_recall_budget",
    "backend.test_bg_scheduler",
    "backend.test_launcher_daemon_recycle",
]
MEMORY = [
    "backend.test_memory_channel_lifecycle",
    "backend.test_qq_memory_boundaries",
    "backend.test_snapshots",
    "backend.test_memory_semantic_policy",
    "backend.test_memory_summary_scheduler",
    "backend.test_target_access",
    "backend.test_llm_stream",
    "backend.test_memory_index_audit",
]


def check_env() -> list[str]:
    problems: list[str] = []
    if ROOT not in pathlib.Path(sys.executable).resolve().parents:
        problems.append(f"not running the project venv: {sys.executable}")
    code = ("import httpx, numpy, psutil; print(httpx.__version__, numpy.__version__)")
    r = subprocess.run([str(PY), "-B", "-c", code], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        problems.append("key deps import failed: " + (r.stderr or "").strip()[:160])
    else:
        print(f"  deps ok: {r.stdout.strip()}")
    return problems


def run_batch(name: str, modules: list[str]) -> bool:
    """Run one batch; retry once — a single flaky ERROR should not fail the gate.

    TEMP/TMP point into cache/tmp so tempfile.mkdtemp() never lands in the repo
    root (ledger 1103 structure rule).
    """
    TMP.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["TEMP"] = env["TMP"] = str(TMP)
    for attempt in (1, 2):
        print(f"  batch {name}: {len(modules)} modules"
              f"{' (retry)' if attempt == 2 else ''} ...", flush=True)
        r = subprocess.run([str(PY), "-B", "-m", "unittest", *modules],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
        tail = [ln for ln in (r.stderr or r.stdout or "").splitlines()
                if ln.startswith(("Ran ", "OK", "FAILED"))]
        print("    " + " | ".join(tail[-2:]) if tail else "    (no summary)")
        if r.returncode == 0:
            return True
        fails = [ln for ln in (r.stderr or "").splitlines()
                 if ln.startswith(("FAIL:", "ERROR:"))]
        for ln in fails[:8]:
            print("    " + ln)
        if attempt == 2:
            return False
    return False


def check_structure() -> bool:
    print("  structure lint ...", flush=True)
    r = subprocess.run([str(PY), "-B", str(ROOT / "tools" / "structure_lint.py"), "--json"],
                       cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    try:
        rep = json.loads(r.stdout)
    except Exception:
        print("    structure: unreadable output")
        return False
    bad = rep.get("violations") or []
    print(f"    structure: {'clean' if not bad else str(len(bad)) + ' violation(s)'}")
    for v in bad[:8]:
        print(f"      [{v.get('kind')}] {v.get('name')} -> {v.get('hint')}")
    return not bad


def check_smoke() -> bool:
    r = subprocess.run([str(PY), str(ROOT / "tools" / "smoke.py"), "--json"],
                       cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    try:
        data = json.loads(r.stdout)
    except Exception:
        print("  smoke: unreadable output")
        return False
    hard = [c for c in data.get("checks", []) if c.get("level") == "FAIL"]
    print(f"  smoke: fail={data.get('fail')} warn={data.get('warn')}")
    for c in hard:
        print(f"    FAIL {c.get('name')}: {c.get('detail')}")
    return not hard


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--smoke", action="store_true", help="also check the live stack")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("[1/4] environment")
    problems = check_env()
    print("[2/4] structure")
    ok_struct = check_structure()
    print("[3/4] unit batches")
    ok_core = run_batch("core", CORE)
    ok_mem = run_batch("memory", MEMORY)
    ok_smoke = True
    if args.smoke:
        print("[4/4] smoke")
        ok_smoke = check_smoke()
    else:
        print("[4/4] smoke skipped (--smoke to enable)")
    ok = not problems and ok_struct and ok_core and ok_mem and ok_smoke
    for p in problems:
        print("  ENV: " + p)
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
