#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导出稿自查（只读）：把 sft_v9_all.jsonl 当"外部交付物"重新验一遍。

检查项：
  A. 文件层：能否逐行 parse、字段是否恰好是 instruction/input/output(/meta)
  B. 配对层：len(input)==len(output)、每条 output 非空、instruction 非空
  C. 内容层：① 元亨自复读（同一记录内相邻 assistant 大段重复）
             ② 客服腔词残留（我这边/我接/我认/稳了/别指望）
             ③ 轮内 input 是否为空（opening 占位）
  D. 指纹层：content_hash 重复（同一内容进了多条）
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter
from difflib import SequenceMatcher

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "data", "finetune", "sft_v9_all.jsonl")
BANNED = ["我这边", "我接", "我认", "稳了", "很稳", "别指望"]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    n = parse_err = 0
    key_bad = pair_bad = out_empty = instr_empty = 0
    dup_in_round = empty_input = 0
    banned_hits = Counter()
    hash_seen = Counter()
    examples = []
    with io.open(P, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                rec = json.loads(line)
            except Exception as e:  # noqa: BLE001
                parse_err += 1
                continue
            extra = set(rec.keys()) - {"instruction", "input", "output", "meta"}
            if extra:
                key_bad += 1
            ins, inp, outp = rec.get("instruction"), rec.get("input"), rec.get("output")
            if not isinstance(inp, list) or not isinstance(outp, list) or len(inp) != len(outp):
                pair_bad += 1
                continue
            if not str(ins or "").strip():
                instr_empty += 1
            flat = []
            for i, o in enumerate(outp):
                a = str(o.get("assistant") or "")
                if not a.strip() and not o.get("tool_call"):
                    out_empty += 1
                flat.append(a)
                for b in BANNED:
                    if b in a:
                        banned_hits[b] += 1
                        if len(examples) < 3:
                            examples.append((lineno, i + 1, b, a[:70]))
                u = str(inp[i].get("user") or "")
                if not u.strip() and inp[i].get("type") == "opening":
                    empty_input += 1
            # 同记录内相邻 assistant 大段重复（元亨复读）
            for a, b in zip(flat, flat[1:]):
                if len(a) > 60 and len(b) > 60:
                    r = SequenceMatcher(None, a, b).ratio()
                    if r >= 0.7:
                        dup_in_round += 1
                        break
            h = (rec.get("meta") or {}).get("content_hash")
            if h:
                hash_seen[h] += 1

    dups = sum(v for v in hash_seen.values() if v > 1)
    print("=" * 74)
    print("导出稿自查：%s" % os.path.relpath(P, ROOT))
    print("=" * 74)
    print("记录数 %d ｜ JSON 解析失败 %d" % (n, parse_err))
    print("字段异常（出现 instruction/input/output/meta 之外的键）%d" % key_bad)
    print("配对不齐 %d ｜ instruction 空 %d ｜ output 空 %d" % (pair_bad, instr_empty, out_empty))
    print()
    print("① 同记录内元亨大段自复读（相似度≥0.7）：%d 条" % dup_in_round)
    print("② 客服腔词残留：%s" % (dict(banned_hits) or "无"))
    for e in examples:
        print("      L%d 第%d轮 [%s] %s" % e)
    print("③ opening 占位（input 为空的轮）：%d" % empty_input)
    print("④ content_hash 重复涉及的记录数：%d" % dups)
    print()
    ok = (parse_err == 0 and key_bad == 0 and pair_bad == 0 and instr_empty == 0
          and out_empty == 0 and dups == 0)
    print("结论：%s" % ("✅ 结构与去重全部通过" if ok else "⚠️ 上述非零项需处理"))
    if dup_in_round:
        print("      ※ 元亨自复读不是格式问题，是**内容质量问题**——需重写那 %d 条（记录了具体条数供后续处理）" % dup_in_round)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
