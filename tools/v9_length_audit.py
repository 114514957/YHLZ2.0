#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V9 训练集长度审计（只读）：真实 token 长度分布 + 截断率 + 监督 token 量。

用本地 Gemma tokenizer（自实现 BPE，见 tools/v9_token_measure.py）逐条测
data/finetune/*.jsonl 的整段长度与 assistant 监督长度，给出：
  · 各分位长度、超 seq 截断条数与比例（v8 用 seq=2048）
  · 被截掉的监督 token 量（截断位置之后仍属 assistant 的部分）
  · 监督 token 总量（用于算"每遍多少监督 token"）

用法：python tools/v9_length_audit.py [--seq 2048] [--json 输出路径]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v9_token_measure import GemmaBPE, TOKENIZER_PATH  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINETUNE = os.path.join(PROJECT_ROOT, "data", "finetune")
FILES = ["sft_persona_v8r4.jsonl", "tool_use_v8.jsonl"]


def encode_len(tok: GemmaBPE, text: str) -> int:
    return tok.count(text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq", type=int, default=2048)
    ap.add_argument("--json", default=os.path.join(
        PROJECT_ROOT, "cache", "v9_materials_preparation", "20261013", "length_audit.json"))
    args = ap.parse_args()

    tok = GemmaBPE(TOKENIZER_PATH)
    report = {"seq": args.seq, "tokenizer": TOKENIZER_PATH, "files": []}

    for name in FILES:
        p = os.path.join(FINETUNE, name)
        if not os.path.exists(p):
            print("跳过（不存在）：%s" % name)
            continue
        lens, asst_lens, cut_count, cut_asst_tokens = [], [], 0, 0
        total_asst = 0
        n = 0
        with io.open(p, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msgs = rec.get("messages") or []
                if not msgs:
                    continue
                n += 1
                full = 0
                asst = 0
                for m in msgs:
                    c = m.get("content") or ""
                    if m.get("tool_calls"):
                        c = c + json.dumps(m["tool_calls"], ensure_ascii=False)
                    t = encode_len(tok, str(c))
                    full += t
                    if m.get("role") == "assistant":
                        asst += t
                lens.append(full)
                asst_lens.append(asst)
                total_asst += asst
                if full > args.seq:
                    cut_count += 1
                    # 粗略：超出部分若落在 assistant 侧即为损失
                    # 用比例估算（无法精确切分时不假装精确）
                    cut_asst_tokens += int(asst * (full - args.seq) / full)
        lens.sort()
        asst_lens.sort()
        q = lambda a, p: a[min(len(a) - 1, int(len(a) * p))] if a else 0
        row = {
            "file": name, "records": n,
            "full_tokens_total": sum(lens), "assistant_tokens_total": total_asst,
            "len_p50": q(lens, 0.5), "len_p90": q(lens, 0.9), "len_p99": q(lens, 0.99),
            "len_max": lens[-1] if lens else 0,
            "asst_p50": q(asst_lens, 0.5), "asst_p90": q(asst_lens, 0.9),
            "asst_max": asst_lens[-1] if asst_lens else 0,
            "over_seq_records": cut_count,
            "over_seq_ratio": round(cut_count / n, 4) if n else 0,
            "est_truncated_assistant_tokens": cut_asst_tokens,
        }
        report["files"].append(row)
        print("=" * 74)
        print("文件 %s（%d 条）" % (name, n))
        print("  整段长度：p50=%d p90=%d p99=%d max=%d" % (row["len_p50"], row["len_p90"], row["len_p99"], row["len_max"]))
        print("  监督长度：p50=%d p90=%d max=%d" % (row["asst_p50"], row["asst_p90"], row["asst_max"]))
        print("  超 seq=%d 的记录：%d 条（%.1f%%），估算被截掉的监督 token ≈ %d"
              % (args.seq, cut_count, 100 * row["over_seq_ratio"], cut_asst_tokens))
        print("  监督 token 合计：%d（每遍）" % total_asst)

    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with io.open(args.json, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print("\n结果已存：%s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
