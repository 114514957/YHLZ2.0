"""LLM 工作台 —— 版本控制 + 对话测试 + 评测跑分（本地 WebUI）。

端口：工作台 8090；它自己起的 llama-server 默认 8091（8081/8082 是老爹的，不碰）。

启动：
    YH\\.venv\\Scripts\\python.exe YH\\llm_workbench\\server.py
或双击 llm_workbench\\start_llm_workbench.bat
"""
from __future__ import annotations

import json
import os
import sys
import time

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import evals  # noqa: E402
import convert  # noqa: E402
import registry  # noqa: E402
import serverctl  # noqa: E402

STATIC = os.path.join(HERE, "static")
CHAT_DIR = os.path.join(HERE, "data", "chats")
WORKBENCH_PORT = int(os.environ.get("LLM_WORKBENCH_PORT", "8090"))

app = FastAPI(title="LLM 工作台", version="0.1")


# ---------------------------------------------------------------- 基础状态
@app.get("/api/state")
def api_state(debug: int = 0):
    t0 = time.time()
    reg = registry.scan()
    t1 = time.time()
    srv = serverctl.status(debug=bool(debug))
    t2 = time.time()
    runs = evals.list_runs()[:30]
    t3 = time.time()
    out = {
        "registry": reg,
        "server": srv,
        "eval": evals.state(),
        "runs": runs,
        "system_prompt": evals.UNIFIED_SYSTEM,
        "default_port": serverctl.DEFAULT_PORT,
        "workbench_port": WORKBENCH_PORT,
    }
    if debug:
        out["timing_ms"] = {"registry": round((t1 - t0) * 1000),
                            "server": round((t2 - t1) * 1000),
                            "runs": round((t3 - t2) * 1000),
                            "total": round((time.time() - t0) * 1000)}
    return out


@app.get("/api/materials")
def api_materials():
    """素材总览（2026-11-08）：黄金样本 / docs/素材 集 / dist 训练包，给工作台「素材」页用。

    只读、带 60s 缓存；不碰数据本身。
    """
    now = time.time()
    cached = _MAT_CACHE.get("data")
    if cached and now - _MAT_CACHE.get("ts", 0) < 60:
        return cached

    root = os.path.dirname(HERE)

    def lines(path: str) -> int:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return sum(1 for _ in f)
        except Exception:  # noqa: BLE001
            return 0

    def blocks(path: str) -> int:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return sum(1 for line in f if line.startswith("## "))
        except Exception:  # noqa: BLE001
            return 0

    mat_dir = os.path.join(root, "docs", "素材")
    sets = []
    try:
        for name in sorted(os.listdir(mat_dir)):
            p = os.path.join(mat_dir, name)
            if not os.path.isfile(p) or not name.endswith(".md"):
                continue
            sets.append({"name": name[:-3], "file": name,
                         "blocks": blocks(p),
                         "kb": round(os.path.getsize(p) / 1024, 1),
                         "mtime": int(os.path.getmtime(p))})
    except Exception:  # noqa: BLE001
        pass

    golden_path = os.path.join(mat_dir, "黄金样本.md")
    golden = {"path": golden_path, "exists": os.path.isfile(golden_path),
              "blocks": 0, "adopted": None,
              "kb": round(os.path.getsize(golden_path) / 1024, 1) if os.path.isfile(golden_path) else 0,
              "mtime": int(os.path.getmtime(golden_path)) if os.path.isfile(golden_path) else 0}
    try:
        with open(golden_path, "r", encoding="utf-8", errors="replace") as f:
            golden["blocks"] = sum(1 for line in f if line.startswith("## golden-"))
    except Exception:  # noqa: BLE001
        pass
    try:
        if root not in sys.path:
            sys.path.insert(0, root)
        from tools.golden_build import load_golden

        golden["adopted"] = sum(1 for g in load_golden()
                                if g.get("status") in ("keep", "fixed"))
    except Exception:  # noqa: BLE001
        pass

    pkgs = []
    dist = os.path.join(root, "dist")
    try:
        for name in sorted(os.listdir(dist)):
            p = os.path.join(dist, name)
            if not os.path.isdir(p) or not name.startswith("retrain_pkg"):
                continue
            files = [f for f in os.listdir(p) if f.endswith(".jsonl")]
            train_lines = sum(lines(os.path.join(p, f)) for f in files if "train" in f)
            val_lines = sum(lines(os.path.join(p, f)) for f in files if "val" in f)
            mb = round(sum(os.path.getsize(os.path.join(p, f))
                           for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))) / 1e6, 1)
            pkgs.append({"name": name, "files": len(files),
                         "train_lines": train_lines, "val_lines": val_lines,
                         "mb": mb, "mtime": int(os.path.getmtime(p))})
    except Exception:  # noqa: BLE001
        pass

    out = {"ok": True, "golden": golden, "sets": sets, "packages": pkgs,
           "materials_md": os.path.join(mat_dir, "素材库.md")}
    _MAT_CACHE.update({"ts": now, "data": out})
    return out


_MAT_CACHE: dict = {}


@app.post("/api/scan")
def api_scan():
    return registry.scan(force=True)


# ---------------------------------------------------------------- 转 GGUF
class ConvertReq(BaseModel):
    version_id: str
    out_name: str = ""


@app.post("/api/convert")
def api_convert(req: ConvertReq):
    reg = registry.scan()
    v = next((x for x in reg["versions"] if x["id"] == req.version_id), None)
    if not v:
        raise HTTPException(404, "没有这个版本：%s" % req.version_id)
    if v["kind"] != "adapter":
        raise HTTPException(400, "只有 adapter 目录需要转 GGUF")
    res = convert.start(v["path"], v["version"], req.out_name)
    if not res.get("ok"):
        raise HTTPException(409, res.get("error", "启动失败"))
    return res


@app.get("/api/convert/state")
def api_convert_state():
    return convert.state()


# ---------------------------------------------------------------- 版本备注
class NoteReq(BaseModel):
    label: str = ""
    note: str = ""
    tags: list[str] = Field(default_factory=list)


@app.post("/api/versions/{ver}/note")
def api_note(ver: str, req: NoteReq):
    notes = registry.load_notes()
    notes[ver] = {"label": req.label.strip(), "note": req.note.strip(),
                  "tags": [t.strip() for t in req.tags if t.strip()],
                  "updated_at": int(time.time())}
    registry.save_notes(notes)
    return {"ok": True}


# ---------------------------------------------------------------- 服务启停
class StartReq(BaseModel):
    version_id: str
    port: int = serverctl.DEFAULT_PORT
    ctx: int = 8192
    ngl: int = 99
    force: bool = False


@app.post("/api/server/start")
def api_start(req: StartReq):
    reg = registry.scan()
    v = next((x for x in reg["versions"] if x["id"] == req.version_id), None)
    if not v:
        raise HTTPException(404, "没有这个版本：%s" % req.version_id)
    if v["kind"] != "gguf-lora":
        raise HTTPException(400, "adapter 目录不能直接服务，先转成 GGUF")
    # 默认异步：加载模型要几十秒，HTTP 不该挂着；前端轮询 /api/server/status。
    res = serverctl.start_async(req.version_id, v["path"], reg["bases"]["gguf"],
                                reg["bases"]["mmproj"], req.port, req.ctx,
                                req.ngl, req.force)
    if not res.get("ok"):
        raise HTTPException(409, res.get("error", "启动失败"))
    return res


@app.post("/api/server/stop")
def api_stop():
    return serverctl.stop()


class StopExtReq(BaseModel):
    port: int
    confirm: bool = False


@app.post("/api/server/stop-external")
def api_stop_external(req: StopExtReq):
    if not req.confirm:
        raise HTTPException(400, "停外部实例必须带 confirm=true（界面会二次确认）")
    return serverctl.stop_external(req.port)


@app.get("/api/server/status")
def api_status():
    return serverctl.status()


@app.get("/api/debug/pid/{pid}")
def api_debug_pid(pid: int):
    """排障用：看看服务进程自己眼里这个 PID 活没活。"""
    import subprocess
    try:
        r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                           capture_output=True, text=True, timeout=10)
        raw = {"rc": r.returncode, "stdout": r.stdout[:300], "stderr": r.stderr[:300]}
    except Exception as ex:  # noqa: BLE001
        raw = {"exc": "%s: %s" % (type(ex).__name__, ex)}
    return {"alive": serverctl._pid_alive(pid), "tasklist": raw,
            "path_head": (os.environ.get("PATH") or "")[:200]}


# ---------------------------------------------------------------- 对话（流式）
class ChatReq(BaseModel):
    port: int = serverctl.DEFAULT_PORT
    messages: list[dict]
    system: str = ""
    temperature: float = 0.7
    top_p: float = 0.95
    max_tokens: int = 512
    tools_enabled: bool = False


@app.post("/api/chat")
async def api_chat(req: ChatReq):
    msgs = []
    if req.system.strip():
        msgs.append({"role": "system", "content": req.system})
    msgs.extend(req.messages)
    body = {"messages": msgs, "temperature": req.temperature, "top_p": req.top_p,
            "max_tokens": req.max_tokens, "stream": True,
            "stream_options": {"include_usage": True}}
    if req.tools_enabled:
        tools = evals.load_tools()
        if tools:
            body["tools"] = tools

    async def gen():
        url = "http://127.0.0.1:%d/v1/chat/completions" % req.port
        t0 = time.time()
        first = None
        n_tok = 0
        called: list[str] = []
        try:
            # trust_env=False：本机回环调用绝不能走 Clash 代理。
            # 这台机器的 NO_PROXY 里带 `[::1]`，httpx 解析会抛
            # InvalidURL: Invalid port: ':1]'（2026-11-02 实撞）。
            async with httpx.AsyncClient(timeout=None, trust_env=False) as cli:
                async with cli.stream("POST", url, json=body) as r:
                    if r.status_code != 200:
                        txt = (await r.aread()).decode("utf-8", "replace")[:400]
                        yield _sse({"type": "error", "error": "HTTP %d: %s"
                                    % (r.status_code, txt)})
                        return
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            d = json.loads(data)
                        except Exception:  # noqa: BLE001
                            continue
                        ch = (d.get("choices") or [{}])[0]
                        delta = ch.get("delta") or {}
                        piece = delta.get("content") or ""
                        for tc in (delta.get("tool_calls") or []):
                            nm = ((tc or {}).get("function") or {}).get("name")
                            if nm and nm not in called:
                                called.append(nm)
                        if piece:
                            if first is None:
                                first = time.time() - t0
                            n_tok += 1
                            yield _sse({"type": "delta", "text": piece})
            el = time.time() - t0
            yield _sse({"type": "done", "elapsed": round(el, 2),
                        "ttft": round(first, 2) if first is not None else None,
                        "chunks": n_tok,
                        "tps": round(n_tok / el, 1) if el > 0 and n_tok else None,
                        "called": called})
        except Exception as ex:  # noqa: BLE001
            yield _sse({"type": "error", "error": "%s: %s" % (type(ex).__name__, ex)})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


# ---------------------------------------------------------------- 评测
class EvalReq(BaseModel):
    suite: str = "persona56"
    port: int = serverctl.DEFAULT_PORT
    tag: str = "run"
    max_tokens: int = 300
    cold: bool = False


@app.post("/api/eval/start")
def api_eval_start(req: EvalReq):
    res = evals.start(req.suite, req.port, req.tag, req.max_tokens, cold=req.cold)
    if not res.get("ok"):
        raise HTTPException(409, res.get("error", "启动失败"))
    return res


@app.get("/api/eval/state")
def api_eval_state():
    return evals.state()


@app.get("/api/runs")
def api_runs():
    return evals.list_runs()


@app.get("/api/runs/{fn}")
def api_run(fn: str):
    d = evals.get_run(fn)
    if not d:
        raise HTTPException(404, "没有这个记录")
    return d


@app.get("/api/diff")
def api_diff(a: str, b: str):
    """两次跑分并排：分类分差 + 逐题差（谁过谁不过、答案有没有变）。"""
    da = evals.get_run(a)
    db = evals.get_run(b)
    if not da or not db:
        raise HTTPException(404, "记录不存在")
    if da.get("ok") is None or db.get("ok") is None:
        raise HTTPException(400, "这两条至少有一条不是判分套件（素材探针只看答案，没法比）")

    ra = {x["id"]: x for x in da.get("results") or []}
    rb = {x["id"]: x for x in db.get("results") or []}
    items = []
    for qid in sorted(set(ra) & set(rb), key=lambda s: (list(ra).index(s))):
        x, y = ra[qid], rb[qid]
        if x["ok"] and y["ok"]:
            kind = "both_ok"
        elif x["ok"] and not y["ok"]:
            kind = "a_only"
        elif not x["ok"] and y["ok"]:
            kind = "b_only"
        else:
            kind = "both_fail"
        items.append({"id": qid, "cat": x.get("cat"), "q": x.get("q"),
                      "a_ok": bool(x["ok"]), "b_ok": bool(y["ok"]), "kind": kind,
                      "a_answer": (x.get("answer") or "")[:600],
                      "b_answer": (y.get("answer") or "")[:600],
                      "a_why": x.get("why") or "", "b_why": y.get("why") or "",
                      "changed": (x.get("answer") or "") != (y.get("answer") or "")})

    cats = []
    ca, cb = da.get("by_cat") or {}, db.get("by_cat") or {}
    for cat in sorted(set(ca) | set(cb)):
        pa, pb = ca.get(cat, [0, 0]), cb.get(cat, [0, 0])
        cats.append({"cat": cat, "a": pa, "b": pb, "delta": pa[0] - pb[0]})

    return {
        "a": {k: da.get(k) for k in ("tag", "ok", "total", "by_cat", "cold",
                                     "finished_at", "port", "suite")},
        "b": {k: db.get(k) for k in ("tag", "ok", "total", "by_cat", "cold",
                                     "finished_at", "port", "suite")},
        "total": {"a": da.get("ok"), "b": db.get("ok"),
                  "delta": (da.get("ok") or 0) - (db.get("ok") or 0)},
        "cats": cats,
        "items": items,
        "counts": {k: sum(1 for i in items if i["kind"] == k)
                   for k in ("both_ok", "a_only", "b_only", "both_fail")},
    }


# ---------------------------------------------------------------- 对话存档
class ChatSaveReq(BaseModel):
    title: str = ""
    version: str = ""
    messages: list[dict]
    meta: dict = Field(default_factory=dict)


@app.post("/api/chats")
def api_chat_save(req: ChatSaveReq):
    os.makedirs(CHAT_DIR, exist_ok=True)
    fn = "%d_%s.json" % (int(time.time()), (req.title or "chat").replace("/", "_")[:40])
    path = os.path.join(CHAT_DIR, fn)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"title": req.title, "version": req.version,
                   "messages": req.messages, "meta": req.meta,
                   "saved_at": int(time.time())}, f, ensure_ascii=False, indent=2)
    return {"ok": True, "file": fn}


@app.get("/api/chats")
def api_chats():
    out = []
    if os.path.isdir(CHAT_DIR):
        for fn in sorted(os.listdir(CHAT_DIR), reverse=True):
            if fn.endswith(".json"):
                p = os.path.join(CHAT_DIR, fn)
                try:
                    with open(p, encoding="utf-8") as f:
                        d = json.load(f)
                    out.append({"file": fn, "title": d.get("title"),
                                "version": d.get("version"), "saved_at": d.get("saved_at"),
                                "turns": len(d.get("messages") or [])})
                except Exception:  # noqa: BLE001
                    continue
    return out


@app.get("/api/chats/{fn}")
def api_chat_get(fn: str):
    p = os.path.join(CHAT_DIR, os.path.basename(fn))
    if not os.path.exists(p):
        raise HTTPException(404, "没有这条记录")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 静态页
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main() -> int:
    print("LLM 工作台 → http://127.0.0.1:%d" % WORKBENCH_PORT)
    uvicorn.run(app, host="127.0.0.1", port=WORKBENCH_PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
