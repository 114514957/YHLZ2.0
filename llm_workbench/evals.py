"""评测：把「56 题人格库」和「20 题素材探针」跑成一个后台任务。

判分复用 tools/persona_bank.verify()——同一份判据，不在工作台里另写一套，
否则又会出「判分函数的结果 ≠ 实际行为」那种事故（台账 1050 / 1059）。

工具遵循题：请求里带 tools（data/tool_registry/snapshot_latest.json），
优先看 llama-server 解析出来的 tool_calls，其次在正文里正则兜底——
gemma 会输出 `call:name{...}`，Qwen3 会输出 `<tool_call>{...}</tool_call>`，
两种都要认（台账 1050 的坑）。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # YH/
TOOLS_DIR = os.path.join(ROOT, "tools")
DATA_DIR = os.path.join(HERE, "data")
RUNS_DIR = os.path.join(DATA_DIR, "runs")
SNAP = os.path.join(ROOT, "data", "tool_registry", "snapshot_latest.json")
MATERIAL20 = os.path.join(ROOT, "cache", "material_probe20.json")

if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import persona_bank as PB  # noqa: E402
import group_bank as GB  # noqa: E402
from unified_prompt import UNIFIED_SYSTEM  # noqa: E402


def load_tools() -> list[dict]:
    if not os.path.exists(SNAP):
        return []
    with io.open(SNAP, encoding="utf-8") as f:
        d = json.load(f)
    inner = d.get("tools") or d
    return [t if "function" in t else {"type": "function", "function": t}
            for t in inner]


def extract_called(msg: dict, raw: str) -> list[str]:
    called: list[str] = []
    for tc in (msg.get("tool_calls") or []):
        name = ((tc or {}).get("function") or {}).get("name")
        if name and name not in called:
            called.append(name)
    for m in re.finditer(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", raw, re.S):
        try:
            j = json.loads(m.group(1))
            if j.get("name") and j["name"] not in called:
                called.append(j["name"])
        except Exception:  # noqa: BLE001
            pass
    for m in re.finditer(r"(?:<\|tool_call>\s*)?call:\s*([a-z_][a-z0-9_]*)\s*\{", raw):
        if m.group(1) not in called:
            called.append(m.group(1))
    if not called:
        for m in re.finditer(r'"name"\s*:\s*"([a-z_]+)"', raw):
            if m.group(1) not in called:
                called.append(m.group(1))
    return called


# 本机回环直连，绕开系统代理（NO_PROXY 里那个 `[::1]` 会坑到解析）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _post(port: int, body: dict, timeout: float = 300) -> dict:
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % port,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


_JOB: dict = {"running": False}
_LOCK = threading.Lock()


def state() -> dict:
    with _LOCK:
        return dict(_JOB)


def _set(**kw) -> None:
    with _LOCK:
        _JOB.update(kw)


def _run_persona56(port: int, tag: str, max_tokens: int = 300) -> dict:
    tools = load_tools()
    qs = list(PB.PERSONA_BANK)
    _set(total=len(qs), done=0)
    res = []
    for i, e in enumerate(qs):
        body = {"messages": [{"role": "system", "content": UNIFIED_SYSTEM},
                             {"role": "user", "content": e["q"]}],
                "temperature": 0.0, "max_tokens": max_tokens, "stream": False}
        if e["cat"] == "工具遵循" and tools:
            body["tools"] = tools
        t0 = time.time()
        err = ""
        try:
            d = _post(port, body)
            msg = d["choices"][0]["message"]
            raw = (msg.get("content") or "").strip()
            called = extract_called(msg, raw)
        except Exception as ex:  # noqa: BLE001
            raw, called, err = "", [], "%s: %s" % (type(ex).__name__, ex)
        el = time.time() - t0
        if err:
            ok, why = False, err[:60]
        else:
            try:
                ok, why = PB.verify(e, raw, tuple(called))
            except Exception as ex:  # noqa: BLE001
                ok, why = False, str(ex)[:60]
        res.append({"id": e["id"], "cat": e["cat"], "q": e["q"],
                    "answer": raw[:800], "called": called,
                    "ok": bool(ok), "why": why, "elapsed": round(el, 2),
                    "error": err})
        _set(done=i + 1, last_id=e["id"])
    return _summarize(res, "persona56")


def _run_material20(port: int, tag: str, max_tokens: int = 300) -> dict:
    if not os.path.exists(MATERIAL20):
        return {"ok": False, "error": "缺 %s" % MATERIAL20}
    with io.open(MATERIAL20, encoding="utf-8") as f:
        cases = json.load(f)
    _set(total=len(cases), done=0)
    res = []
    for i, c in enumerate(cases):
        body = {"messages": [{"role": "system", "content": UNIFIED_SYSTEM},
                             {"role": "user", "content": c["q"]}],
                "temperature": 0.0, "max_tokens": max_tokens, "stream": False}
        t0 = time.time()
        err = ""
        try:
            d = _post(port, body)
            msg = d["choices"][0]["message"]
            raw = (msg.get("content") or "").strip()
        except Exception as ex:  # noqa: BLE001
            raw, err = "", "%s: %s" % (type(ex).__name__, ex)
        res.append({"id": c.get("id"), "cat": c.get("cat"), "q": c["q"],
                    "answer": raw[:800], "elapsed": round(time.time() - t0, 2),
                    "error": err})
        _set(done=i + 1, last_id=c.get("id"))
    return {"tag": tag, "suite": "material20", "total": len(res), "ok": None,
            "by_cat": {}, "results": res}


def _public_system() -> str:
    """群聊要用群聊的系统提示词（backend 里那份 public 渲染），不是私聊的 UNIFIED_SYSTEM。

    2026-11-04 实撞：拿私聊提示词跑群聊题，元亨把每个群友都叫「老爹」。
    """
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from backend.target_prompts import render_system_prompt
        return render_system_prompt(public=True)
    except Exception:  # noqa: BLE001
        return UNIFIED_SYSTEM


def _run_group(port: int, tag: str, max_tokens: int = 300) -> dict:
    """群聊语境：多人/短回合/@关系。判据仍用 persona_bank.verify（确定性）。"""
    qs = list(GB.GROUP_BANK)
    _set(total=len(qs), done=0)
    system = _public_system()
    res = []
    for i, e in enumerate(qs):
        msgs = [{"role": "system", "content": system}] + list(e["messages"])
        body = {"messages": msgs, "temperature": 0.0, "max_tokens": max_tokens,
                "stream": False}
        t0 = time.time()
        err = ""
        try:
            d = _post(port, body)
            raw = ((d["choices"][0]["message"].get("content")) or "").strip()
        except Exception as ex:  # noqa: BLE001
            raw, err = "", "%s: %s" % (type(ex).__name__, ex)
        if err:
            ok, why = False, err[:60]
        else:
            try:
                ok, why = GB.verify(e, raw, ())
            except Exception as ex:  # noqa: BLE001
                ok, why = False, str(ex)[:60]
        res.append({"id": e["id"], "cat": "群聊", "q": e.get("scene") or "",
                    "answer": raw[:800], "called": [], "ok": bool(ok), "why": why,
                    "elapsed": round(time.time() - t0, 2), "error": err,
                    "gate": bool(e.get("gate"))})
        _set(done=i + 1, last_id=e["id"])
    out = _summarize(res, "group")
    gate = [r["id"] for r in res if r.get("gate") and not r["ok"]]
    out["gate_fail"] = gate
    out["gate_ok"] = not gate
    return out


def _summarize(res: list[dict], suite: str) -> dict:
    cat: dict[str, list[int]] = {}
    for r in res:
        c = cat.setdefault(r["cat"], [0, 0])
        c[1] += 1
        if r["ok"]:
            c[0] += 1
    total = sum(v[1] for v in cat.values())
    ok = sum(v[0] for v in cat.values())
    # 安全闸门（台账 1013/1077）：r07/r08/s06 任一挂 = 整套不算过，不折算成分数
    gate = [r["id"] for r in res if r["id"] in PB.GATE_IDS and not r["ok"]]
    return {"suite": suite, "total": total, "ok": ok, "by_cat": cat, "results": res,
            "gate_fail": gate, "gate_ok": not gate,
            "judge_version": getattr(PB, "JUDGE_VERSION", 1)}


def _worker(suite: str, port: int, tag: str, max_tokens: int) -> None:
    try:
        if suite == "persona56":
            out = _run_persona56(port, tag, max_tokens)
        elif suite == "group":
            out = _run_group(port, tag, max_tokens)
        elif suite == "material20":
            out = _run_material20(port, tag, max_tokens)
        else:
            out = {"ok": False, "error": "未知套件 %s" % suite}
        out.update({"tag": tag, "port": port, "finished_at": int(time.time()),
                    "started_at": _JOB.get("started_at"),
                    "cold": bool(_JOB.get("cold"))})
        os.makedirs(RUNS_DIR, exist_ok=True)
        fn = "%d_%s_%s.json" % (int(time.time()), suite, re.sub(r"[^\w.-]", "_", tag))
        path = os.path.join(RUNS_DIR, fn)
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        _set(running=False, result=out, result_file=fn, error=out.get("error", ""))
    except Exception as ex:  # noqa: BLE001
        _set(running=False, error="%s: %s" % (type(ex).__name__, ex))


def start(suite: str, port: int, tag: str, max_tokens: int = 300,
          cold: bool = False) -> dict:
    """cold=True 表示「实例刚起、没被聊过」。

    台账 1068：服务端只要先处理过一条**不带系统提示**的请求，同权重同参数的
    56 题会从 45 掉到 44（p10/p11 翻、st06 反翻），且 `cache_prompt=false` 也拦不住，
    只有重启实例能复位。所以「冷态」必须记进结果里，否则数字对不上。
    """
    with _LOCK:
        if _JOB.get("running"):
            return {"ok": False, "error": "已经有一个评测在跑"}
        _JOB.clear()
        _JOB.update({"running": True, "suite": suite, "port": port, "tag": tag,
                     "total": 0, "done": 0, "started_at": int(time.time()),
                     "result": None, "error": "", "cold": bool(cold)})
    t = threading.Thread(target=_worker, args=(suite, port, tag, max_tokens), daemon=True)
    t.start()
    return {"ok": True}


def list_runs() -> list[dict]:
    out = []
    if os.path.isdir(RUNS_DIR):
        for fn in sorted(os.listdir(RUNS_DIR), reverse=True):
            if not fn.endswith(".json"):
                continue
            p = os.path.join(RUNS_DIR, fn)
            try:
                with io.open(p, encoding="utf-8") as f:
                    d = json.load(f)
                out.append({"file": fn, "tag": d.get("tag"), "suite": d.get("suite"),
                            "total": d.get("total"), "ok": d.get("ok"),
                            "by_cat": d.get("by_cat"), "finished_at": d.get("finished_at"),
                            "port": d.get("port"), "cold": d.get("cold"),
                            "gate_ok": d.get("gate_ok"),
                            "judge_version": d.get("judge_version")})
            except Exception:  # noqa: BLE001
                continue
    return out


def get_run(fn: str) -> dict | None:
    p = os.path.join(RUNS_DIR, os.path.basename(fn))
    if not os.path.exists(p):
        return None
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    print(json.dumps({"persona": len(PB.PERSONA_BANK),
                      "tools": len(load_tools()),
                      "system_prompt_chars": len(UNIFIED_SYSTEM)},
                     ensure_ascii=False))
