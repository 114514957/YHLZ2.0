"""YHLZ remote dev runner (ledger 0226): drive opencode headless from QQ.

Flow (per user's workflow):
  master QQ -> qq_bot `#dev <task>` -> DevRunner.start(task)
  -> `opencode run` (headless, dir = project root)
  -> agent may ask ONE key question  -> relay to QQ, wait for master's answer
  -> master answers -> DevRunner.answer(text) -> continue the SAME session
  -> agent finishes -> report result to QQ
Commit/push is NOT performed by the agent; only after master replies `#y`
does the runner commit (push still needs a separate `#push`).

Safety: only the whitelisted master (qq_bot enforces); no auto push; the
agent prompt forbids git commit/push; work is confined to --dir (project).

Usage:
  python tools/dev_runner.py --task "把 X 改成 Y"
  python tools/dev_runner.py --answer "用方案 A"
  python tools/dev_runner.py --status
  python tools/dev_runner.py --commit "msg"
Env: YHLZ_DEV_MODEL (default deepseek/deepseek-v4-flash)
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

_ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE = _ROOT / "cache" / "dev" / "state.json"
LOG = _ROOT / "cache" / "dev" / "opencode.log"
MODEL = os.getenv("YHLZ_DEV_MODEL", "deepseek/deepseek-v4-flash")
TIMEOUT = float(os.getenv("YHLZ_DEV_TIMEOUT", "1800"))

START_PROMPT = """你是 YHLZ 项目的开发执行体，工作目录就是项目根目录。
这是一个新任务。**这一轮先不要动手**（禁止修改文件、禁止运行会改变状态的命令），
只做三件事：
1) 用 1-3 个最关键的问题澄清需求（确实没有疑问就写"无问题"）；
2) 给出你打算怎么做的简短方案；
3) 给出你的把握程度（高/中/低）和理由。
以 [QUESTION] 开头输出以上内容，然后停止，等待用户答复后再执行。
执行阶段的规则：只在本项目内改动；禁止 git commit / git push（提交由外部确认）。
任务：{task}"""

ANSWER_PROMPT = """（用户答复）{answer}

请据此继续：
- 若信息已足够，就执行任务；完成后用一段话总结（做了什么、改了哪些文件、
  是否跑了测试及结果），以 [DONE] 开头。
- 若仍需澄清，只问最关键的问题并以 [QUESTION] 开头，然后停止等待。
- 全程只在本项目内改动；禁止 git commit / git push。"""


def _opencode_exe() -> str:
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
    raise FileNotFoundError("找不到 opencode 可执行文件（npm i -g opencode-ai）")


def _run(prompt: str, session: str | None, timeout: float) -> dict:
    """Run opencode headless; return {text, session, ok}."""
    cmd = [_opencode_exe(), "run", prompt, "-m", MODEL,
           "--dir", str(_ROOT), "--format", "json"]
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
            cmd, cwd=str(_ROOT), stdout=subprocess.PIPE,
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
    if "[QUESTION]" in text:
        return "awaiting"
    if "[DONE]" in text:
        return "done"
    s = text.strip()
    if len(s) < 300 and ("?" in s or "？" in s):
        return "awaiting"
    return "done"


def start(task: str) -> dict:
    d = {"status": "running", "session": "", "task": task, "text": ""}
    _save(d)
    r = _run(START_PROMPT.format(task=task), None, TIMEOUT)
    d["session"] = r["session"]
    d["text"] = r["text"] or r["error"]
    d["status"] = _classify(r["text"]) if r["ok"] else "error"
    _save(d)
    return d


def answer(text: str) -> dict:
    d = _load()
    if not d.get("session"):
        return {"status": "error", "text": "没有进行中的会话，先用 #dev <任务> 开始",
                "session": ""}
    d["status"] = "running"
    _save(d)
    r = _run(ANSWER_PROMPT.format(answer=text), d["session"], TIMEOUT)
    d["text"] = r["text"] or r["error"]
    d["status"] = _classify(r["text"]) if r["ok"] else "error"
    _save(d)
    return d


def commit(message: str) -> dict:
    def git(*a: str) -> str:
        p = subprocess.run(["git", *a], cwd=str(_ROOT), capture_output=True,
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
    p = subprocess.run(["git", "push", "origin", "HEAD"], cwd=str(_ROOT),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return {"text": ((p.stdout or "") + (p.stderr or "")).strip()}


def main() -> int:
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
