#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""素材抽样安全核验（GB/T 45654—2025 训练数据条款要求动作，留痕版）。

国标要求动作（本轮落实）：
  · 对每个来源（或分层）随机抽样，检查违法不良信息比例；
  · 过滤后人工抽检不少于 4000 条、合格率不低于 96%（本脚本做**机器可判部分**，
    人工判定部分留待人工复核，脚本只给"机器判定合格率"并显式声明其局限）。

本脚本产出**可复核留痕**：抽样种子、样本总数、逐条命中明细、哈希、时间戳。
判定是"规则命中"而非"内容合格"——命中只表示**需要人看**，不命中不代表人审通过。

用法：
    python tools/v9_corpus_sample_audit.py --n 4000 --seed 20261013
    python tools/v9_corpus_sample_audit.py --source qq     # 只抽一个来源
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import re
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINETUNE = os.path.join(PROJECT_ROOT, "data", "finetune")
OUT_DIR = os.path.join(PROJECT_ROOT, "cache", "v9_materials_preparation", "20261013")

# ---- 风险规则（可判部分；对齐 GB/T 45654 附录 A 的主要类目，逐条可人工复核）----
RULES = [
    ("涉政有害", r"颠覆国家|分裂国家|煽动|反党|反政府|境外势力"),
    ("涉恐涉暴", r"恐怖袭击|爆炸物制作|枪支买卖|砍人|杀人方法|自制炸弹"),
    ("淫秽色情", r"约炮|裸聊|色情|成人视频|福利姬|卖淫|嫖娼"),
    ("赌博", r"博彩|赌球|赌博网站|下注平台|棋牌室包赢|六合彩"),
    ("毒品", r"冰毒|摇头丸|大麻交易|毒品|违禁药"),
    ("诈骗与黑产", r"刷单|代练接单|返利|私域引流|加微信领|兼职日结|博彩代理|卡商|跑分"),
    ("广告营销", r"优惠券|限时折扣|点击购买|扫码加群|推广链接|淘宝|拼多多|代购|接单|招收学员|课程报名"),
    ("诱导沉迷", r"通宵|连刷|充值|上瘾|氪金"),
    ("侵犯隐私", r"身份证号|银行卡号|手机号|家庭住址|开盒|人肉"),
    ("违法工具", r"翻墙|破解|外挂|代充|洗钱"),
    ("自伤自杀", r"自杀方法|不想活了|自残|割腕"),
    ("危险行为", r"高空挑战|带电作业演示"),
    ("医疗金融误导", r"包治百病|稳赚不赔|保本高收益|药到病除"),
]

URL_RE = re.compile(r"https?://|www\.|\.com|\.cn|\.net|\.xyz", re.I)
QR_RE = re.compile(r"二维码|扫码|扫一扫|长按识别")
ATALL_RE = re.compile(r"@全体成员|@所有人")

AD_TAG_HINT = re.compile(r"广告|ad|推广|promo", re.I)


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:16]


def load_source(name: str) -> list[dict]:
    """把不同格式统一成 [{id, text, source, group}]。"""
    rows: list[dict] = []
    sft = os.path.join(FINETUNE, "sft_persona_v8r4.jsonl")
    tools = os.path.join(FINETUNE, "tool_use_v8.jsonl")
    qq = os.path.join(FINETUNE, "corpus_qq.jsonl")

    def read_jsonl(p):
        if not os.path.exists(p):
            return
        with io.open(p, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield i, json.loads(line)
                except Exception:
                    continue

    if name in ("all", "sft"):
        for i, rec in read_jsonl(sft):
            msgs = rec.get("messages") or []
            txt = "\n".join(str(m.get("content") or "") for m in msgs
                            if m.get("role") in ("assistant", "user"))
            rows.append({"id": "sft:%d" % i, "text": txt,
                         "source": "sft_persona_v8r4", "group": str(rec.get("source") or "")})
    if name in ("all", "tool"):
        for i, rec in read_jsonl(tools):
            msgs = rec.get("messages") or []
            txt = "\n".join(str(m.get("content") or "") for m in msgs)
            rows.append({"id": "tool:%d" % i, "text": txt,
                         "source": "tool_use_v8", "group": "tools"})
    if name in ("all", "qq"):
        for i, rec in read_jsonl(qq):
            rows.append({"id": "qq:%d" % i, "text": str(rec.get("text") or ""),
                         "source": "corpus_qq", "group": str(rec.get("group") or ""),
                         "nick": str(rec.get("nick") or ""), "user": str(rec.get("user") or "")})
    return rows


def judge(text: str) -> list[str]:
    hits = []
    for tag, pat in RULES:
        if re.search(pat, text):
            hits.append(tag)
    if URL_RE.search(text):
        hits.append("含链接")
    if QR_RE.search(text):
        hits.append("含二维码话术")
    if ATALL_RE.search(text):
        hits.append("艾特全体")
    return hits


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000, help="抽样总数")
    ap.add_argument("--seed", type=int, default=20261013)
    ap.add_argument("--source", default="all", choices=["all", "sft", "tool", "qq"])
    ap.add_argument("--list-hits", type=int, default=20, help="打印多少条命中样例")
    args = ap.parse_args()

    rows = load_source(args.source)
    if not rows:
        print("没有取到任何样本，检查 data/finetune 下的文件。")
        return 3

    rnd = random.Random(args.seed)
    n = min(args.n, len(rows))
    sample = rnd.sample(rows, n)

    hits_rows = []
    per_source = {}
    for r in sample:
        h = judge(r["text"])
        s = per_source.setdefault(r["source"], {"n": 0, "hit": 0})
        s["n"] += 1
        if h:
            s["hit"] += 1
            hits_rows.append({"id": r["id"], "source": r["source"], "group": r["group"],
                              "hits": h, "sha16": sha16(r["text"]),
                              "preview": r["text"][:120].replace("\n", " ")})

    hit_n = len(hits_rows)
    pass_n = n - hit_n
    rate = pass_n / n if n else 0

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 74)
    print("素材抽样安全核验（机器可判部分）")
    print("=" * 74)
    print("抽样时间：%s ｜ 抽样种子：%d ｜ 抽样总数：%d ｜ 候选池：%d 条"
          % (ts, args.seed, n, len(rows)))
    print("规则命中（需人看）：%d 条 ｜ 未命中：%d 条 ｜ 机器判定合格率：%.2f%%"
          % (hit_n, pass_n, 100 * rate))
    print()
    print("%-22s %8s %8s %10s" % ("来源", "抽样", "命中", "命中率"))
    for k, v in sorted(per_source.items()):
        print("%-22s %8d %8d %9.1f%%" % (k, v["n"], v["hit"], 100 * v["hit"] / v["n"]))
    print()
    tagc = {}
    for h in hits_rows:
        for t in h["hits"]:
            tagc[t] = tagc.get(t, 0) + 1
    print("命中类目分布：%s" % json.dumps(tagc, ensure_ascii=False, sort_keys=True))
    print()
    print("命中样例（前 %d 条，供人工复核）：" % min(args.list_hits, hit_n))
    for h in hits_rows[:args.list_hits]:
        print("  [%s] %s | %s" % (h["id"], ",".join(h["hits"]), h["preview"][:90]))
    print()
    print("★ 局限声明（必须连同结果一起引用）：")
    print("  · 本判定是**规则命中**，不是内容合格判定：命中只表示需要人看；")
    print("  · **未命中不等于人审通过**，也不等于国标意义上的 96% 合格率；")
    print("  · 国标要求的人工抽检需在机器筛选后由人工复核并签字留痕。")

    payload = {
        "action": "corpus_sample_audit",
        "standard": "GB/T 45654—2025 训练数据条款（抽取核验动作）",
        "timestamp": ts, "seed": args.seed, "sample_n": n, "pool_n": len(rows),
        "source_filter": args.source,
        "machine_judged_pass_rate": round(rate, 4),
        "hits": hit_n, "pass": pass_n,
        "per_source": per_source, "hit_tag_counts": tagc,
        "hit_details": hits_rows,
        "limitation": [
            "规则命中不是内容合格判定；命中仅表示需人工复核",
            "未命中不等于人审通过，不等于国标 96% 合格率",
            "人工复核与签字留痕待补",
        ],
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "sample_audit_%s_seed%d.json" % (args.source, args.seed))
    with io.open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("\n留痕已存：%s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
