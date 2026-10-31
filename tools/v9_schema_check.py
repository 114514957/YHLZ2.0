#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""出集前 schema 校验（P0-6）：训练稿结构的硬门 + 合规字段体检。

两级判定：
  【硬门 ERROR】必须为 0，否则**不许出集**：
    · JSON 无法解析
    · 缺 messages / messages 为空 / 无任何 assistant 回合
    · role 不在 {system,user,assistant,tool}
    · assistant 消息既无 content 也无 tool_calls
    · 相邻 assistant（装配失真）／首条即 assistant（裸开局）
    · group_id 跨 train/val/test（切分泄漏）—— 仅当文件带 group_id 时检查
  【体检 WARN】不拦出集，但记录缺口：
    · 缺 source_id / group_id / content_hash / safety_labels / consent_status / 双签

用法：
    python tools/v9_schema_check.py data/finetune/*.jsonl
    python tools/v9_schema_check.py --train A.jsonl --val B.jsonl --test C.jsonl   # 查泄漏
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import io
import json
import os
import sys
from collections import Counter

VALID_ROLES = {"system", "user", "assistant", "tool"}
# 硬门只认这几个字段（字段名确定性）；合规字段名允许同义（见下）
GROUP_KEYS = ["group_id", "group_code"]
COMPLIANCE_KEYS = {
    "source_id": ["source_id"],
    "group_id": ["group_id", "group_code"],
    "content_hash": ["content_hash", "sha16"],
    "safety_labels": ["safety_labels"],
    "consent_status": ["consent_status"],
    "annotator": ["annotator_exec", "annotator_review"],
}


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:16]


def pick(rec: dict, names: list[str]):
    for n in names:
        if n in rec and rec[n] not in (None, ""):
            return rec[n]
    return None


def check_file(path: str) -> dict:
    errors = Counter()
    warns = Counter()
    groups = set()
    n = 0
    n_assistant = 0
    missing = Counter()
    err_samples: list[str] = []
    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                rec = json.loads(line)
            except Exception as e:  # noqa: BLE001
                errors["JSON 不可解析"] += 1
                if len(err_samples) < 5:
                    err_samples.append("L%d: %s" % (lineno, e))
                continue
            if not isinstance(rec, dict):
                errors["记录不是对象"] += 1
                continue

            # 非对话型记录（纯文本语料）走另一套最小校验
            if "messages" not in rec and ("text" in rec or "content" in rec):
                if not str(rec.get("text") or rec.get("content") or "").strip():
                    errors["空文本记录"] += 1
                g = pick(rec, GROUP_KEYS)
                if g is not None:
                    groups.add(str(g))
                for k, names in COMPLIANCE_KEYS.items():
                    if pick(rec, names) is None:
                        missing[k] += 1
                continue

            msgs = rec.get("messages")
            if not isinstance(msgs, list) or not msgs:
                errors["缺 messages 或为空"] += 1
                continue
            roles = []
            for m in msgs:
                if not isinstance(m, dict):
                    errors["消息不是对象"] += 1
                    continue
                r = str(m.get("role"))
                roles.append(r)
                if r not in VALID_ROLES:
                    errors["非法 role: %s" % r] += 1
                if r == "assistant":
                    n_assistant += 1
                    if not str(m.get("content") or "").strip() and not m.get("tool_calls"):
                        errors["assistant 既无 content 也无 tool_calls"] += 1
            if "assistant" not in roles:
                errors["无 assistant 回合"] += 1
            if roles and roles[0] == "assistant":
                errors["裸开局（首条即 assistant）"] += 1
            for a, b in zip(roles, roles[1:]):
                if a == "assistant" and b == "assistant":
                    errors["相邻 assistant"] += 1
                    break

            g = pick(rec, GROUP_KEYS)
            if g is not None:
                groups.add(str(g))
            for k, names in COMPLIANCE_KEYS.items():
                if pick(rec, names) is None:
                    missing[k] += 1

    return {"file": path, "records": n, "assistant_msgs": n_assistant,
            "errors": dict(errors), "warns": dict(warns),
            "missing_compliance": dict(missing),
            "groups": groups, "err_samples": err_samples}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="要校验的 jsonl（支持通配）")
    ap.add_argument("--train"), ap.add_argument("--val"), ap.add_argument("--test")
    args = ap.parse_args()

    paths: list[str] = []
    for f in args.files:
        paths.extend(sorted(glob.glob(f)) or [f])
    split_map = {}
    for tag, p in (("train", args.train), ("val", args.val), ("test", args.test)):
        if p and os.path.exists(p):
            paths.append(p)
            split_map[p] = tag

    if not paths:
        print("没有要校验的文件。用法：python tools/v9_schema_check.py data/finetune/sft_persona_v8r4.jsonl")
        return 2

    results = []
    total_err = 0
    print("=" * 76)
    print("出集前 schema 校验")
    print("=" * 76)
    for p in paths:
        if not os.path.exists(p):
            print("\n[跳过] 不存在：%s" % p)
            continue
        r = check_file(p)
        results.append(r)
        e = sum(r["errors"].values())
        total_err += e
        print("\n【%s】%s" % (os.path.basename(p), "❌ 有 ERROR" if e else "✅ 硬门通过"))
        print("  记录 %d 条 ｜ assistant 消息 %d 条 ｜ 含 group 的记录组 %d 个"
              % (r["records"], r["assistant_msgs"], len(r["groups"])))
        for k, v in sorted(r["errors"].items(), key=lambda x: -x[1]):
            print("  [ERROR] %s ×%d" % (k, v))
        for s in r["err_samples"]:
            print("      %s" % s)
        if r["missing_compliance"]:
            print("  [WARN] 合规字段缺失：%s"
                  % ", ".join("%s×%d" % (k, v) for k, v in
                              sorted(r["missing_compliance"].items(), key=lambda x: -x[1])))

    # 跨切分 group 泄漏
    if len(split_map) >= 2:
        print("\n【切分泄漏检查】")
        seen = {}
        leak = 0
        for r in results:
            tag = split_map.get(r["file"])
            if not tag:
                continue
            for g in r["groups"]:
                if g in seen and seen[g] != tag:
                    print("  [ERROR] group %s 同时出现在 %s 与 %s" % (g, seen[g], tag))
                    leak += 1
                seen[g] = tag
        if not leak:
            print("  ✅ 未发现跨切分 group")

    print("\n" + "=" * 76)
    print("结论：ERROR 合计 %d 条 ｜ %s" % (total_err, "可出集" if total_err == 0 else "**不许出集**"))
    print("提示：合规字段缺失是 WARN 不是 ERROR——但按国标要求，这些字段齐备前不应做正式合规声明。")
    return 1 if total_err else 0


if __name__ == "__main__":
    sys.exit(main())
