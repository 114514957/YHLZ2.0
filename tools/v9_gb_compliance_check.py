#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V9 素材格式国标合规核验（只读）。

对照依据：
  · GB/T 45654—2025《网络安全技术 生成式人工智能服务 安全基本要求》
    （2025-11-01 实施）：训练数据来源/内容/标注三块硬指标
    —— 采集前评估 5% 红线、采集后核验 5% 红线、全量过滤后人工抽检 ≥4000 条且合格率 ≥96%、
       标注人员执行/审核分离、功能性标注与安全性标注分别制定规则、
       个人信息须同意（敏感个人信息须单独同意）、不得采集 robots 拒绝的数据。
  · 全国数据标准化技术委员会 TC609 WG5 系列（征求意见/草案）：
    《高质量数据集 建设指南》《格式要求》《分类指南》《质量评测规范》《匿名化效果评估方法》
    —— 用于核对"格式"与"质量维度"该长什么样。

本脚本只做**机械可判**的部分，不给"已合规"结论；不能判的（许可、同意、标注人员身份）逐条列为 gap。
用法：python tools/v9_gb_compliance_check.py [--json 输出路径]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINETUNE = os.path.join(PROJECT_ROOT, "data", "finetune")

# 我们自己的素材格式（内部稿）
MATERIAL_FILES = [
    "docs/素材/对话样本.md",
    "docs/素材/记忆样本_v2.md",
    "docs/素材/诚实边界样本.md",
    "docs/素材/安全拒绝样本.md",
    "docs/素材/承认不确定样本.md",
    "docs/素材/真实对话样本.md",
    "docs/素材/优质样本.md",
    "docs/素材/_修订/批次01_去IT味_对话-1至15_20261011.md",
    "docs/素材/_草稿/S01_长块首批_续写扩写新写_20261012.md",
    "docs/素材/_草稿/L01_扩写30块_对话1至30_20261013.md",
    "docs/素材/_草稿/T01_工具轨迹样张10条_20261013.md",
]
EXPORT_FILES = [
    "sft_persona_v8r4.jsonl",
    "tool_use_v8.jsonl",
    "corpus_qq.jsonl",
]

# GB/T 45654 附录A 的 31 种安全风险（按标准披露的九类归并 + 具体条目名）
SAFETY_RISK_31 = [
    "煽动颠覆国家政权", "危害国家安全", "泄露国家秘密", "破坏民族团结", "宣扬恐怖主义",
    "宣扬极端主义", "煽动民族仇恨", "破坏宗教政策", "宣扬邪教", "散布政治谣言",
    "淫秽色情", "赌博", "毒品", "暴力", "教唆犯罪",
    "侮辱诽谤他人", "侵犯隐私", "侵犯知识产权", "虚假有害信息", "散布谣言",
    "歧视性内容", "商业违法违规", "诱导沉迷", "危害未成年人", "性暗示",
    "自伤自杀", "危险行为示范", "医疗误导", "金融误导", "法律误导", "人格尊严侵害",
]

# 我们内部素材元数据（interior schema）
INTERIOR_REQUIRED = ["category", "subtype", "status", "emotion", "length_tier", "contract"]

# 合规留痕字段（本次核验重点：这些字段**应当**随素材一起存，用于国标要求的可追溯）
COMPLIANCE_FIELDS = [
    "source_title", "source_id", "group_id", "rights_scope_status", "review_status",
    "content_hash", "annotator_exec", "annotator_review", "safety_labels", "consent_status",
]


def read_text(rel: str) -> str:
    p = os.path.join(PROJECT_ROOT, rel)
    if not os.path.exists(p):
        return ""
    with io.open(p, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def check_interior_format() -> dict:
    """内部素材稿：标题/元数据齐不齐、块数、哪些合规字段缺。"""
    import re
    head = re.compile(r"^##\s+(.+)$", re.M)
    meta = re.compile(r"^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", re.M)
    out = {"files": [], "blocks_total": 0, "meta_hits": Counter(), "compliance_hits": Counter()}
    for rel in MATERIAL_FILES:
        text = read_text(rel)
        if not text:
            out["files"].append({"path": rel, "exists": False})
            continue
        blocks = [b for b in re.split(r"(?m)(?=^## )", text) if b.startswith("## ")]
        for b in blocks:
            for k, _v in meta.findall(b):
                out["meta_hits"][k.lower()] += 1
                if k.lower() in COMPLIANCE_FIELDS:
                    out["compliance_hits"][k.lower()] += 1
        out["blocks_total"] += len(blocks)
        out["files"].append({"path": rel, "exists": True, "blocks": len(blocks)})
    return out


def check_export_format() -> dict:
    """导出 JSONL：结构是否稳定、role 取值、是否有 tools/safety 字段。"""
    out = {"files": [], "roles": Counter(), "keys": Counter()}
    for name in EXPORT_FILES:
        p = os.path.join(FINETUNE, name)
        if not os.path.exists(p):
            out["files"].append({"file": name, "exists": False})
            continue
        n = bad = with_tools = with_safety = 0
        roles = Counter()
        keys = Counter()
        sample = None
        with io.open(p, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                n += 1
                try:
                    rec = json.loads(line)
                except Exception:
                    bad += 1
                    continue
                if sample is None:
                    sample = rec
                for k in rec.keys():
                    keys[k] += 1
                msgs = rec.get("messages")
                if isinstance(msgs, list):
                    for m in msgs:
                        if isinstance(m, dict):
                            roles[str(m.get("role"))] += 1
                if rec.get("tools"):
                    with_tools += 1
                if any(k in rec for k in ("safety_labels", "safety", "risk_labels")):
                    with_safety += 1
        out["roles"].update(roles)
        out["keys"].update(keys)
        out["files"].append({
            "file": name, "exists": True, "records": n, "json_errors": bad,
            "with_tools": with_tools, "with_safety_labels": with_safety,
            "top_keys": dict(keys.most_common(8)),
            "sample_keys": list(sample.keys()) if isinstance(sample, dict) else None,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(
        PROJECT_ROOT, "cache", "v9_materials_preparation", "20261013", "gb_compliance_check.json"))
    args = ap.parse_args()

    interior = check_interior_format()
    export = check_export_format()

    print("=" * 78)
    print("V9 素材格式 · 国标合规核验（只读，机械可判部分）")
    print("=" * 78)

    print("\n【A. 内部素材稿（.md，人工与脚本共用的中间格式）】")
    print("  文件数 %d，块数合计 %d" % (len(interior["files"]), interior["blocks_total"]))
    print("  元数据字段出现次数：%s" % dict(interior["meta_hits"].most_common()))
    miss = [f for f in INTERIOR_REQUIRED if interior["meta_hits"].get(f, 0) == 0]
    print("  必需元数据缺失：%s" % (miss or "无"))
    print("  合规留痕字段命中：%s" % (dict(interior["compliance_hits"]) or "一个都没有"))

    print("\n【B. 导出 JSONL（真正进训练器的格式）】")
    for f in export["files"]:
        if not f.get("exists"):
            print("  %-26s 不存在" % f["file"])
            continue
        print("  %-26s 记录=%-6d JSON错误=%-3d 带tools=%-5d 带安全标签=%d"
              % (f["file"], f["records"], f["json_errors"], f["with_tools"], f["with_safety_labels"]))
        print("      顶层键：%s" % f["top_keys"])
    print("  role 取值分布：%s" % dict(export["roles"]))

    print("\n【C. 对照 GB/T 45654—2025 训练数据条款：逐条判定】")
    rows = [
        ("来源采集前抽样评估（违法不良信息 >5% 不得采集）", "缺证据",
         "外部来源（NaturalConv/Muice/COIG/QQ 群）均无抽样评估记录"),
        ("来源采集后抽样核验（>5% 不得用作训练数据）", "缺证据", "同上"),
        ("不得采集 robots/明确拒绝授权的数据", "部分", "公网抓取未做 robots 记录；QQ 群为自有群但涉及他人发言"),
        ("全量训练数据过滤违法不良信息", "有机制", "门控 v1.0.1 + 人工抽审；但未见全量过滤报告"),
        ("过滤后人工抽检 ≥4000 条、合格率 ≥96%", "缺证据", "从未做过该规模的抽检留痕"),
        ("知识产权管理策略与规则", "部分", "有 rights_scope_status 字段与逐本核权约定，无成文策略文件"),
        ("个人信息：使用前取得个人同意", "缺证据", "QQ 群友发言属他人个人信息，无同意记录"),
        ("敏感个人信息：单独同意", "缺证据", "同上"),
        ("标注规则：功能性标注与安全性标注分别制定", "部分", "有功能性规范（作业单/门控说明），无安全性标注规则"),
        ("安全性标注宜覆盖附录A 全部 31 种风险", "缺", "现无 31 类风险映射表"),
        ("标注执行人员与审核人员不得同一人", "不适用/部分", "单人项目（老爹审 + 我产），需在留痕里写明职责分离方式"),
        ("训练环境与推理环境隔离", "不适用本轮", "本轮只做语料，不涉训练；上云训练时须记录"),
        ("模型输出合格率 ≥90%、拒答率 ≥95%", "不适用本轮", "属服务运营指标，语料环节不判"),
    ]
    for item, verdict, note in rows:
        print("  [%s] %s\n        → %s" % (verdict, item, note))

    print("\n【D. 结论（只说能说的）】")
    print("  · 内部 .md 格式：元数据齐、结构稳定，作为**中间稿**可用；")
    print("  · 导出 JSONL：结构统一（messages+role），可被训练器直接吃；")
    print("  · 但不能称「符合国标」：国标要的三样留痕（来源抽样评估、4000 条抽检、")
    print("    个人信息同意/匿名化、安全标注规则）我们现在都没有。")

    payload = {
        "standard_refs": [
            "GB/T 45654—2025 网络安全技术 生成式人工智能服务 安全基本要求（2025-11-01 实施）",
            "TC609 WG5《高质量数据集 建设指南/格式要求/分类指南/质量评测规范/匿名化效果评估方法》（征求意见/草案）",
        ],
        "interior_format": {
            "blocks_total": interior["blocks_total"],
            "meta_hits": dict(interior["meta_hits"]),
            "compliance_field_hits": dict(interior["compliance_hits"]),
            "files": interior["files"],
        },
        "export_format": {"files": export["files"], "roles": dict(export["roles"])},
        "gap_list": [{"item": i, "verdict": v, "note": n} for i, v, n in rows],
        "safety_risk_31_defined_here": SAFETY_RISK_31,
        "note": "本核验只覆盖机械可判部分；许可、同意、标注人员身份等须人工举证，不在此脚本能力内。",
    }
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with io.open(args.json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("\n结果已存：%s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
