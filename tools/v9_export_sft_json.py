#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导出严格的 instruction / input / output JSON（老爹 2026-10-14 要求）。

## 格式契约（严格版）

每条记录 = **一个 JSON 对象**，字段固定三件套 + 元数据：

```json
{
  "instruction": "<元亨的身份与说话规则>",          // 字符串，非空
  "input": [                                         // 数组：按顺序的输入项，非空
    {"user": "<老爹/别人的话>"},
    {"user": "<下一句>"},
    {"user": "<工具返回>", "type": "tool_result", "name": "<工具名>"}
  ],
  "output": [                                        // 数组：与 input **严格一一对应**，长度必须相等
    {"assistant": "<元亨的话>"},
    {"assistant": "<元亨的话>"},
    {"assistant": "", "tool_call": {"name": "...", "arguments": {...}}}
  ],
  "meta": { ... }                                    // 合规留痕，训练时可忽略
}
```

**"严格对应"的判据（脚本会验）**：
1. `len(input) == len(output)`；
2. `input[i]` 与 `output[i]` 是同一轮——即"对第 i 条输入，元亨的第 i 条回应"；
3. 不允许空 output（`assistant` 空且无 `tool_call` 视为坏数据）；
4. 多轮不压扁：一块里有几轮就出几个 input/output 配对。

**向后兼容**：原 `messages` 数组仍完整保留在 `meta.original_messages`（可用 `--no-original` 关掉）。

用法：
    python tools/v9_export_sft_json.py --in data/finetune/sft_persona_v8r4t_train.jsonl --out data/finetune/sft_v9_train
    # 产物：<out>.jsonl（每行一条）+ <out>.array.json（数组版，便于肉眼看）
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "finetune")


def to_io(rec: dict, keep_original: bool = True) -> tuple[dict | None, str]:
    """messages → instruction/input/output。返回 (record, 拒绝原因)。"""
    msgs = rec.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return None, "无 messages"

    instruction = ""
    inputs: list[dict] = []
    outputs: list[dict] = []
    pending_user: list[dict] = []      # 累积到下一个 assistant 之前的输入项

    for m in msgs:
        role = m.get("role")
        content = m.get("content")
        content = "" if content is None else str(content)

        if role == "system":
            if not instruction:
                instruction = content
            else:
                # 块内额外 system（如"（虚构小剧场）"）→ 作为该轮的输入标记
                pending_user.append({"user": content, "type": "scene_marker"})
            continue

        if role in ("user", "tool"):
            item = {"user": content}
            if role == "tool":
                item["type"] = "tool_result"
                if m.get("name"):
                    item["name"] = m["name"]
            pending_user.append(item)
            continue

        if role == "assistant":
            tcs = m.get("tool_calls") or []
            out: dict = {"assistant": content}
            if tcs:
                tc = tcs[0].get("function", {}) if isinstance(tcs[0], dict) else {}
                name = tc.get("name") or ""
                raw_args = tc.get("arguments")
                if isinstance(raw_args, str):
                    try:
                        raw_args = json.loads(raw_args)
                    except Exception:
                        pass
                out["tool_call"] = {"name": name, "arguments": raw_args}
                if len(tcs) > 1:
                    out["tool_calls_extra"] = [t.get("function", {}) for t in tcs[1:]]
            # 对应：把累积的输入并成一项（若多条，取首条为 user，其余作为 context）
            if not pending_user:
                # assistant 领先于任何 user（裸开局）→ 补一个空输入位，保证严格对应
                pending_user.append({"user": "", "type": "opening"})
            head = dict(pending_user[0])
            if len(pending_user) > 1:
                head["context"] = [dict(x) for x in pending_user[1:]]
            inputs.append(head)
            outputs.append(out)
            pending_user = []
            continue

        # 其它 role：忽略并在计数里体现（由调用方统计）
    # 结尾若有未配对的输入 → 丢掉（不产生半条记录）
    if len(inputs) != len(outputs) or not inputs:
        return None, "配对不齐或空"

    # 严格校验
    for i, o in enumerate(outputs):
        if not str(o.get("assistant") or "").strip() and not o.get("tool_call"):
            return None, "第%d轮 output 为空" % (i + 1)

    out_rec = {
        "instruction": instruction,
        "input": inputs,
        "output": outputs,
        "meta": {
            "source": rec.get("source"),
            "source_id": rec.get("source_id"),
            "group_id": rec.get("group_id"),
            "content_hash": rec.get("content_hash"),
            "safety_labels": rec.get("safety_labels"),
            "consent_status": rec.get("consent_status"),
            "weight": rec.get("weight"),
            "annotator_exec": rec.get("annotator_exec"),
            "annotator_review": rec.get("annotator_review"),
        },
    }
    if rec.get("tools"):
        out_rec["meta"]["tools_schema"] = rec["tools"]
    if keep_original:
        out_rec["meta"]["original_messages"] = msgs
    return out_rec, ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", action="append", required=True)
    ap.add_argument("--out", required=True, help="输出前缀（不含扩展名）")
    ap.add_argument("--no-original", action="store_true", help="不保留 original_messages（体积小一半）")
    ap.add_argument("--array", action="store_true", default=True, help="同时写数组版")
    args = ap.parse_args()

    rows: list[dict] = []
    n_read = 0
    for p in args.inputs:
        if not os.path.exists(p):
            print("跳过（不存在）：%s" % p)
            continue
        with io.open(p, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                n_read += 1
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass

    ok: list[dict] = []
    rejects = Counter()
    stats = Counter()
    for r in rows:
        rec, why = to_io(r, keep_original=not args.no_original)
        if rec is None:
            rejects[why] += 1
            continue
        ok.append(rec)
        stats["轮数%d" % len(rec["input"])] += 1
        if any(o.get("tool_call") for o in rec["output"]):
            stats["含工具调用"] += 1
        if rec["meta"].get("weight") == 1.0:
            stats["核心权重1.0"] += 1

    # 严格校验（二次独立检查）
    bad = 0
    for rec in ok:
        if len(rec["input"]) != len(rec["output"]):
            bad += 1
        if not rec["instruction"].strip():
            bad += 1
        for i, o in enumerate(rec["output"]):
            if "assistant" not in o:
                bad += 1

    out_jsonl = os.path.join(OUT_DIR, args.out + ".jsonl") if not os.path.isabs(args.out) \
        else args.out + ".jsonl"
    out_arr = out_jsonl.replace(".jsonl", ".array.json")
    os.makedirs(os.path.dirname(out_jsonl), exist_ok=True)
    with io.open(out_jsonl, "w", encoding="utf-8") as fh:
        for rec in ok:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if args.array:
        with io.open(out_arr, "w", encoding="utf-8") as fh:
            json.dump(ok, fh, ensure_ascii=False, indent=1)

    print("=" * 74)
    print("导出严格 instruction/input/output JSON")
    print("=" * 74)
    print("读入 %d 条 ｜ 成功 %d 条 ｜ 拒绝 %d 条" % (n_read, len(ok), sum(rejects.values())))
    for k, v in rejects.most_common():
        print("   拒绝原因：%-22s %d" % (k, v))
    print("配对校验：不齐/缺 instruction 的记录 = %d %s" % (bad, "（应为 0）" if bad == 0 else "⚠️"))
    print("轮数分布（前 8）：%s" % dict(stats.most_common(8)))
    print("产物：\n   %s" % os.path.relpath(out_jsonl, ROOT))
    if args.array:
        print("   %s" % os.path.relpath(out_arr, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
