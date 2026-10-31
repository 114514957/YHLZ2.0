"""DEPRECATED (0831) — 旧 Full 派单链，已从所有 live 入口摘除。

历史：master QQ -> qq_bot `#dev` -> DevRunner.start(task) -> harness 网关
-> 提问/答复 -> 汇报；`#y` 后在新会话里 `git add -A` 提交（**主仓库全量**）。

0831 起派单统一到 Lite 任务库：`tools/qq_dev_runner.py` + `backend/qq_dev_jobs.py`
（单飞、worktree 隔离、按 job 文件清单提交、版本化回报）。工作台 /talk、/turn、
语音 [[dev:]]、QQ 桥都走它；本模块只保留给历史测试/考古，`main()` 已拒绝执行。

Executor (ledger 0797): harness only.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

_TOOLS = pathlib.Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import dev_contract as dc  # noqa: E402
import harness_gateway as gw  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE = _ROOT / "cache" / "dev" / "state.json"
LOG = _ROOT / "cache" / "dev" / "opencode.log"
MODEL = os.getenv("YHLZ_DEV_MODEL", "deepseek/deepseek-v4-flash")
AGENT = os.getenv("YHLZ_DEV_AGENT", "yhlz-dev")
TIMEOUT = float(os.getenv("YHLZ_DEV_TIMEOUT", "1800"))
# v1.1 (ledger 0446) dual track → v1.2 (ledger 0797) harness only:
# "dsh" is the sole backend, executed by the resident gateway
# (tools/dsh_worker.py). Workspace is overridable so evaluation can run in a
# sandbox without touching the live repo.
WORKDIR = pathlib.Path(os.getenv("YHLZ_DEV_WORKDIR", str(_ROOT))).resolve()
DSH_WORKER_URL = os.getenv("YHLZ_DSH_WORKER", "http://127.0.0.1:8347")
DSH_PY = pathlib.Path(os.getenv(
    "YHLZ_DSH_PYTHON", str(_ROOT / "venv-dsh" / "Scripts" / "python.exe")))
# Retired A1 gray switch (ledger 0450): kept as a path so old tests/tools that
# reference it still import; nothing reads or writes it any more.
BACKEND_FILE = _ROOT / "cache" / "dev" / "backend.txt"
HARNESS_BACKEND = "dsh"
RETIRED_BACKENDS = ("opencode",)


def _backend() -> str:
    """Harness-only (ledger 0797): opencode 退役，历史开关不再影响行为。"""
    return HARNESS_BACKEND


def set_backend(name: str) -> str:
    """Retired switch: reports the fixed backend instead of changing it."""
    b = str(name or "").strip().lower()
    if b in RETIRED_BACKENDS:
        return ("[利贞] opencode 后端已退役（ledger 0797）：利贞现在只跑 harness，"
                "无需切换。")
    if b and b != HARNESS_BACKEND:
        return f"用法：#backend（只读）——利贞固定跑 harness，当前：{_backend()}"
    return f"[利贞] 后端固定 harness（{_backend()}），opencode 已退役。"


def backend_status() -> str:
    return "[利贞] 当前后端：harness（dsh）——唯一后端；opencode 已退役（#backend 只读）"


def _post_worker(path: str, obj: dict, timeout: float = 30.0) -> dict:
    return gw.post(path, obj, url=DSH_WORKER_URL, timeout=timeout)


def _worker_healthy(timeout: float = 2.0) -> bool:
    return gw.healthy(url=DSH_WORKER_URL, timeout=timeout)


def _ensure_worker(wait_s: float = 60.0) -> bool:
    """Spawn the dsh worker (venv-dsh) if it is not listening yet."""
    return gw.ensure(url=DSH_WORKER_URL, py=DSH_PY, workdir=str(WORKDIR),
                     wait_s=wait_s)


# Prompt contract lives in tools/dev_contract.py (shared with the Lite worker
# and the harness gateway); the names stay importable from here.
START_PROMPT = dc.START_PROMPT
ANSWER_PROMPT = dc.ANSWER_PROMPT


def _opencode_exe() -> str:
    """Retired (ledger 0797): opencode executor kept one window, unused."""
    cand = shutil.which("opencode")
    if cand:
        p = pathlib.Path(cand)
        exe = p.parent / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
        if exe.exists():
            return str(exe)
        if p.suffix.lower() == ".exe":
            return str(p)
    for c in (
        pathlib.Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules"
        / "opencode-ai" / "bin" / "opencode.exe",
        pathlib.Path(os.environ.get("ProgramFiles", "")) / "nodejs"
        / "node_modules" / "opencode-ai" / "bin" / "opencode.exe",
    ):
        if c.exists():
            return str(c)
    raise FileNotFoundError("找不到利贞(opencode)可执行文件（npm i -g opencode-ai）")


def _run(prompt: str, session: str | None, timeout: float) -> dict:
    """Retired (ledger 0797) opencode headless runner; no live call site."""
    cmd = [_opencode_exe(), "run", prompt, "-m", MODEL,
           "--agent", AGENT, "--dir", str(WORKDIR), "--format", "json"]
    if session:
        cmd += ["--session", session]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    texts: list[str] = []
    sid = session or ""
    err_tail = ""
    logf = LOG.open("a", encoding="utf-8")
    logf.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} "
               f"session={session or '-'} ===\n{prompt}\n")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(WORKDIR), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:  # noqa: BLE001
        return {"text": "", "session": sid, "ok": False,
                "error": f"{type(exc).__name__}: {exc}"}
    start = time.time()
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if time.time() - start > timeout:
                proc.kill()
                return {"text": "".join(texts), "session": sid, "ok": False,
                        "error": f"超时 {timeout:.0f}s"}
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("sessionID"):
                sid = ev["sessionID"]
            if ev.get("type") == "text":
                t = (ev.get("part") or {}).get("text", "")
                if t:
                    texts.append(t)
            elif ev.get("type") == "error":
                err_tail = json.dumps(ev.get("error", {}), ensure_ascii=False)[:300]
        proc.wait(timeout=30)
    except Exception as exc:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:
            pass
        err_tail = err_tail or f"{type(exc).__name__}: {exc}"
    finally:
        logf.write(f"--- done sid={sid} ---\n")
        logf.close()
    text = "".join(texts).strip()
    ok = bool(text) and not err_tail
    return {"text": text, "session": sid, "ok": ok,
            "error": "" if ok else (err_tail or "无输出")}


def _load() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"status": "idle", "session": "", "task": "", "text": ""}


def _save(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                     encoding="utf-8")


def _classify(text: str) -> str:
    """Kept for callers/tests; the contract lives in tools/dev_contract.py."""
    return dc.classify(text)


def start(task: str) -> dict:
    """Start one dev task on the harness gateway (harness is the only backend)."""
    if not _ensure_worker():
        return {"status": "error", "session": "", "task": task,
                "text": "harness 网关不可用（venv-dsh 缺失或启动失败）"}
    try:
        res = _post_worker("/start", {"task": task})
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "session": "", "task": task,
                "text": f"harness 网关调用失败：{type(exc).__name__}"}
    if not res.get("ok"):
        return {"status": "error", "session": "", "task": task,
                "text": str(res.get("error") or "worker rejected")}
    out = _load()
    out["backend"] = HARNESS_BACKEND
    return out


def answer(text: str) -> dict:
    """Answer the pending harness session (harness is the only backend)."""
    if not _ensure_worker():
        return {"status": "error", "text": "harness 网关不可用",
                "session": ""}
    try:
        res = _post_worker("/answer", {"text": text})
    except Exception as exc:  # noqa: BLE001
        return {"status": "error",
                "text": f"harness 网关调用失败：{type(exc).__name__}",
                "session": ""}
    if not res.get("ok"):
        return {"status": "error", "text": str(res.get("error") or ""),
                "session": ""}
    return _load()


def commit(message: str) -> dict:
    def git(*a: str) -> str:
        p = subprocess.run(["git", *a], cwd=str(WORKDIR), capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        return (p.stdout or "") + (p.stderr or "")

    out = git("add", "-A")
    out += git("commit", "-m", message)
    d = _load()
    d["status"] = "idle"
    d["text"] = out.strip()
    _save(d)
    return d


def push() -> dict:
    p = subprocess.run(["git", "push", "origin", "HEAD"], cwd=str(WORKDIR),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return {"text": ((p.stdout or "") + (p.stderr or "")).strip()}


def main() -> int:
    import sys

    print("[dev_runner] 已退役（ledger 0831）：派单统一走 Lite 任务库。\n"
          "  状态/提交：tools/qq_dev_runner.py（QQ 桥、工作台、语音共用）\n"
          "  本命令不再派单、不再提交（避免 git add -A 卷入主仓在途改动）。",
          flush=True)
    return 2


def _legacy_main() -> int:  # 历史实现，不再从命令行可达
    ap = argparse.ArgumentParser()
    ap.add_argument("--task")
    ap.add_argument("--answer")
    ap.add_argument("--commit")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        print(json.dumps(_load(), ensure_ascii=False, indent=2))
    elif a.task:
        print(json.dumps(start(a.task), ensure_ascii=False, indent=2))
    elif a.answer:
        print(json.dumps(answer(a.answer), ensure_ascii=False, indent=2))
    elif a.commit:
        print(json.dumps(commit(a.commit), ensure_ascii=False, indent=2))
    elif a.push:
        print(json.dumps(push(), ensure_ascii=False))
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
