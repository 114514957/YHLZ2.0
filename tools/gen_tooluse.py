"""Generate tool-use SFT trajectories from the REAL capability registry.

v8 (ledger 0506): the v6 generator hardcoded 15 FAKE tool names
(get_time/find_file/read_ledger/...) that matched ZERO of the 34 real
capabilities -> the model learned to call tools that do not exist.

This version:
  - derives tool names/descriptions/schemas from
    backend.target_scheduler_tools.openai_tools_view() (runtime truth);
  - batch composition per 10 records: 6 call + 1 failure-follow-up +
    1 multi-turn + 2 no-call (one of them = dev dispatch [[dev: ...]]);
    call:no-call = 7:2 >= 2:1;
  - hard validation: call names ⊆ batch tools (⊆ real registry), argument
    keys ⊆ declared properties, required params present, tool msg match;
  - checkpoints after every batch.

Output: data/finetune/tool_use_v8.jsonl  {messages, tools, source}

Usage:
    python tools/gen_tooluse.py --batches 1 --out data/finetune/_t.jsonl
    python tools/gen_tooluse.py --batches 60
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tools.cloud_rewrite as cr  # noqa: E402
from backend.target_scheduler_tools import openai_tools_view  # noqa: E402
from tools.finetune_assemble import SYSTEM  # noqa: E402

OUT = ROOT / "data" / "finetune" / "tool_use_v8.jsonl"

REAL: list[dict] = openai_tools_view()
REAL_BY_NAME: dict[str, dict] = {t["function"]["name"]: t["function"] for t in REAL}

_SYS_TASK = "你是数据工程师，严格按用户给定格式输出 JSON，不加任何解释。"


def ds_json(key, user, max_tokens=7000, temperature=0.9):
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": _SYS_TASK},
                     {"role": "user", "content": user}],
        "temperature": temperature, "max_tokens": max_tokens, "stream": False,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"].get("content", ""), d.get("usage", {})


def pick_tools(order: list[str], b: int, rng: random.Random) -> list[str]:
    k = rng.randint(4, 6)
    start = (b * 5) % len(order)
    picks = [order[(start + i) % len(order)] for i in range(k)]
    return picks


def schemas_for(names: list[str]) -> list[dict]:
    return [{"type": "function", "function": REAL_BY_NAME[n]} for n in names]


def build_prompt(names: list[str], mix: tuple = (6, 1, 1, 1, 1)) -> str:
    schemas = schemas_for(names)
    tdesc = json.dumps(schemas, ensure_ascii=False, indent=1)
    call, fail, multi, nocall, dev = mix
    total = sum(mix)
    items = []
    if call:
        items.append(f"{call} 条「需要调用」：提问像老爹随口说的（口语）；arguments 填对，必填参数都要给全")
    if fail:
        items.append(f"{fail} 条「失败跟进」：工具返回报错 JSON（如 {{\"ok\":false,\"error\":\"...\"}}）→ "
                     f"元亨如实说没成/不会假装成功（**禁止**\"已完成/搞定了/已经帮您\"）")
    if multi:
        items.append(f"{multi} 条「多轮」：调用→结果→用户再追问一句→元亨再答（多一对 user+assistant，不新增工具消息）")
    if nocall:
        items.append(f"{nocall} 条「不需要调用」：有工具但闲聊，直接回答，无 tool_calls")
    if dev:
        items.append(f"{dev} 条「开发任务派单」：用户要改代码/文件 → **不许瞎找文件**，"
                     f"回答末尾单独一行输出 `[[dev: 具体任务]]`（无 tool_calls）")
    body = "；\n".join(f"{chr(0x2460+i)}{s}" for i, s in enumerate(items))
    return f"""为「元亨」造工具调用 SFT 样本，输出纯 JSON 数组，共 {total} 条。

本批可用工具（**只能用这些名字，参数名必须与声明完全一致**）：
{tdesc}

每条固定格式（system 内容逐字照抄下面给出的 SYS）：
{{"messages":[
 {{"role":"system","content":"{SYSTEM}"}},
 {{"role":"user","content":"<自然中文提问>"}},
 {{"role":"assistant","tool_calls":[{{"id":"c1","type":"function","function":{{"name":"<工具名>","arguments":{{<参数对象>}}}}}}]}},
 {{"role":"tool","name":"<工具名>","content":"<该工具返回的 JSON 字符串>"}},
 {{"role":"assistant","content":"<元亨最终回答>"}}
],"tools":{tdesc}}}

构成（严格按此顺序）：
{body}。

硬要求：
- arguments 必须是 **JSON 对象**（不是字符串）；键只能用该工具声明里的参数名；
- 工具返回 content 是 JSON 字符串（可含中文）；
- 元亨最终回答 ≤40 字、口语、活泼、偶尔傲娇；**禁止**"根据查询结果/为您/以下是/好的，我帮您"等助手腔；
- 只输出 JSON 数组，不要解释、不要 markdown 代码块。"""


def parse_json_array(txt):
    s = txt.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.MULTILINE).strip()
    i, j = s.find("["), s.rfind("]")
    if i < 0 or j < 0:
        return []
    try:
        return json.loads(s[i:j + 1])
    except Exception:  # noqa: BLE001
        return []


def _arg_ok(name: str, args: dict) -> bool:
    fn = REAL_BY_NAME.get(name)
    if not fn:
        return False
    params = (fn.get("parameters") or {})
    props = set((params.get("properties") or {}).keys())
    required = set(params.get("required") or [])
    if not isinstance(args, dict):
        return False
    if not set(args.keys()) <= props:
        return False
    return required <= set(args.keys())


def valid(rec, names: list[str]) -> str:
    """Return "" if ok, else the reject reason."""
    ms = rec.get("messages") or []
    roles = [m.get("role") for m in ms]
    if "assistant" not in roles or "user" not in roles:
        return "无user/assistant"
    if ms[0].get("role") != "system" or ms[0].get("content") != SYSTEM:
        return "system不一致"
    calls = [m for m in ms if m.get("role") == "assistant" and m.get("tool_calls")]
    for m in calls:
        for tc in m["tool_calls"]:
            fn = tc.get("function") or {}
            if fn.get("name") not in names:
                return f"工具不在本批:{fn.get('name')}"
            if not _arg_ok(fn["name"], fn.get("arguments")):
                return f"参数不合法:{fn.get('name')}"
    tool_msgs = [m for m in ms if m.get("role") == "tool"]
    if tool_msgs and not calls:
        return "tool消息无调用"
    for tm in tool_msgs:
        if tm.get("name") not in names:
            return "tool消息名字非法"
    final = [m for m in ms if m.get("role") == "assistant" and m.get("content")]
    if not final:
        return "无最终回答"
    if not str(final[-1]["content"]).strip():
        return "空最终回答"
    if "tools" not in rec:
        return "缺tools字段"
    return ""


def classify(rec) -> str:
    ms = rec["messages"]
    has_call = any(m.get("role") == "assistant" and m.get("tool_calls") for m in ms)
    if not has_call:
        return "dev" if "[[dev:" in ms[-1]["content"] else "nocall"
    tool_msgs = [m for m in ms if m.get("role") == "tool"]
    if any('"ok":false' in str(m.get("content", "")).replace(" ", "") or "error" in str(m.get("content", "")).lower()
           for m in tool_msgs):
        return "failure"
    if sum(1 for m in ms if m.get("role") == "user") > 1:
        return "multiturn"
    return "call"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="真实注册表工具调用样本生成 v8")
    ap.add_argument("--batches", type=int, default=60)
    ap.add_argument("--seed", type=int, default=20260926)
    ap.add_argument("--mix", default="6,1,1,1,1",
                    help="每批构成 call,fail,multi,nocall,dev（和=每批条数）")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    mix = tuple(int(x) for x in args.mix.split(","))
    if len(mix) != 5 or sum(mix) < 1:
        print("[error] --mix 需 5 个整数")
        return 2
    out = Path(args.out)
    key = cr.load_key()
    if not key:
        print("[error] 缺 DEEPSEEK_API_KEY")
        return 2
    rng = random.Random(args.seed)
    order = list(REAL_BY_NAME)
    rng.shuffle(order)
    got, seen = [], set()
    stats = {"call": 0, "failure": 0, "multiturn": 0, "nocall": 0, "dev": 0}
    fail = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    usage_in = usage_out = 0
    for b in range(args.batches):
        names = pick_tools(order, b, rng)
        recs, err = [], "?"
        for attempt in range(2):
            try:
                txt, usage = ds_json(key, build_prompt(names, mix))
            except Exception as e:  # noqa: BLE001
                err = type(e).__name__
                time.sleep(2)
                continue
            usage_in += usage.get("prompt_tokens", 0)
            usage_out += usage.get("completion_tokens", 0)
            arr = parse_json_array(txt)
            if not arr:
                err = "解析失败"
                continue
            for rec in arr:
                if not isinstance(rec, dict):
                    continue
                why = valid(rec, names)
                if why:
                    err = why
                    continue
                fp = json.dumps(rec["messages"], ensure_ascii=False)
                if fp in seen:
                    continue
                seen.add(fp)
                rec["tools"] = schemas_for(names)
                rec["source"] = "tooluse"
                recs.append(rec)
            if len(recs) >= 8:
                break
        if len(recs) < 5:
            fail += 1
            print(f"[{b+1}/{args.batches}] 放弃({len(recs)}) :: {err}")
            continue
        for r in recs:
            stats[classify(r)] += 1
        got.extend(recs)
        with out.open("w", encoding="utf-8") as f:
            for r in got:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[{b+1}/{args.batches}] +{len(recs)} (累计 {len(got)}) 工具={'/'.join(names)}")
    st = {"total": len(got), **stats, "fail_batches": fail, "out": str(out),
          "tokens_in": usage_in, "tokens_out": usage_out}
    out.with_suffix(".stats.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(st, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
