"""Chain guard（台账 1105）：一条链只能有一个消费者，不许新旧一起跑。

检查项（只读，不改任何东西）：
1. 进程角色：daemon / watchdog / llama / lz_link / mcp 的“逻辑实例数”
   （venv 壳+解释器算一对，不是两个实例）；桥/旧链是否残留在跑；
2. 端口：8081 / 8321 / 8348 各自最多一个监听者；
3. 自启：Startup 里同时生效的 YH/元亨/利贞 入口 ≤1；计划任务里不许有启用的旧守护；
4. 自主：默认必须关（fail-closed），并报告当前是 flag 关还是 env 未授权。

用法：
    python tools/chain_guard.py            # 人读
    python tools/chain_guard.py --json
退出码：0 = 干净；1 = 有双链/残留/自启重叠。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import socket
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

ROLE_PATTERNS = [
    ("daemon", ("target_daemon",), 2),
    ("watchdog", ("yhlz_watchdog",), 2),
    ("llama", ("llama-server",), 1),
    ("lz_link", ("lz_link.py",), 2),
    ("qq_bridge", ("qq_bridge_service",), 2),
    ("legacy_qq", ("qq_bot.py", "napcat_watch.py"), 0),
    ("workbench", ("llm_workbench",), 2),
]


def _procs():
    if psutil is None:
        return []
    out = []
    for p in psutil.process_iter(["pid", "ppid", "name", "cmdline"]):
        try:
            cmd = " ".join(str(x) for x in (p.info.get("cmdline") or []))
            out.append({"pid": int(p.info["pid"]), "ppid": int(p.info["ppid"] or 0),
                        "name": str(p.info.get("name") or ""), "cmd": cmd})
        except Exception:
            continue
    return out


def _listening(port: int) -> list[int]:
    pids = []
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == "LISTEN" and conn.laddr and conn.laddr.port == port:
                pids.append(int(conn.pid or 0))
    except Exception:
        pass
    return sorted(set(p for p in pids if p))


def _startup_active() -> list[str]:
    folder = pathlib.Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / \
        "Start Menu" / "Programs" / "Startup"
    out = []
    if not folder.exists():
        return out
    for p in folder.iterdir():
        if p.suffix.lower() == ".disabled":
            continue
        if any(k in p.name for k in ("YH", "元亨", "利贞", "YHLZ")):
            out.append(p.name)
    return out


def _scheduled_enabled() -> list[str]:
    try:
        r = subprocess.run(["schtasks", "/query", "/fo", "csv", "/nh"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=20)
    except Exception:
        return []
    bad = []
    for line in (r.stdout or "").splitlines():
        if not any(k in line for k in ("YHLZ", "LZLink", "元亨", "利贞")):
            continue
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 3 and "Disabled" not in parts[2]:
            bad.append(parts[0])
    return bad


def audit() -> dict:
    procs = _procs()
    problems: list[dict] = []
    roles = {}
    for role, needles, pair_max in ROLE_PATTERNS:
        hit = [p for p in procs if any(n in p["cmd"] for n in needles)]
        roles[role] = [p["pid"] for p in hit]
        # logical roots: a hit whose parent is not also a hit
        ids = {p["pid"] for p in hit}
        roots = [p for p in hit if p["ppid"] not in ids]
        max_roots = (pair_max + 1) // 2
        if len(roots) > max_roots:
            problems.append({"kind": "duplicate-chain", "role": role,
                             "detail": f"{len(roots)} 个逻辑实例 {[p['pid'] for p in roots]}"})
        if role == "legacy_qq" and hit:
            problems.append({"kind": "legacy-chain", "role": role,
                             "detail": f"旧 QQ 链仍在跑: {[p['pid'] for p in hit]}"})

    ports = {}
    for port in (8081, 8321, 8348):
        pids = _listening(port)
        ports[port] = pids
        if len(pids) > 1:
            problems.append({"kind": "duplicate-listener", "port": port,
                             "detail": f"{len(pids)} 个 pid 在听"})

    startup = _startup_active()
    if len(startup) > 1:
        problems.append({"kind": "startup-overlap", "detail": startup})

    sched = _scheduled_enabled()
    if sched:
        problems.append({"kind": "scheduled-old-guard", "detail": sched})

    # autonomy: report only; the gate itself is fail-closed in code
    try:
        from backend.target_daemon import AUTONOMY_FLAG, autonomy_disabled
        autonomy = {
            "disabled": bool(autonomy_disabled()),
            "flag": AUTONOMY_FLAG.exists(),
            "env_enable": os.getenv("YHLZ_AUTONOMY_ENABLE", ""),
        }
        if not autonomy["disabled"]:
            problems.append({"kind": "autonomy-on", "detail": autonomy})
    except Exception as exc:  # noqa: BLE001
        autonomy = {"error": type(exc).__name__}

    return {"ok": not problems, "roles": roles, "ports": ports,
            "startup": startup, "scheduled": sched, "autonomy": autonomy,
            "problems": problems}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = audit()
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print("roles:")
        for role, pids in rep["roles"].items():
            if pids:
                print(f"  {role}: {pids}")
        print(f"ports: {rep['ports']}")
        print(f"startup: {rep['startup']}")
        print(f"scheduled(enabled): {rep['scheduled'] or '-'}")
        print(f"autonomy: {rep['autonomy']}")
        if rep["ok"]:
            print("链检查：干净（无双链/无旧链残留/无自启重叠）")
        else:
            print(f"链检查：{len(rep['problems'])} 个问题")
            for p in rep["problems"]:
                print(f"  [{p['kind']}] {p.get('role') or p.get('port') or ''} {p.get('detail')}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
