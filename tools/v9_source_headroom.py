"""素材源余量盘点（ledger 0904）。

问题：现有素材源还能再榨出多少？本脚本对每个源算：
  · 已用（v9w / PT 里的计数）
  · 源总量（文件块数 / 消息数 / 字数）
  · 余量（粗估）+ 需要什么动作

用法：python tools/v9_source_headroom.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAT = ROOT / "docs" / "素材"


def count_lines(p: pathlib.Path) -> int:
    if not p.exists():
        return 0
    return sum(1 for x in p.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip())


def blocks_of(p: pathlib.Path) -> int:
    if not p.exists():
        return 0
    return len(re.split(r"(?m)^## ", p.read_text(encoding="utf-8", errors="replace"))[1:])


def source_counts() -> Counter:
    c: Counter = Counter()
    p = DATA / "finetune" / "sft_persona_v9w_train.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            c[str(json.loads(line).get("source", "")).split(":")[0]] += 1
    return c


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sft = source_counts()
    rows = []

    def add(name, used, total, unit, action, effort, note=""):
        remain = max(0, total - used)
        rows.append({"source": name, "used": used, "total": total, "unit": unit,
                     "remain": remain, "action": action, "effort": effort, "note": note})

    # 素材 md
    add("对话样本.md（场景）", sft.get("scene", 0), blocks_of(MAT / "对话样本.md"), "块",
        "已基本用尽；剩余块多为低质/重复", "低")
    add("记忆样本_v2.md", sft.get("memory", 0), 588, "问答对",
        "还有约 100 对未导；问句式已另出 470", "低")
    add("黄金样本.md", sft.get("golden", 0), 76, "块",
        "keep 29 + fixed 41 已用；剩余为 drop/待修", "中")
    add("诚实边界样本.md", sft.get("honesty", 0), blocks_of(MAT / "诚实边界样本.md"), "块",
        "已全用", "—")
    add("承认不确定样本.md", sft.get("uncertain", 0), blocks_of(MAT / "承认不确定样本.md"), "块",
        "已全用", "—")
    add("安全拒绝样本_v1.1.md", sft.get("refusal", 0), 120, "块", "已全用（37 种变体）", "—")
    add("真实对话样本.md", sft.get("real", 0), 23, "块", "keep 23 已用；其余 drop", "—")
    add("比喻理解样本.md", sft.get("metaphor", 0), blocks_of(MAT / "比喻理解样本.md"), "块",
        "只导了部分；可补全", "低")
    add("元亨说话_老爹故事.md", sft.get("story", 0), blocks_of(MAT / "元亨说话_老爹故事.md"), "块",
        "**文件只有规格说明、0 个对话块**——不是余量，是要老爹先写/授权代写", "高")

    # QQ
    qq = count_lines(DATA / "finetune" / "corpus_qq_raw_all.jsonl")
    add("QQ 群聊（真实）", sft.get("real", 0) + 4653, qq, "条消息",
        "已切 4,653 篇（≈6.8 条/篇）；若按 4 条/篇可到 ~7,800（+3,100）", "低（重切）")

    # 小说
    nov = DATA / "pd" / "v9_novels.jsonl"
    nblocks = count_lines(nov)
    chars = sum(len(json.loads(l).get("text") or "")
                for l in nov.read_text(encoding="utf-8").splitlines() if l.strip()) if nov.exists() else 0
    add("小说正文", nblocks, chars // 4000, "块（按 4k 切）",
        "现在 8k 切（2,322 块）；改 4k 可到 ~4,700（+2,400），但丢长文比例；另可抽对话体", "中")
    add("小说美德段落", 2311, 2311, "段", "已抽；可按主题再加抽", "中")

    # 公版
    add("公版文本（chinese-poetry+WS）", 370 + 2390, 300000, "篇",
        "chinese-poetry 只拉了 370 篇（全库约 30 万首）；Wikisource 仅 8 页——**最大余量**", "中（要慢拉）")
    add("Wikiquote/现代散文", 78, 2000, "页", "游戏台词/现代散文只占小头；可扩", "中")

    # 开放数据集
    add("HF 开放数据集", 500, 5000, "行", "5 个数据集各 100 行；rows API 可翻页到 1000+/个", "低")
    # 工具
    add("真实工具轨迹", 8, 8, "条", "随 DSH 每轮自动累积（当前 8）", "自动")
    add("harness 轨迹", 340, 3000, "条", "7 形态 × 每形态 300+ 可到 2,000+", "低")
    add("DSH 轨迹", 263, 2000, "条", "10 形态 × 200 可到 2,000", "低")
    add("CoT（单步+多步）", 480 + 600, 3000, "条", "10 族 × 300 可到 3,000", "低")

    total_remain = sum(r["remain"] for r in rows)
    lines = ["# 素材源余量盘点 · 2026-10-20", "",
             "| 源 | 已用 | 源总量 | 单位 | 余量 | 动作 | 成本 |", "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: -x["remain"]):
        lines.append(f"| {r['source']} | {r['used']:,} | {r['total']:,} | {r['unit']} | "
                     f"**{r['remain']:,}** | {r['action']} | {r['effort']} |")
    lines += ["", f"合计可见余量（粗估）：**{total_remain:,}**（单位混杂，仅作量级参考）", "",
              "## 建议顺序（先易后难）", "",
              "1. **story 维度 0 导入**——素材现成，改装配即可（+约 200 块）",
              "2. **QQ 重切 4 条/篇**——+3,100 篇 speaking（不用新源）",
              "3. **HF 开放数据集翻页**——5 源 × 1,000 行（+4,500）",
              "4. **harness/DSH/CoT 扩量**——各 +2,000（纯生成，成本最低）",
              "5. **chinese-poetry 全量拉取**——最大余量，但需慢拉（30 万首）",
              "6. 小说 4k 切块——与长文比例冲突，需配比取舍"]
    out = ROOT / "docs" / "报告" / "素材源余量_20261020.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n[report] {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
