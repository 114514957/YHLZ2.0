"""Generate tool-use SFT trajectories (tool-agnostic, randomized schemas).

Output: data/finetune/tool_use_v6.jsonl  {messages, tools, source}
"""
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools.cloud_rewrite as cr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "finetune" / "tool_use_v6.jsonl"

_SYS_TASK = "你是数据工程师，严格按用户给定格式输出 JSON，不加任何解释。"


def ds_json(key, user, max_tokens=6000, temperature=0.9):
    """DS 调用（长输出 + 关思考）；cr.ds_chat 的 900 token 会截断。"""
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

TOOL_POOL = [
    ("get_time", "获取指定时区的当前时间", {"tz": "string"}),
    ("lookup_weather", "查询城市天气", {"city": "string", "day": "string"}),
    ("calc_expr", "计算数学表达式", {"expr": "string"}),
    ("search_notes", "按关键词检索笔记", {"query": "string"}),
    ("find_file", "按名字查找文件", {"name": "string"}),
    ("translate_text", "翻译文本", {"text": "string", "to": "string"}),
    ("convert_units", "单位换算", {"value": "number", "from": "string", "to": "string"}),
    ("read_ledger", "检索项目台账记录", {"keyword": "string"}),
    ("list_events", "列出某天的日程", {"date": "string"}),
    ("get_quote", "查询股票行情", {"symbol": "string"}),
    ("send_msg", "给某人发消息", {"to": "string", "text": "string"}),
    ("run_script", "运行一个脚本", {"path": "string"}),
    ("hash_text", "计算文本摘要", {"text": "string", "algo": "string"}),
    ("random_pick", "从候选中随机选一个", {"items": "string"}),
    ("count_words", "统计文本字数", {"text": "string"}),
]

SYS = ("你是元亨——老爹的伙伴，活泼、傲娇、话短；像朋友说话，禁止助手腔/报告腔。"
       "需要事实/数据/操作时先用工具，拿到结果再用自己的口吻短答，绝不编造。")

N_BATCH = 40      # 批次数
PER_BATCH = 10    # 每批条数


def rand_toolset():
    return random.sample(TOOL_POOL, random.randint(2, 4))


def to_schema(t):
    name, desc, props = t
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object",
                       "properties": {k: {"type": v} for k, v in props.items()},
                       "required": list(props.keys())}}}


def build_prompt(tools):
    tdesc = json.dumps([to_schema(t) for t in tools], ensure_ascii=False, indent=1)
    names = "、".join(t[0] for t in tools)
    return f"""为「元亨」（中文对话AI：活泼、傲娇、话短、口语）造 SFT 样本，教它使用工具。

可用工具（随机名，勿换成别的名字）：{names}
工具 JSON Schema：
{tdesc}

请输出 JSON 数组，共 10 条。**8 条"需要调用工具"** + **2 条"有工具但不需要调用"**。
需要调用的格式（严格）：
{{"messages":[
 {{"role":"system","content":"{SYS}"}},
 {{"role":"user","content":"<一句自然的中文提问>"}},
 {{"role":"assistant","tool_calls":[{{"id":"c1","type":"function","function":{{"name":"<工具名>","arguments":{{<参数对象>}}}}}}]}},
 {{"role":"tool","name":"<工具名>","content":"<该工具返回的 JSON 字符串>"}},
 {{"role":"assistant","content":"<元亨口吻的最终回答，≤30字，短、俏、偶尔傲娇>"}}
],"tools":{tdesc}}}
不需要调用的格式：同上但 assistant 直接给 content（没有 tool_calls/tool 两条）。

硬要求：
- arguments 必须是 **JSON 对象**（不是字符串）；
- 最终回答必须元亨口吻（短、口语），**禁止**"根据查询结果""为您""以下是"等助手腔；
- 工具返回值要像真实 JSON；只输出 JSON 数组，不要解释、不要 markdown 代码块。"""


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


def valid(rec):
    ms = rec.get("messages") or []
    roles = [m.get("role") for m in ms]
    if "assistant" not in roles or "user" not in roles:
        return False
    for m in ms:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                if not isinstance(tc.get("function", {}).get("arguments"), dict):
                    return False
    return "tools" in rec


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    key = cr.load_key()
    if not key:
        print("[error] 缺 DEEPSEEK_API_KEY")
        return 2
    got, fail, seen = [], 0, set()
    for b in range(N_BATCH):
        tools = rand_toolset()
        try:
            txt, _ = ds_json(key, build_prompt(tools))
        except Exception as e:  # noqa: BLE001
            fail += 1
            print("[err]", type(e).__name__)
            continue
        arr = parse_json_array(txt)
        if not arr:
            fail += 1
            print(f"[{b+1}] 解析失败")
            continue
        added = 0
        for rec in arr:
            if not isinstance(rec, dict) or not valid(rec):
                continue
            fp = json.dumps(rec["messages"], ensure_ascii=False)
            if fp in seen:
                continue
            seen.add(fp)
            rec["tools"] = [to_schema(t) for t in tools]
            rec["source"] = "tooluse"
            got.append(rec)
            added += 1
        print(f"[{b+1}/{N_BATCH}] +{added} (累计 {len(got)})")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in got:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    call = sum(1 for r in got if any(m.get("tool_calls") for m in r["messages"]))
    print(f"完成: {len(got)} 条 ({call} 需调用 / {len(got)-call} 不需调用), 失败批次 {fail}")
    print("->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
