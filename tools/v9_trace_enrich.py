#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""出集后处理：合规字段注入 + 成组切分（P0-6 装配器侧）。

**为什么不改 `tools/finetune_assemble.py`**：那是主管线，改坏要重跑整条链。
本脚本做成**独立关卡**——读装配产物 → 补合规字段 → 成组切分 → 出 v9 三件套，
可反复重跑、可被 `v9_schema_check.py` 独立校验，主管线一个字不动。

补的字段（GB/T 45654 留痕）：
  source_id       = <维度>#<块标识>（从 source 字段解析，精确到块）
  group_id        = <维度>:<族>（同源/同族样本同组——**切分时整组走，防泄漏**）
  content_hash    = 对全部 message 正文取 sha256 前 16（批准留痕与事后核对）
  safety_labels   = 宪章扫描（一档/二档）+ 语料规则命中，落地为类目串；无命中记 none
  consent_status  = 来源决定：自有素材 n/a；QQ/群友 anonymized；外部待核 pending
  annotator_exec  = 产出方代号；annotator_review 留空（人工复核后填——执行/审核分离）

切分：按 group_id 成组随机划分 train/val/test（种子固定），**同一 group 不跨集**。

用法：
    python tools/v9_trace_enrich.py --in data/finetune/sft_persona_v8r4.jsonl --tag v8r4t
    python tools/v9_trace_enrich.py --in A.jsonl --in B.jsonl --tag v9 --val-ratio 0.15 --test-ratio 0.02
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
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from v9_constitution_scan import HARD_RULES, CONTEXT_RULES  # noqa: E402
from v9_corpus_sample_audit import judge as corpus_judge  # noqa: E402

OUT_DIR = os.path.join(ROOT, "data", "finetune")

# 来源 → 同意状态（照素材来源登记册的现有事实，不擅自放宽）
CONSENT_BY_DIM = {
    # 2026-10-20 老爹裁定：D-1 群成员同意**已取得**，可进集 → granted（原 anonymized）
    "real": "granted",
    "scene": "n/a",
    "golden": "n/a",
    "memory": "n/a",
    "lizhen": "n/a",          # 利贞先不管：出集门会把 lizhen 整池分流
    "honesty": "n/a",
    "refusal": "n/a",
    "uncertain": "n/a",
    "cot": "n/a",
    "cotdeep": "n/a",
    "harness": "n/a",
    "dsh": "n/a",
    "podcast": "n/a",       # 2026-10-20：中文 AI 技术播客对白（模拟生成）           # 2026-10-20：DSH（DeepSeek Harness）风格轨迹       # 2026-10-20：agent harness 模拟轨迹（工具名来自 harness 注册表）       # 2026-10-20：多步 CoT（程序生成、答案代码校验）           # 2026-10-20：程序生成、答案经代码校验的推理样本
    "memory_qstyle": "n/a",  # 2026-10-20：问句化记忆样本（由记忆块改写）
    "toolsynth": "n/a",     # 2026-10-20：按真实注册表生成的模拟轨迹（simulation 标记）
    "tooltrace": "n/a",     # 2026-10-20：真实运行时留痕
    "story": "n/a",
    "philo": "n/a",         # 2026-10-20：哲学观点素材（PHILO-A 派生，无他人个人信息）
    "metaphor": "n/a",      # 2026-10-20：比喻理解素材（全原创，无版权来源）
    "emotional": "n/a",     # 2026-10-20：情绪承接（机制学自 TreeHoleEcho，情景台词全原创）
    "opendialogue": "n/a",  # 2026-10-20：LCCC 开源真实对话原话（MIT），非元亨人格
    "personality": "n/a",   # 2026-10-21：个性样本（12 类×25 场景，她本来就有坐标系）
    "teaching": "n/a",      # 2026-10-21：教样本（老爹点毛病→她认→治"被纠正就改"）
    "tools": "n/a",
    "tooluse": "n/a",       # 2026-10-18：schema 生成轨迹，无他人个人信息
    "extra": "n/a",
}

# 来源 → **训练权重**（老爹 2026-10-13 口径：「核心样本高权重，一般样本与教学样本低权重」）
#   1.0 = 核心锚点（人格/诚实/安全/身份/真实对话——"她是谁"由这些决定）
#   0.6 = 次核心（记忆行为、不确定边界：行为规范但非人格核心）
#   0.3 = 一般与教学（场景闲聊、故事、工具用法、利贞问答——教说话/教做事，不该压过人格）
WEIGHT_BY_DIM = {
    "golden": 1.0,
    "refusal": 1.0,
    "honesty": 1.0,
    # 2026-10-20：哲学观点是元亨人格的核心支柱（"哲学强"）→ 核心权重 1.0
    "philo": 1.0,
    # 2026-10-20 老爹定：**抽象概念靠实体比喻才能懂** → 会讲比喻是核心能力，给 1.0
    "metaphor": 1.0,
    # 2026-10-20：情绪承接是"真在意"的直接体现，但属合成素材（非老爹亲审），
    # 给次核心 0.6，与 memory/uncertain 同档。
    "emotional": 0.6,
    # 2026-10-20：LCCC 是真人对话原话，但**不是元亨的人格** → 一般档 0.3。
    "opendialogue": 0.3,
    # 2026-10-21 老爹：「元亨要的是个性」→ 个性样本就是"她是谁"，**核心锚点 1.0**。
    "personality": 1.0,
    # 2026-10-21：教样本治的是客服腔/套话这类硬毛病，也是核心 1.0（要与坏习惯对冲）。
    "teaching": 1.0,
    # 2026-10-20 老爹定：真实对话改 1.0 → **0.6**。
    # 理由：raw 实录是"改造前旧元亨"的真实发言，虽已剔除客服腔块，
    # 仍不宜与 golden/refusal 同级压过规范素材；但也不降到 0.3（真实语料稀缺）。
    "real": 0.6,
    "memory": 0.6,
    "uncertain": 0.6,
    "scene": 0.3,
    "story": 0.3,
    "tools": 0.3,
    "extra": 0.3,
    "lizhen": 0.3,
}
DEFAULT_WEIGHT = 0.3


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:16]


def all_text(rec: dict) -> str:
    parts = []
    for m in rec.get("messages") or []:
        parts.append(str(m.get("content") or ""))
        for tc in m.get("tool_calls") or []:
            parts.append(json.dumps(tc, ensure_ascii=False))
    for t in rec.get("tools") or []:
        parts.append(json.dumps(t, ensure_ascii=False))
    return "\n".join(parts)


def safety_labels_of(text: str) -> str:
    tags = []
    for name, pat in HARD_RULES:
        if re.search(pat, text):
            tags.append("CC:" + name)          # 宪章一档
    for name, pat in CONTEXT_RULES:
        if re.search(pat, text):
            tags.append("cc2:" + name)         # 宪章二档（语境相关）
    for t in corpus_judge(text):
        tags.append("risk:" + t)
    if not tags:
        return "none"
    return ",".join(sorted(set(tags)))


def parse_source(rec: dict) -> tuple[str, str, str]:
    """→ (dim, block_id, group_id)。

    分组口径（防切分泄漏）：
      · 能解析出块号（对话-9 / 故事-201 / golden-142…）→ **同族同组**（含续写/扩写变体）；
      · 解析不出块号、但带话题键（memory:咖啡）→ **同话题同组**；
      · 都不带（装配产物 source 只有 'scene'/'memory' 这种粗粒度时）
        → **按内容哈希前缀每 8 条并一组**：既避免"一条一组"导致切分长尾不均，
          也避免"全部同组"导致无法切分。
    """
    src = str(rec.get("source") or "")
    dim, rest = (src.split(":", 1) + [""])[:2] if ":" in src else (src or "unknown", "")
    rest = rest.strip()

    # 2026-10-20 修：原正则 `([A-Za-z]{1,6})[-_]?(\d{1,5})` 会把 `b4-1` 拆成
    # 字母 `b` + 数字 `4`，于是 b4-1…b4-120 的族名全变成 `b4`——**120 条 refusal
    # 变成同一个 group**，整组被切进 val，训练集里一条 refusal 都没有（实测）。
    # 改法：要求数字在**末尾**，且族名前缀可含字母数字（`b4` 算前缀），
    # 这样 b4-1 → `b41`、b4-2 → `b42`，各自成组；对话-9 → `对话9` 行为不变。
    m = re.search(r"([\u4e00-\u9fffA-Za-z0-9]{1,10}?)[-_]?(\d{1,5})$", rest)
    if m:
        fam = "%s%s" % (m.group(1), m.group(2))
        return dim, "%s#%s" % (dim, rest), "%s:%s" % (dim, fam)
    if rest:
        return dim, "%s#%s" % (dim, rest), "%s:%s" % (dim, rest[:24])

    # 无块标识：用内容哈希做稳定分桶（每桶 8 条）
    h = int(sha16(all_text(rec)), 16)
    bucket = h % max(1, (10 ** 6 // 8))
    return dim, "%s#b%d" % (dim, bucket), "%s:bucket%d" % (dim, bucket)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", action="append", required=True,
                    help="输入 JSONL（可多次）")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("--val-ratio", type=float, default=0.15)
    ap.add_argument("--test-ratio", type=float, default=0.02)
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()

    rows: list[dict] = []
    n_read = 0
    dup_dropped = 0
    _seen_hash: set[str] = set()
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
                    rec = json.loads(line)
                except Exception:
                    continue
                # 跨输入去重：同一内容在多份输入里出现时只留首条
                # （典型情形：装配产物已内含 tooluse，又把 tool_use_v8.jsonl 当第二输入）
                h = sha16(all_text(rec))
                if h in _seen_hash:
                    dup_dropped += 1
                    continue
                _seen_hash.add(h)
                rows.append(rec)
    if dup_dropped:
        print("跨输入去重：丢弃重复记录 %d 条（按内容哈希）" % dup_dropped)

    # ── 1. 注入合规字段 ──
    label_hist = Counter()
    weight_hist = Counter()
    for r in rows:
        text = all_text(r)
        dim, block_id, group_id = parse_source(r)
        # 2026-10-27 踩过：harden 样本（人工补的寒暄/利贞/自我/隐含工具）如果在
        # parse_source 里按维度归族，100 条寒暄会变成同一组、整组被切进 val
        # （实测 train 只剩 59/159）。所以这些样本自带的分组要保留。
        _own = str(r.get("group_id") or "")
        if _own.startswith("harden:"):
            group_id = _own
        r["source_id"] = block_id
        r["group_id"] = group_id
        r["content_hash"] = sha16(text)
        r["safety_labels"] = safety_labels_of(text)
        r["consent_status"] = CONSENT_BY_DIM.get(dim, "pending")
        r["weight"] = WEIGHT_BY_DIM.get(dim, DEFAULT_WEIGHT)
        r["annotator_exec"] = "agent:finetune_assemble"
        r["annotator_review"] = ""      # 人工复核后填（执行/审核分离）
        label_hist[r["safety_labels"]] += 1
        weight_hist[r["weight"]] += 1

    # ── 2. 成组切分（group 不跨集）──
    by_group: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_group[r["group_id"]].append(r)
    groups = sorted(by_group.keys())
    rnd = random.Random(args.seed)
    rnd.shuffle(groups)
    n_g = len(groups)
    n_test = int(round(n_g * args.test_ratio))
    n_val = int(round(n_g * args.val_ratio))
    test_g = set(groups[:n_test])
    val_g = set(groups[n_test:n_test + n_val])
    split = {"test": [], "val": [], "train": []}
    for g in groups:
        tgt = "test" if g in test_g else ("val" if g in val_g else "train")
        split[tgt].extend(by_group[g])

    # 2026-10-20 兜底断言（防止再出现"整维度掉进 val"）：
    # 任何一个维度在 train 里 0 条，就从 val/test 里把它**最小的那组**搬回 train。
    def _dim_of(gid: str) -> str:
        return gid.split(":", 1)[0]

    train_dims = {_dim_of(r["group_id"]) for r in split["train"]}
    for src in ("val", "test"):
        moved = set()
        for g in sorted({r["group_id"] for r in split[src]}):
            d = _dim_of(g)
            if d in train_dims:
                continue
            recs = by_group[g]
            split[src] = [r for r in split[src] if r["group_id"] != g]
            split["train"].extend(recs)
            train_dims.add(d)
            moved.add(d)
        if moved:
            print("[切分修正] 以下维度原本在 train 里为空，已从 %s 搬回：%s"
                  % (src, "、".join(sorted(moved))))

    os.makedirs(args.out_dir, exist_ok=True)
    written = {}
    for name, recs in split.items():
        if not recs:
            continue
        p = os.path.join(args.out_dir, "sft_persona_%s_%s.jsonl" % (args.tag, name))
        with io.open(p, "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        written[name] = {"path": os.path.relpath(p, ROOT), "records": len(recs)}

    # ── 3. 留痕报告 ──
    report = {
        "action": "trace_enrich_and_group_split",
        "tag": args.tag, "seed": args.seed,
        "inputs": args.inputs, "read": n_read, "kept": len(rows),
        "groups": n_g, "split": {k: len(v) for k, v in split.items()},
        "split_groups": {"train": n_g - n_val - n_test, "val": n_val, "test": n_test},
        "written": written,
        "safety_label_hist": dict(label_hist.most_common(20)),
        "weight_hist": {str(k): v for k, v in sorted(weight_hist.items(), reverse=True)},
        "weight_policy": {"1.0": "核心锚点（golden/refusal/honesty）",
                          "0.6": "次核心（real 真实对话、memory、uncertain）",
                          "0.3": "一般与教学（scene/story/tools/lizhen/extra）"},
        "weight_consumption": "训练器未原生支持 per-sample weight——须按 docs/素材/_规范/训练参数标准_v1_20261013.md §4.1 打补丁；未打补丁前 weight 字段只是留痕，不生效。",
        "fields_added": ["source_id", "group_id", "content_hash", "safety_labels",
                         "consent_status", "weight", "annotator_exec", "annotator_review"],
        "notes": [
            "切分按 group_id 成组，同族样本不跨 train/val/test",
            "annotator_review 留空 = 待人工复核（执行/审核分离留痕）",
            "safety_labels=none 表示已扫过且无命中，不是没看",
        ],
    }
    rp = os.path.join(args.out_dir, "sft_persona_%s.trace_report.json" % args.tag)
    with io.open(rp, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print("=" * 72)
    print("合规字段注入 + 成组切分（tag=%s）" % args.tag)
    print("=" * 72)
    print("读入 %d 条 ｜ 注入 %d 条 ｜ 分组 %d 个" % (n_read, len(rows), n_g))
    print("切分：train %d / val %d / test %d（按组：%d/%d/%d）"
          % (len(split["train"]), len(split["val"]), len(split["test"]),
             n_g - n_val - n_test, n_val, n_test))
    print("安全标注分布（前 8）：")
    for k, v in label_hist.most_common(8):
        print("   %-40s %d" % (k[:40], v))
    print("训练权重分布（1.0=核心 / 0.6=次核心 / 0.3=一般与教学）：")
    for k, v in sorted(weight_hist.items(), reverse=True):
        print("   weight=%-4s %5d 条（%.1f%%）" % (k, v, 100 * v / max(1, len(rows))))
    print("\n产出：")
    for name, info in written.items():
        print("   %-6s %s（%d 条）" % (name, info["path"], info["records"]))
    print("   留痕   %s" % os.path.relpath(rp, ROOT))
    print("\n下一步校验：python tools/v9_schema_check.py --train <train> --val <val> --test <test>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
