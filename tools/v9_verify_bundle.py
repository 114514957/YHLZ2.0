#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V9 训练包上机自检：**不吃 GPU、不下载模型**，30 秒内给出"能不能开训"的结论。

检查顺序：
  1. 必需文件是否齐（按 MANIFEST 校验 sha256 前 16 位）
  2. 数据条数与字段结构
  3. `tool_calls[].function.arguments` 必须是对象（不是 JSON 字符串）
     —— 2026-10-20 实测：字符串会让 Gemma 4 的 chat template 直接抛错，训练一开头就崩
  4. 依赖是否装齐（torch/transformers/peft/bitsandbytes/datasets）
  5. GPU 显存是否够（4-bit 加载实测约 9.0 GB，建议 ≥12 GB）
  6. 有 tokenizer 时：逐条跑 apply_chat_template，报告 token 分布与超长条数
     （无 tokenizer 则跳过，不阻断）

用法：
    python tools/verify_bundle.py
    python tools/verify_bundle.py --base google/gemma-4-E4B-it   # 顺带做模板检查
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FAIL = []
WARN = []


def ok(msg):
    print("  [OK]   " + msg)


def bad(msg):
    FAIL.append(msg)
    print("  [FAIL] " + msg)


def warn(msg):
    WARN.append(msg)
    print("  [warn] " + msg)


def sha16(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None, help="可选：基座路径或 HF id，用于模板检查")
    ap.add_argument("--max-seq-len", type=int, default=768)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("== 1. 文件完整性 ==")
    mp = os.path.join(ROOT, "MANIFEST.json")
    if not os.path.exists(mp):
        bad("缺 MANIFEST.json")
        man = {"files": {}, "data": {}}
    else:
        man = json.load(io.open(mp, encoding="utf-8"))
    for rel, info in (man.get("files") or {}).items():
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            bad("缺文件 %s" % rel)
            continue
        if sha16(p) != info.get("sha256_16"):
            bad("%s 校验和不符（文件被改过或传输损坏）" % rel)
        else:
            ok("%s（%d 字节）" % (rel, info.get("bytes", os.path.getsize(p))))

    print("\n== 2. 数据 ==")
    rows = {}
    for kind in ("train", "val", "test"):
        p = os.path.join(ROOT, "data", "%s.jsonl" % kind)
        if not os.path.exists(p):
            bad("缺 data/%s.jsonl" % kind)
            continue
        rs = [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]
        rows[kind] = rs
        exp = (man.get("data") or {}).get(kind)
        if exp is not None and exp != len(rs):
            bad("data/%s.jsonl 条数 %d ≠ MANIFEST 里的 %d" % (kind, len(rs), exp))
        else:
            ok("data/%-10s %5d 条" % (kind + ".jsonl", len(rs)))
        if not rs:
            bad("data/%s.jsonl 是空的" % kind)

    print("\n== 3. tool_calls.arguments 类型（会让模板崩的那处）==")
    bad_n = 0
    for kind, rs in rows.items():
        for r in rs:
            for m in r.get("messages") or []:
                for tc in m.get("tool_calls") or []:
                    arg = (tc.get("function") or {}).get("arguments")
                    if isinstance(arg, str):
                        bad_n += 1
    if bad_n:
        bad("有 %d 处 arguments 是字符串（会被 Gemma 模板拒收）" % bad_n)
    else:
        ok("全部 arguments 都是对象")

    print("\n== 4. 依赖 ==")
    for mod, minv in (("torch", None), ("transformers", None), ("peft", None),
                      ("bitsandbytes", None), ("datasets", None)):
        try:
            m = __import__(mod)
            ok("%-14s %s" % (mod, getattr(m, "__version__", "?")))
        except Exception as e:  # noqa: BLE001
            bad("缺依赖 %s（%s）—— 先 pip install -r requirements.txt" % (mod, e))
    try:
        import torch
        if torch.cuda.is_available():
            prop = torch.cuda.get_device_properties(0)
            gb = prop.total_memory / 1e9
            ok("GPU %s ｜ %.1f GB" % (prop.name, gb))
            if gb < 11.0:
                bad("显存 %.1f GB < 11 GB：4-bit 加载实测需 9.0 GB，加激活会 OOM，"
                    "建议换 ≥12 GB 的卡" % gb)
            elif gb < 16.0:
                warn("显存 %.1f GB，够但不宽裕；建议 batch_size=1 + seq 768" % gb)
        else:
            bad("torch 看不到 CUDA（驱动的 CUDA 版本与 torch 不匹配？）")
    except Exception:
        pass

    print("\n== 5. 模板与 token 分布 ==")
    base = a.base or json.load(io.open(
        os.path.join(ROOT, "config", "finetune_v9_cloud.json"), encoding="utf-8"))["base_model"]
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(base, trust_remote_code=True)
        counts, errs = [], 0
        for r in (rows.get("train") or [])[:600]:
            try:
                text = tok.apply_chat_template(r["messages"], tokenize=False,
                                               add_generation_prompt=False)
                counts.append(len(tok(text, add_special_tokens=False)["input_ids"]))
            except Exception:
                errs += 1
        if errs:
            bad("%d 条样本无法套用 chat template" % errs)
        if counts:
            counts.sort()
            n = len(counts)
            q = lambda k: counts[min(n - 1, int(n * k))]
            ok("token 中位 %d ｜p90 %d ｜p99 %d ｜最大 %d（抽样 %d 条）"
               % (counts[n // 2], q(0.9), q(0.99), counts[-1], n))
            over = sum(1 for c in counts if c > a.max_seq_len)
            if over:
                warn("%d 条超过 max_seq_len=%d（会被截断）" % (over, a.max_seq_len))
            else:
                ok("max_seq_len=%d 下零截断" % a.max_seq_len)
    except Exception as e:  # noqa: BLE001
        warn("跳过模板检查（tokenizer 不可用：%s）——不阻断，训练前会自然校验" % str(e)[:80])

    print("\n" + "=" * 60)
    if FAIL:
        print("结论：**不能开训**，%d 个问题：" % len(FAIL))
        for x in FAIL:
            print("  - " + x)
        return 1
    print("结论：**可以开训**（%d 项警告）" % len(WARN))
    for x in WARN:
        print("  - " + x)
    print("\n下一步：bash run.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
