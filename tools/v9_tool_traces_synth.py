"""工具轨迹重建：schema 忠实 + 防错误泛化/过拟合（ledger 0887）。

问题：真实轨迹只有 8 条（会背样例）；生成轨迹 v8 只覆盖 34/43 工具且无 simulation 标记。
做法：**只从真实注册表**（43 项）造轨迹，逐条标 `simulation: true`，并施加防过拟合控制：

  1) 覆盖：每个工具至少 1 个正例；每工具上限 12 条（防单工具主导）
  2) 场景：normal / missing-required(先问不调) / empty-result(诚实说没有) /
           error-handling(如实报错) / no-call(不该调) —— 正:负 ≈ 2:1
  3) 多样性：每场景 ≥3 种措辞模板；参数值来自占位池（**不写真实文件内容**，防记忆泄漏）
  4) 近重复：5-gram Jaccard > 0.8 丢弃
  5) 泛化评估：**留出 6 个工具**（默认 ledger_* 与 file_share 等写操作）完全不出现在训练集，
     用于测"没见过的工具会不会乱调/乱编参数"

输出：data/finetune/tool_use_v9_synth.jsonl + tool_synth_report.json
用法：python tools/v9_tool_traces_synth.py [--per-tool 10] [--holdout 6]
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "tool_registry" / "snapshot_latest.json"
OUT = ROOT / "data" / "finetune" / "tool_use_v9_synth.jsonl"
REPORT = ROOT / "cache" / "v9_materials_preparation" / "tool_synth_report.json"

SYSTEM = ("你是元亨——数字生命体，老爹的伙伴。工具只能调用真实注册表中的能力；"
          "缺参先问、查无直说、失败照实讲，不编工具、不编结果。")

VALUES = {
    "path": ["docs/notes.md", "docs/素材/黄金样本.md", "data/finetune/x.jsonl"],
    "file": ["docs/notes.md", "README.md"],
    "query": ["昨晚聊的素材", "记忆里关于勇气的段落", "上次的派单"],
    "q": ["素材", "勇气", "记忆"],
    "keyword": ["素材", "利贞", "勇气"],
    "name": ["老爹", "利贞", "素材"],
    "text": ["记一下：明天把素材清单发老爹", "今天把工具轨迹补到 200 条"],
    "content": ["记一下：明天把素材清单发老爹"],
    "group_id": ["1094579571", "855372167"],
    "user_id": ["2258374446"],
    "id": ["1", "42"],
    "entry_stamp": ["1"],
    "limit": [3, 5, 10],
    "count": [3, 5],
    "n": [3, 5],
    "action": ["list", "show"],
    "mode": ["auto"],
}
DEFAULT_VALUE = "value"


def placeholder(param: str):
    for key, vals in VALUES.items():
        if key in param.lower():
            return random.choice(vals)
    return DEFAULT_VALUE


def args_for(spec: dict) -> dict:
    out = {}
    for p in spec.get("properties") or []:
        out[p] = placeholder(p)
    for r in spec.get("required") or []:
        out.setdefault(r, placeholder(r))
    return out



# 每个工具的自然说法（2026-10-20 老爹：样例太机械，不像人话）
NATURAL = {
    "file_read": ["帮我看看 {path} 里写了啥", "读一下 {path}"],
    "file_list": ["列一下 {path} 里有什么", "看看 {path} 底下都有啥"],
    "file_share": ["把 {path} 发给老爹", "这个文件分享给老爹"],
    "file_download": ["先把这个文件下下来"],
    "memory_recall": ["我上次说过要买什么来着", "回忆一下关于{query}的事"],
    "memory_save": ["记一下：{text}", "存进记忆：{text}"],
    "memory_audit": ["看看我的记忆有没有问题"],
    "memory_profile": ["我的记忆画像现在什么样"],
    "memory_why": ["为什么我会记住{query}"],
    "memory_causal": ["查一下这条记忆的来龙去脉"],
    "ledger_add": ["记条台账：{text}"],
    "ledger_list": ["列一下最近的台账"],
    "ledger_search": ["台账里搜一下{query}"],
    "ledger_get": ["把台账 {id} 拿给我看"],
    "ledger_update": ["改一下台账 {id} 的标题"],
    "ledger_delete": ["把台账 {id} 删了"],
    "kb_add": ["这条加进知识库：{text}"],
    "kb_query": ["知识库里查一下{query}"],
    "diary_write": ["写日记：{text}"],
    "diary_list": ["看看最近的日记"],
    "diary_delete": ["把昨天那条日记删了"],
    "qq_export": ["把群 {group_id} 最近的消息导出"],
    "qq_process": ["把这批群聊处理一下"],
    "qq_digest": ["给我个群聊摘要"],
    "qq_status": ["QQ 现在什么状态"],
    "qq_summarize": ["总结一下今天的群聊"],
    "song_play": ["放首歌", "来一首"],
    "song_list": ["都有哪些歌"],
    "song_send": ["把这首发给老爹"],
    "system_time": ["现在几点了"],
    "runtime_status": ["你现在状态怎么样"],
    "web_search": ["帮我搜一下{query}"],
    "web_fetch": ["打开这个链接看看"],
    "member_profile": ["看看 {name} 的资料"],
    "skill_search": ["你有哪些技能"],
    "skill_add": ["这个流程记成技能"],
    "skill_feedback": ["这个技能用着不太行"],
    "task_plan": ["帮我排个计划"],
    "schedule_plan": ["明天几点提醒我"],
    "report_qq_weekly": ["给我出个 QQ 周报"],
}

WRITE_TOOLS = {"memory_save", "ledger_add", "ledger_delete", "ledger_update",
               "diary_write", "diary_delete", "kb_add", "skill_add", "song_send",
               "qq_runbatch", "qq_shutdown", "file_share"}

PHRASES = {
    "normal": ["帮我用{name}看一下{obj}", "用{name}处理一下{obj}", "{name} 跑一下，对象是{obj}"],
    "missing": ["直接用{name}处理吧", "{name} 别问了，直接办", "用{name}"],
}
OBJS = ["那个文件", "这条记录", "刚才那条", "上次那份"]


def obj_for(spec: dict) -> str:
    props = spec.get("properties") or []
    p = props[0] if props else "对象"
    return {"path": "那个文件", "query": "那条记忆", "text": "这条内容",
            "group_id": "那个群", "name": "那个名字"}.get(p, random.choice(OBJS))


def build(tool: str, spec: dict, scenario: str) -> dict | None:
    a = args_for(spec)
    required = list(spec.get("required") or [])
    obj = obj_for(spec)
    name = tool
    nat = NATURAL.get(name)
    vals = {"path": a.get("path", "docs/notes.md"),
            "query": a.get("query") or a.get("q") or a.get("keyword") or "素材",
            "text": a.get("text") or a.get("content") or "记一条",
            "id": a.get("id") or a.get("entry_stamp") or "1",
            "name": a.get("name") or "老爹",
            "group_id": a.get("group_id") or "1094579571"}
    if scenario == "normal":
        if nat:
            _tpl = random.choice(nat)
            _vals = dict(vals)
            if "：" in _tpl:
                _vals = {k: str(v).replace("：", "，") for k, v in _vals.items()}
            user = _tpl.format(**_vals)
        else:
            user = random.choice(PHRASES["normal"]).format(name=name, obj=obj)
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
                {"role": "assistant", "content": "",
                 "tool_calls": [{"id": "c1", "type": "function",
                                 "function": {"name": name,
                                              "arguments": json.dumps(a, ensure_ascii=False)}}]},
                {"role": "tool", "name": name, "content": "ok"},
                {"role": "assistant", "content": "办好了。"}]
    elif scenario == "missing":
        if not required:
            return None
        if nat:
            user = random.choice(nat).format(**{**vals, required[0]: ""}) if "{" in "".join(nat) else random.choice(nat)
        else:
            user = random.choice(PHRASES["missing"]).format(name=name)
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
                {"role": "assistant",
                 "content": f"{name} 得先给我 {required[0]}，不然我不瞎猜。"}]
    elif scenario == "empty":
        if name in WRITE_TOOLS:
            return None
        base = random.choice(nat).format(**vals) if nat else f"用 {name} 查 {obj}"
        user = base + "，查不到就直说"
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
                {"role": "assistant", "content": "",
                 "tool_calls": [{"id": "c1", "type": "function",
                                 "function": {"name": name,
                                              "arguments": json.dumps(a, ensure_ascii=False)}}]},
                {"role": "tool", "name": name, "content": "not found"},
                {"role": "assistant", "content": "没查到，这条我这边是空的，不编给你。"}]
    elif scenario == "error":
        base = random.choice(nat).format(**vals) if nat else f"{name} 报错了怎么办"
        user = base + ("，要是失败就照实告诉我" if name in WRITE_TOOLS
                       else "，要是报错就照实告诉我")
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
                {"role": "assistant", "content": "",
                 "tool_calls": [{"id": "c1", "type": "function",
                                 "function": {"name": name,
                                              "arguments": json.dumps(a, ensure_ascii=False)}}]},
                {"role": "tool", "name": name, "content": "ERROR: permission denied"},
                {"role": "assistant", "content": "没做成，报的是权限不足；要不换条路，要不你给我权限我再试。"}]
    else:  # no-call（由独立列表生成，不走本函数）
        return None
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
                {"role": "assistant", "content": "在。想说啥就说，我在听。"}]
    return {"messages": msgs, "simulation": True, "generated": True,
            "tool": tool, "scenario": scenario,
            "source": f"toolsynth:{scenario}",
            "source_id": f"synth#{tool}#{scenario}",
            "group_id": f"sim:{tool}:{scenario}",
            "license": "own", "content_hash": ""}


def grams(text: str, n: int = 5) -> set[str]:
    t = "".join(text.split())
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    random.seed(20261020)
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-tool", type=int, default=10)
    ap.add_argument("--holdout", type=int, default=6)
    args = ap.parse_args()
    snap = json.loads(SNAP.read_text(encoding="utf-8"))
    tools = {t["name"]: t for t in snap["tools"]}
    names = sorted(tools)

    # 留出工具：优先"写操作/危险"类，测零样本选择与不乱调
    prefer = [n for n in names if any(k in n for k in
              ("ledger_add", "ledger_delete", "ledger_update", "file_share",
               "qq_shutdown", "qq_runbatch", "skill_add", "song_send"))]
    holdout = (prefer or names)[: args.holdout]
    train_tools = [n for n in names if n not in holdout]

    scenarios = ["normal", "missing", "empty", "error", "no-call"]
    rows, seen, by_tool = [], set(), {}
    for tool in train_tools:
        spec = tools[tool]
        n = 0
        for sc in scenarios:
            reps = 2 if sc in ("normal", "missing") else 1
            for _ in range(reps):
                if n >= args.per_tool:
                    break
                rec = build(tool, spec, sc)
                if not rec:
                    continue
                text = json.dumps(rec["messages"], ensure_ascii=False)
                g = grams(json.dumps(rec["messages"][1:], ensure_ascii=False))
                dup = any(len(g & s) / max(1, len(g | s)) > 0.8 for s in seen)
                if dup:
                    continue
                seen.add(frozenset(g))
                rec["content_hash"] = hashlib.sha256(text.encode()).hexdigest()[:16]
                rows.append(rec)
                n += 1
        by_tool[tool] = n

    # —— no-call 负例：独立、多样、与工具无关（防见啥都调） ——
    CASUAL = ["在吗", "今天好累", "陪我聊两句", "你在干嘛", "晚安",
              "我今天不想干活", "外面下雨了", "有点饿", "你睡了吗",
              "周末想去爬山", "这歌好听", "给我讲个冷笑话", "烦死了",
              "我想躺一会儿", "今天吃什么", "你猜我在想啥", "好无聊",
              "刚刚做了个梦", "我头疼", "陪我发会儿呆", "你在忙吗",
              "我回来了", "天黑了", "想喝点热的"]
    for i, line in enumerate(CASUAL):
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": line},
                {"role": "assistant", "content": "在。" + ("想说就说，我听着。" if i % 2 else "")}]
        text = json.dumps(msgs, ensure_ascii=False)
        g = frozenset(grams(json.dumps(msgs[1:], ensure_ascii=False)))
        if any(len(g & s) / max(1, len(g | s)) > 0.8 for s in seen):
            continue
        seen.add(g)
        rows.append({"messages": msgs, "simulation": True, "generated": True,
                     "tool": "(none)", "scenario": "no-call",
                     "source": "toolsynth:no-call", "source_id": f"synth#nocall#{i}",
                     "group_id": f"sim:nocall:{i}", "license": "own",
                     "content_hash": hashlib.sha256(text.encode()).hexdigest()[:16]})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    rep = {"rows": len(rows), "tools_total": len(names),
           "tools_in_train": len(train_tools), "holdout_tools": holdout,
           "per_tool": by_tool, "simulation": True,
           "anti_overfit": {
               "cap_per_tool": args.per_tool,
               "near_dup_jaccard": 0.8,
               "pos_neg_ratio_target": "2:1",
               "placeholder_values_only": True,
               "holdout_for_zero_shot_eval": len(holdout)},
           "file": str(OUT.relative_to(ROOT))}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("rows", "tools_total", "tools_in_train",
                                          "holdout_tools")}, ensure_ascii=False, indent=1))
    print(f"[report] {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
