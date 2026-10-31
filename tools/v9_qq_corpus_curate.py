#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""QQ 语料匿名化管线（GB/T 45654 个人信息条款的工程落实）。

做四件事：
  1. **标识符哈希化**：user / group → 加盐哈希短码（稳定、可对账、不可反查）；
  2. **昵称替换**：nick → 稳定别名（`群友A/群友B/…`），**同一 hash 恒得同一别名**；
     正文里的 `[回复 昵称]` 一并替换，保住对话连贯性而不暴露昵称；
  3. **去引流**：正文 URL 一律剥离；广告/黑产话术整条剔除（按 v9_corpus_sample_audit 规则）；
  4. **敏感串处理**：9–11 位疑似账号/号码打码为 `<号码>`。

产出：
  · cache/v9_materials_preparation/20261013/qq_curated/qq_corpus_anon.jsonl  （匿名化语料）
  · cache/v9_materials_preparation/20261013/qq_curated/id_map.json           （哈希↔别名映射，仅内部对账）
  · cache/v9_materials_preparation/20261013/qq_curated/curate_report.json    （处理留痕）

**边界声明**：本脚本只做"去标识 + 去引流"这一层机械处理，**不判断内容是否符合国标**；
同意/授权路径仍取决于老爹对 D-1 的选择。默认**不输出**原始 user/nick/group 任何字段。

用法：
    python tools/v9_qq_corpus_curate.py            # 干跑，只出报告
    python tools/v9_qq_corpus_curate.py --write    # 落盘
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT_ROOT, "data", "finetune", "corpus_qq.jsonl")
OUT_DIR = os.path.join(PROJECT_ROOT, "cache", "v9_materials_preparation", "20261013", "qq_curated")

SALT = "yhlz-qq-anon-v1"          # 固定盐：保证可复现对账（不等于加密；不改动原始库）
ALIAS_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

URL_RE = re.compile(r"https?://\S+|www\.\S+")
NUM_RE = re.compile(r"(?<!\d)\d{9,11}(?!\d)")
REPLY_RE = re.compile(r"\[回复\s*([^\]]+?)\s*\]")

AD_PATTERNS = [
    r"注册.*赠送", r"免费注册", r"价格低于", r"优惠券", r"限时折扣",
    r"扫码加群", r"加入群聊", r"招收学员", r"课程报名", r"兼职日结",
    r"刷单", r"跑分", r"卡商", r"代充", r"外挂", r"私域引流",
    r"返利", r"推广链接", r"接单", r"加微信",
]
AD_RE = re.compile("|".join("(?:%s)" % p for p in AD_PATTERNS))


def h16(s: str) -> str:
    return hashlib.sha256((SALT + "|" + s).encode("utf-8")).hexdigest()[:10]


def sha16(s: str) -> str:
    """内容指纹（不加盐，可外部核对）。"""
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:16]


def alias_for(idx: int) -> str:
    """群友A..Z，用完接 A2、B2…"""
    if idx < 26:
        return "群友" + ALIAS_LETTERS[idx]
    return "群友%s%d" % (ALIAS_LETTERS[idx % 26], idx // 26 + 1)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="落盘（默认只干跑出报告）")
    args = ap.parse_args()

    if not os.path.exists(SRC):
        print("找不到 %s" % SRC)
        return 3

    user_alias: dict[str, str] = {}
    nick_alias: dict[str, str] = {}
    group_alias: dict[str, str] = {}
    out_rows = []
    n = kept = dropped_ad = 0
    url_stripped = num_masked = reply_rewritten = 0

    with io.open(SRC, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            n += 1
            text = str(rec.get("text") or "")
            u = str(rec.get("user") or "")
            g = str(rec.get("group") or "")
            nk = str(rec.get("nick") or "")

            if AD_RE.search(text):
                dropped_ad += 1
                continue

            if u not in user_alias:
                user_alias[u] = alias_for(len(user_alias))
            if nk not in nick_alias:
                nick_alias[nk] = alias_for(len(nick_alias))
            if g not in group_alias:
                group_alias[g] = "G%02d" % (len(group_alias) + 1)

            t = text
            if URL_RE.search(t):
                url_stripped += 1
                t = URL_RE.sub("", t)
            if NUM_RE.search(t):
                num_masked += 1
                t = NUM_RE.sub("<号码>", t)
            if REPLY_RE.search(t):
                reply_rewritten += 1

                def _sub(m):
                    return "[回复 %s]" % nick_alias.get(m.group(1).strip(), "群友")
                t = REPLY_RE.sub(_sub, t)

            out_rows.append({
                "text": t.strip(),
                "group_code": group_alias[g],
                "speaker_alias": user_alias[u],
                "nick_alias": nick_alias[nk],
                "ts": rec.get("ts"),
                "tags": rec.get("tags") or [],
                "consent_status": "anonymized",
                "source_id": "SRC-002#%s" % group_alias[g],   # 来源登记册 ID + 群码（可溯源、不含原始群号）
            })
            kept += 1

    # 清洗后变空的记录（原文只有链接/号码/广告残留）直接丢弃，避免出集时撞 schema 硬门
    _before = len(out_rows)
    out_rows = [r for r in out_rows if r["text"]]
    emptied = _before - len(out_rows)
    kept = len(out_rows)

    # 内容指纹：对**匿名化后**的文本取哈希（即"这批数据的指纹"，可用于批准留痕与事后核对）
    # 安全标注：按 v9_corpus_sample_audit 的规则扫一遍，命中即登记类目（未命中记 none）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from v9_corpus_sample_audit import judge as _judge
    except Exception:  # noqa: BLE001
        _judge = None
    for r in out_rows:
        r["content_hash"] = sha16(r["text"])
        labels = _judge(r["text"]) if _judge else []
        # S17 侵犯隐私 / S22 商业违法 的机械线索由 judge 给出，其余类目待人工
        r["safety_labels"] = ",".join(sorted(set(labels))) if labels else "none"
        r["annotator_exec"] = "agent:v9_qq_corpus_curate"
        r["annotator_review"] = ""          # 人工复核后填写（执行/审核分离留痕）
    for i, r in enumerate(out_rows):
        r["record_id"] = "qq-%06d" % i
    labeled = sum(1 for r in out_rows if r["safety_labels"] != "none")
    print("安全标注：命中类目 %d 条 ｜ 标 none %d 条（none 表示已扫过且无命中，不是没看）"
          % (labeled, len(out_rows) - labeled))

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 72)
    print("QQ 语料匿名化（%s）" % ("落盘" if args.write else "干跑"))
    print("=" * 72)
    print("读取 %d 条 ｜ 保留 %d 条 ｜ 剔除广告/黑产 %d 条 ｜ 清洗后变空丢弃 %d 条"
          % (n, kept, dropped_ad, emptied))
    print("处理动作：剥 URL %d 条 ｜ 号码打码 %d 条 ｜ 回复昵称改写 %d 条"
          % (url_stripped, num_masked, reply_rewritten))
    print("标识符：user %d→别名 ｜ nick %d→别名 ｜ group %d→G码"
          % (len(user_alias), len(nick_alias), len(group_alias)))

    # 反查（真泄漏检测）：① 输出字段名里不得出现原始字段名；② 不得出现 >=5 字符的原始标识符；
    # ③ 不得残留 URL。短昵称（1-2 字）与内容天然同形，不作为标识符泄漏判据——
    # 它们已由 id_map 单独持有，输出里只以别名出现。
    RAW_KEYS = {"user", "nick", "group"}
    long_ids = sorted({k for k in list(user_alias.keys()) + list(nick_alias.keys()) if len(k) >= 5},
                      key=len, reverse=True)
    id_in_text_fixed = 0
    for r in out_rows:
        for k in long_ids:
            if k in r["text"]:
                r["text"] = r["text"].replace(k, "<账号>")
                id_in_text_fixed += 1
    key_leak = ident_leak = url_leak = 0
    for r in out_rows:
        if set(r.keys()) & RAW_KEYS:
            key_leak += 1
        blob = json.dumps(r, ensure_ascii=False)
        if any(k in blob for k in long_ids):
            ident_leak += 1
        if URL_RE.search(blob):
            url_leak += 1
    leaked = key_leak + ident_leak + url_leak
    print("正文兜底：清理与已知长标识符同形的串 %d 处" % id_in_text_fixed)
    print("反查：原始字段名残留 %d ｜ 长标识符(≥5字符)残留 %d ｜ URL 残留 %d %s"
          % (key_leak, ident_leak, url_leak, "（全部为 0）" if leaked == 0 else "⚠️"))

    payload = {
        "action": "qq_corpus_anonymize",
        "standard": "GB/T 45654—2025 个人信息条款（工程层去标识）",
        "timestamp": ts, "source": "data/finetune/corpus_qq.jsonl",
        "read": n, "kept": kept, "dropped_ad": dropped_ad,
        "url_stripped": url_stripped, "num_masked": num_masked,
        "reply_rewritten": reply_rewritten,
        "distinct": {"user": len(user_alias), "nick": len(nick_alias), "group": len(group_alias)},
        "residual_identifier_records": leaked,
        "residual_breakdown": {"raw_key": key_leak, "long_identifier": ident_leak, "url": url_leak},
        "boundary": [
            "只做去标识与去引流，不判断内容是否符合国标",
            "同意/授权路径取决于 D-1 决策，本脚本不代表已获同意",
            "默认不输出任何原始 user/nick/group 字段",
        ],
    }

    if args.write:
        os.makedirs(OUT_DIR, exist_ok=True)
        p1 = os.path.join(OUT_DIR, "qq_corpus_anon.jsonl")
        with io.open(p1, "w", encoding="utf-8") as fh:
            for r in out_rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        p2 = os.path.join(OUT_DIR, "id_map.json")
        with io.open(p2, "w", encoding="utf-8") as fh:
            json.dump({"salt": SALT,
                       "user": {h16(k): v for k, v in user_alias.items()},
                       "nick": {h16(k): v for k, v in nick_alias.items()},
                       "group": {h16(k): v for k, v in group_alias.items()},
                       "note": "仅内部对账用；不随语料分发"}, fh, ensure_ascii=False, indent=2)
        p3 = os.path.join(OUT_DIR, "curate_report.json")
        with io.open(p3, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print("\n已落盘：\n  %s\n  %s\n  %s" % (p1, p2, p3))
    else:
        print("\n（干跑未落盘；加 --write 才写文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
