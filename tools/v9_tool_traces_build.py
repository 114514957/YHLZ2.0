"""把真实工具留痕汇编为训练样本（ledger 0874）。

输入：`data/tool_traces/live.jsonl`（`backend/tool_trace_log.py` 写入的运行时记录）
输出：`data/pd/v9_tool_traces_real.jsonl`
  每条 = 一条真实轨迹：{messages:[user, assistant(tool_calls), tool(result), assistant(final)],
                       source:"tooltrace:real", license:"own", group_id, chars}
同时给 PT 用的纯文本形态也在 messages 里（装配器直接渲染）。

用法：python tools/v9_tool_traces_build.py [--min-tools 1]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "tool_traces" / "live.jsonl"
OUT = ROOT / "data" / "pd" / "v9_tool_traces_real.jsonl"


def render(result: dict) -> str:
    out = []
    if result.get("ok"):
        out.append(str(result.get("output") or result.get("readback") or "ok"))
    else:
        out.append(f"ERROR: {result.get('error') or 'failed'}")
    return "\n".join(out)[:1200]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-tools", type=int, default=1)
    args = ap.parse_args()
    if not SRC.exists():
        print("缺少", SRC, file=sys.stderr)
        return 2

    rows, skipped = [], 0
    for line in SRC.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        tools = [t for t in (d.get("tools") or []) if t.get("name")]
        if len(tools) < args.min_tools:
            skipped += 1
            continue
        user = str(d.get("user_text") or "").strip()
        answer = str(d.get("answer") or "").strip()
        if not user:
            skipped += 1
            continue
        calls = [{"id": f"call_{i}", "type": "function",
                  "function": {"name": t["name"],
                               "arguments": json.dumps(t.get("arguments") or {},
                                                       ensure_ascii=False)}}
                 for i, t in enumerate(tools)]
        results = "\n".join(f"[{t['name']}] {render(t)}" for t in tools)
        messages = [{"role": "user", "content": user},
                    {"role": "assistant", "content": answer or "",
                     "tool_calls": calls},
                    {"role": "tool", "content": results}]
        if answer:
            messages.append({"role": "assistant", "content": answer})
        text = "\n".join(
            [f"[user] {user}", f"[tool_call] {json.dumps([{'name': c['function']['name'], 'arguments': c['function']['arguments']} for c in calls], ensure_ascii=False)}",
             f"[tool_result] {results[:800]}"] + ([f"[assistant] {answer}"] if answer else []))
        rows.append({"messages": messages, "text": text,
                     "source": "tooltrace:real", "source_id": f"trace#{int(d.get('ts', 0))}",
                     "group_id": f"trace:{int(d.get('ts', 0))}",
                     "license": "own", "channel": d.get("channel"),
                     "tools": [t["name"] for t in tools],
                     "chars": len(text),
                     "content_hash": hashlib.sha256(text.encode()).hexdigest()[:16]})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"real_traces": len(rows), "skipped": skipped,
                      "tools": sorted({t for r in rows for t in r["tools"]}),
                      "file": str(OUT.relative_to(ROOT))}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
