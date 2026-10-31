#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修映射后 103 条记录的"收尾话"：让元亨的回答与新工具的实际返回一致。

问题：机械映射只换了工具名、参数、返回值，**元亨最后那句还是照旧工具说的**
（如 qq_status→runtime_status 后还说「三条白名单群，候选12」），
训上去等于教模型**无视工具结果编答案**，比少数据更糟。

做法：把新工具的真实返回交给模型，**只改最后一条 assistant 回答**，
让它严格按返回内容说；前面的 user / 调用 / tool 结果一律不动。

用法：
    python tools/v9_fix_remap_answers.py --apply
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

SYS = (
    "你在修一条「元亨调用工具」的训练样本。只输出元亨的那一句回答，不解释。\n"
    "【问题】这条样本的工具调用被换成了新的，但元亨的最后一句还是在说**旧结果**里的数字和东西。\n"
    "【要求】\n"
    "· **严格按给定的工具返回内容说话**：返回里有什么就说什么，没有的一个字都不许编。\n"
    "· 如果返回里没有具体数字，就不许出现数字。\n"
    "· 保持元亨口吻：活泼、傲娇、话短、有起伏；自称 我/咱/本小姐/老娘 切换。\n"
    "· 一到两句就够，别写成汇报。禁止列表、括号动作、Markdown、助手腔。\n"
    "· 禁词：我这边、我接、我认、稳了、很稳、别指望；不许说「理论上来说」。\n"
)


def load_key() -> str:
    from tools import scene_v8 as sv
    return sv.load_key()


def ds_call(key: str, user: str) -> str:
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": user}],
        "temperature": 0.5, "max_tokens": 400, "stream": False,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())["choices"][0]["message"].get("content", "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--in", dest="src", default="data/finetune/tool_use_v8_remapped.jsonl")
    ap.add_argument("--out", default="data/finetune/tool_use_v8_final.jsonl")
    a = ap.parse_args()

    rows = [json.loads(x) for x in io.open(a.src, encoding="utf-8") if x.strip()]
    key = load_key()
    fixed = skipped = 0
    out = []
    for r in rows:
        msgs = r.get("messages") or []
        # 找最后一条有 tool_calls 的 assistant 与它后面对应的 tool 结果
        idx_call = None
        for i, m in enumerate(msgs):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                idx_call = i
        if idx_call is None:
            out.append(r)
            skipped += 1
            continue
        # 是否为新映射工具（拿 runtime_status/report_qq_weekly/kb_add/skill_search 之一）
        # 2026-10-20：**只处理真正被映射过的记录**（带 remapped_from 标记）。
        # 不带标记的是本来就用现行工具、回答也本来就对的，改了反而会坏。
        if not r.get("remapped_from"):
            out.append(r)
            skipped += 1
            continue
        names = {(tc.get("function") or {}).get("name")
                 for tc in msgs[idx_call].get("tool_calls") or []}
        if not names & {"runtime_status", "report_qq_weekly", "kb_add", "skill_search"}:
            out.append(r)
            skipped += 1
            continue
        tool_res = ""
        idx_tool = None
        for j, m in enumerate(msgs[idx_call + 1:], start=idx_call + 1):
            if m.get("role") == "tool":
                c = m.get("content")
                tool_res = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                idx_tool = j
                break
        if not tool_res or idx_tool is None:
            out.append(r)
            skipped += 1
            continue
        # 2026-10-20 修：**所有跟在该工具结果之后的 assistant 回答都要改**，
        # 不能只改最后一条。实测多轮记录里中间那条仍是旧结果
        #（「整完啦，九个大主题」← 新返回里根本没有主题数）。
        targets = [j for j, m in enumerate(msgs)
                   if j > idx_tool and m.get("role") == "assistant"
                   and (m.get("content") or "").strip() and not m.get("tool_calls")]
        if not targets:
            out.append(r)
            skipped += 1
            continue
        user_q = next((m.get("content") or "" for m in msgs if m.get("role") == "user"), "")
        ok_any = False
        for j in targets:
            prompt = ("用户问：%s\n\n调用的工具：%s\n工具返回：%s\n\n旧回答（与新结果不符，要重写）：%s\n\n"
                      "请只输出重写后的元亨回答。"
                      % (user_q[:120], "/".join(sorted(names)), tool_res[:300],
                         (msgs[j].get("content") or "")[:160]))
            try:
                new = ds_call(key, prompt)
            except Exception as exc:  # noqa: BLE001
                print("  失败 %s" % exc)
                continue
            new = new.strip().strip('"').replace("**", "")
            if len(new) < 6:
                continue
            r["messages"][j] = {"role": "assistant", "content": new}
            ok_any = True
        if ok_any:
            fixed += 1
        else:
            skipped += 1
        out.append(r)
        if fixed % 20 == 0:
            print("  已修 %d 条" % fixed)

    print("\n改写收尾话 %d 条｜跳过 %d 条｜共 %d" % (fixed, skipped, len(rows)))
    if a.apply:
        io.open(a.out, "w", encoding="utf-8").write(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n")
        print("已写 ->", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
