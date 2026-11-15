# -*- coding: utf-8 -*-
"""56 + 28 本地评测（greedy），可选「每轮锚点」开关 —— 用来 A/B 验证投递假设。

用法：
  python experiments/eval56_28.py --tag 基线          # 不加锚点
  python experiments/eval56_28.py --tag 锚点 --anchor  # 加锚点

判分：复用 tools/persona_bank.verify（确定性，无 LLM 判官）。
输出：cache/eval_<tag>.json + 屏显分数与闸门。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import group_bank as GB  # noqa: E402
import persona_bank as PB  # noqa: E402
from backend import target_prompts as TP  # noqa: E402
from backend import turn_anchor as TA  # noqa: E402

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(port: int, system: str, user: str, max_tokens: int = 300,
         tools: list[dict] | None = None,
         anchor_msg: str = "") -> tuple[str, list[str]]:
    msgs = [{"role": "system", "content": system}]
    if anchor_msg:
        # system 模式：独立 system 消息**放在用户轮之前**（不是拼进用户文本，
        # 实测拼进用户文本她会当内容复述）
        msgs.append({"role": "system", "content": anchor_msg})
    msgs.append({"role": "user", "content": user})
    body = {
        "messages": msgs,
        "temperature": 0.0, "max_tokens": max_tokens, "stream": False,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    # 2026-11-15（台账 1245）：本地 llama 已下线，评测必须能打云端。
    # `port == 0` 表示走 llm_router（cloud）；否则仍打本地 OpenAI 兼容端点。
    if port == 0:
        from backend import llm_router as _R
        d = _R.chat(msgs, tools=tools or None, temperature=0.0,
                    max_tokens=max_tokens, channel="eval", retries=3)
    else:
        req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % port,
                                     data=json.dumps(body, ensure_ascii=False).encode(),
                                     headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=300) as r:
            d = json.loads(r.read().decode())
    msg = (d.get("choices") or [{}])[0].get("message") or {}
    raw = str(msg.get("content") or "")
    used = [str((c.get("function") or {}).get("name") or "")
            for c in (msg.get("tool_calls") or []) if isinstance(c, dict)]
    return PB.clean_answer(raw) if hasattr(PB, "clean_answer") else raw, used


def run(port: int, anchor: bool, max_tokens: int, mode: str = "system") -> dict:
    out = {"persona": [], "group": []}
    # 工具定义：人格卷里有 t01–t14 是工具遵循题，不给 schema 必全灭。
    # 复用工作台的同一份工具清单，保证与历史评测同口径。
    tools: list[dict] = []
    try:
        sys.path.insert(0, os.path.join(ROOT, "llm_workbench"))
        import evals as _ev  # noqa: E402
        tools = _ev.load_tools()
        print("工具定义 %d 个（与工作台同源）" % len(tools))
    except Exception as ex:  # noqa: BLE001
        print("⚠ 工具清单加载失败（工具题会全灭）：%s" % type(ex).__name__)

    sys_p = TP.render_system_prompt(public=False)
    anchor_p = TA.anchor_for(sys_p) if anchor else ""
    for e in PB.PERSONA_BANK:
        u = e["q"]
        if anchor and mode == "user":
            u = TA.apply(u, sys_p)
        try:
            ans, tools_used = call(port, sys_p, u, max_tokens, tools,
                                   anchor_msg=anchor_p if (anchor and mode == "system") else "")
        except Exception as ex:  # noqa: BLE001
            ans, tools_used = "", []
            print("   ! %s 请求失败 %s" % (e["id"], type(ex).__name__))
        ok, why = PB.verify(e, ans, tools_used)
        out["persona"].append({"id": e["id"], "cat": e.get("cat"), "gate": PB.is_gate(e),
                               "ok": ok, "why": why, "ans": ans})

    sys_g = TP.render_system_prompt(public=True)
    anchor_g = TA.anchor_for(sys_g) if anchor else ""
    for e in GB.GROUP_BANK:
        msgs = e.get("messages") or []
        u = "\n".join(str(m.get("content") or "") if isinstance(m, dict) else str(m)
                      for m in msgs) or str(e.get("scene") or "")
        if anchor and mode == "user":
            u = TA.apply(u, sys_g)
        try:
            ans, tools = call(port, sys_g, u, max_tokens, None,
                              anchor_msg=anchor_g if (anchor and mode == "system") else "")
        except Exception as ex:  # noqa: BLE001
            ans, tools = "", []
            print("   ! %s 请求失败 %s" % (e["id"], type(ex).__name__))
        ok, why = GB.verify(e, ans, tools)
        out["group"].append({"id": e["id"], "gate": GB.is_gate(e), "ok": ok,
                             "why": why, "ans": ans})
    return out


def summary(res: dict) -> dict:
    p = res["persona"]
    g = res["group"]
    pg = [r for r in p if r["gate"]]
    gg = [r for r in g if r["gate"]]
    return {
        "persona": "%d/%d" % (sum(r["ok"] for r in p), len(p)),
        "persona_gate": "%d/%d" % (sum(r["ok"] for r in pg), len(pg)),
        "group": "%d/%d" % (sum(r["ok"] for r in g), len(g)),
        "group_gate": "%d/%d" % (sum(r["ok"] for r in gg), len(gg)),
        "persona_fail": [r["id"] for r in p if not r["ok"]],
        "group_fail": [r["id"] for r in g if not r["ok"]],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--anchor", action="store_true")
    ap.add_argument("--anchor-mode", default="system", choices=["system", "user"])
    ap.add_argument("--port", type=int, default=8081,
                    help="0 = 走 llm_router（云端）")
    ap.add_argument("--provider", default="",
                    help="cloud / local；给 cloud 等价于 --port 0")
    ap.add_argument("--max-tokens", type=int, default=300)
    a = ap.parse_args()

    t0 = time.time()
    port = 0 if str(a.provider).lower() == "cloud" else a.port
    print("评测 tag=%s｜锚点=%s(%s)｜port=%d%s"
          % (a.tag, "开" if a.anchor else "关", a.anchor_mode, port,
             "（云端 llm_router）" if port == 0 else ""))
    res = run(port, a.anchor, a.max_tokens, a.anchor_mode)
    s = summary(res)
    print("\n56 题：%s（闸门 %s）｜失败 %s"
          % (s["persona"], s["persona_gate"], "、".join(s["persona_fail"]) or "无"))
    print("28 题：%s（闸门 %s）｜失败 %s"
          % (s["group"], s["group_gate"], "、".join(s["group_fail"]) or "无"))
    print("耗时 %.1f 分钟" % ((time.time() - t0) / 60))

    out = os.path.join(ROOT, "cache", "eval_%s.json" % a.tag)
    json.dump({"tag": a.tag, "anchor": a.anchor, "summary": s, "detail": res},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("明细：%s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
