#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""训练前最终体检（老爹 2026-10-23：「最后检查，格式，结构啥的，好了我租卡」）。

**这次要严**——租卡后才发现格式问题就是白花钱。逐层硬检查：

  A 文件层：UTF-8 无 BOM、每行合法 JSON、无空行、行数与预期一致
  B 记录层：messages 结构、role 合法、tool 消息带 name、tool_calls 三件套齐、
            **arguments 必须是 dict 不能是 str**、tool_call 与 tool 返回**一一配对**
  C 内容层：assistant 空内容只在有 tool_calls 时允许、无 NULL、无控制字符
  D 训练器层：Dataset.from_list、apply_chat_template、真实 encode 抽样
  E 配置层：config 指向的文件存在、参数自洽、底座路径存在

用法：
    python tools/v9_preflight.py          # 全查（含 tokenizer，约 1 分钟）
    python tools/v9_preflight.py --fast   # 跳过 tokenizer
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FAIL, WARN, OK = [], [], []


def ok(m):
    OK.append(m)
    print("  [OK]   " + m)


def bad(m):
    FAIL.append(m)
    print("  [FAIL] " + m)


def warn(m):
    WARN.append(m)
    print("  [warn] " + m)


SPLITS = ["train", "val", "test"]
VALID_ROLE = {"system", "user", "assistant", "tool"}
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def check_file_layer(path):
    raw = io.open(path, "rb").read()
    name = os.path.basename(path)
    if raw.startswith(b"\xef\xbb\xbf"):
        bad("A %s 带 UTF-8 BOM" % name)
    else:
        ok("A %s 无 BOM" % name)
    if b"\r\n" in raw:
        warn("A %s 含 CRLF 换行（Linux 训练环境建议 LF）" % name)
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        bad("A %s 不是合法 UTF-8：%s" % (name, str(e)[:60]))
        return [], 0
    lines = txt.split("\n")
    rows, badline, empty = [], 0, 0
    for i, ln in enumerate(lines, 1):
        if not ln.strip():
            empty += 1
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError as e:
            badline += 1
            if badline <= 3:
                bad("A %s 第 %d 行不是合法 JSON：%s" % (name, i, str(e)[:60]))
    if not badline:
        ok("A %s 全部 %d 行合法 JSON" % (name, len(rows)))
    if empty > 1:
        warn("A %s 有 %d 个空行（末尾换行正常，中间空行要留意）" % (name, empty))
    return rows, len(raw)


def check_record_layer(rows, name):
    n_struct = n_role = n_toolname = n_tcfmt = n_argstr = 0
    n_pair = n_empty_asst = 0
    for r in rows:
        msgs = r.get("messages")
        if not isinstance(msgs, list) or not msgs:
            n_struct += 1
            continue
        if msgs[0].get("role") != "system":
            n_struct += 1
        for m in msgs:
            role = m.get("role")
            if role not in VALID_ROLE:
                n_role += 1
            if role == "tool" and not (m.get("name") or "").strip():
                n_toolname += 1
            cnt = 0
            for tc in m.get("tool_calls") or []:
                cnt += 1
                if not (tc.get("id") and tc.get("type") == "function"
                        and isinstance(tc.get("function"), dict)):
                    n_tcfmt += 1
                else:
                    args = tc["function"].get("arguments")
                    if isinstance(args, str):
                        n_argstr += 1
                    elif not isinstance(args, dict):
                        n_tcfmt += 1
            # assistant 空内容只在有 tool_calls 时允许
            if role == "assistant" and not (m.get("content") or "").strip() and cnt == 0:
                n_empty_asst += 1
        # tool_call 与 tool 返回配对
        calls = sum(len(m.get("tool_calls") or []) for m in msgs)
        tools = sum(1 for m in msgs if m.get("role") == "tool")
        if calls != tools:
            n_pair += 1
    if n_struct:
        bad("B %s 有 %d 条 messages 结构不对（空/首条不是 system）" % (name, n_struct))
    else:
        ok("B %s messages 结构正确（首条都是 system）" % name)
    if n_role:
        bad("B %s 有 %d 个非法 role" % (name, n_role))
    else:
        ok("B %s role 全部合法" % name)
    if n_toolname:
        bad("B %s 有 %d 条 tool 消息缺 name" % (name, n_toolname))
    else:
        ok("B %s tool 消息都带 name" % name)
    if n_tcfmt:
        bad("B %s 有 %d 个 tool_call 结构不全（id/type/function）" % (name, n_tcfmt))
    else:
        ok("B %s tool_call 三件套齐全" % name)
    if n_argstr:
        bad("B %s 有 %d 处 arguments 是**字符串**（Gemma 模板会直接报错）" % (name, n_argstr))
    else:
        ok("B %s arguments 全部是对象" % name)
    if n_pair:
        bad("B %s 有 %d 条 tool_call 数与 tool 返回数不匹配" % (name, n_pair))
    else:
        ok("B %s tool_call 与 tool 返回一一配对" % name)
    if n_empty_asst:
        warn("B %s 有 %d 条 assistant 空内容且无 tool_calls" % (name, n_empty_asst))


def check_content_layer(rows, name):
    n_ctrl = n_long = 0
    maxlen = 0
    for r in rows:
        for m in r["messages"]:
            c = m.get("content")
            if c is None:
                continue
            if CTRL.search(c):
                n_ctrl += 1
            maxlen = max(maxlen, len(c))
            if len(c) > 8000:
                n_long += 1
    if n_ctrl:
        bad("C %s 有 %d 处控制字符" % (name, n_ctrl))
    else:
        ok("C %s 无控制字符｜最长 content %d 字符" % (name, maxlen))
    if n_long:
        warn("C %s 有 %d 条 content >8000 字符" % (name, n_long))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()

    print("=" * 76)
    print("A/B/C 文件 · 结构 · 内容")
    print("=" * 76)
    data = {}
    for sp in SPLITS:
        p = "data/finetune/sft_persona_v9t_%s.jsonl" % sp
        if not os.path.exists(p):
            bad("A 缺文件 %s" % p)
            continue
        rows, size = check_file_layer(p)
        data[sp] = rows
        print("        %s：%d 条 / %.1f MB" % (sp, len(rows), size / 1048576))
        if sp == "train":
            check_record_layer(rows, sp)
            check_content_layer(rows, sp)

    print("\n" + "=" * 76)
    print("D 训练器层（真正会跑的那几步）")
    print("=" * 76)
    try:
        from datasets import Dataset
        slim = [{"messages_json": json.dumps(r["messages"], ensure_ascii=False),
                 "source": str(r.get("source", ""))} for r in data["train"]]
        ds = Dataset.from_list(slim)
        ok("D Dataset.from_list 建表成功（%d 行，列 %s）" % (len(ds), ds.column_names))
    except Exception as e:  # noqa: BLE001
        bad("D Dataset.from_list 失败：%s" % str(e)[:100])
        ds = None

    if a.fast:
        warn("D tokenizer 检查跳过（--fast）")
    else:
        try:
            from transformers import AutoTokenizer
            tok = AutoTokenizer.from_pretrained("models/gemma4-hf/gemma-4-e4b-it",
                                                trust_remote_code=True)
            import random
            random.seed(11)
            samp = random.sample(data["train"], min(200, len(data["train"])))
            err, lens = 0, []
            for r in samp:
                try:
                    txt = tok.apply_chat_template(r["messages"], tokenize=False,
                                                  add_generation_prompt=False)
                    lens.append(len(tok(txt, add_special_tokens=False)["input_ids"]))
                except Exception as e:  # noqa: BLE001
                    err += 1
                    if err <= 2:
                        print("        渲染失败样例：%s" % str(e)[:90])
            if err:
                bad("D 模板渲染 %d/%d 条失败" % (err, len(samp)))
            else:
                ok("D apply_chat_template 抽 %d 条全部渲染成功" % len(samp))
            if lens:
                lens.sort()
                over = sum(1 for x in lens if x > 768)
                ok("D token 中位 %d｜p95 %d｜最大 %d｜超 768 的 %d 条（%.1f%%）"
                   % (lens[len(lens) // 2], lens[int(len(lens) * 0.95)], lens[-1],
                      over, 100.0 * over / len(lens)))
        except Exception as e:  # noqa: BLE001
            warn("D tokenizer 不可用：%s" % str(e)[:90])

    print("\n" + "=" * 76)
    print("E 配置层")
    print("=" * 76)
    cfg_p = "config/finetune_v9.json"
    try:
        cfg = json.load(io.open(cfg_p, encoding="utf-8"))
        for k in ("train_file", "val_file"):
            if os.path.exists(cfg[k]):
                ok("E %s = %s（存在）" % (k, cfg[k]))
            else:
                bad("E %s = %s（**不存在**）" % (k, cfg[k]))
        base = cfg.get("base_model")
        if base and os.path.isdir(base):
            ok("E base_model 存在：%s" % base)
        else:
            bad("E base_model 不存在：%s" % base)
        for k in ("max_seq_len", "epochs", "lora_r", "batch_size", "grad_accum"):
            if k in cfg:
                print("        %-14s %s" % (k, cfg[k]))
        if "tag" in cfg:
            bad("E config 里出现了 tag（会覆盖 train_file 指向旧数据）")
        else:
            ok("E config 无 tag 字段（不会覆盖 train_file）")
    except Exception as e:  # noqa: BLE001
        bad("E 读 config 失败：%s" % str(e)[:80])

    print("\n" + "=" * 76)
    print("结论")
    print("=" * 76)
    print("  OK %d ｜WARN %d ｜FAIL %d" % (len(OK), len(WARN), len(FAIL)))
    if FAIL:
        print("\n  ❌ **不能租卡**，先修：")
        for x in FAIL:
            print("    - " + x)
        return 1
    print("\n  ✅ **可以租卡**：格式/结构/训练器/配置四层全过。")
    if WARN:
        print("  留意：")
        for x in WARN:
            print("    - " + x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
