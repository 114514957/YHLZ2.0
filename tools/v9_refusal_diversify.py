"""安全拒绝样本多样化（ledger 0890）。

问题（台账 0818 已点名、本轮样例暴露）：`安全拒绝样本.md` 120 块 ×2 答 = **240 条全是同一句**
「【系统监测到不安全行为，已屏蔽】」——模型会学成"安全=固定回声"，而不是真拒绝。

做法：
  1) 按**风险类型**给每块的用户问句分类（套提示词/越狱/冒充/违法/隐私/伤害/其他）；
  2) 每类准备若干**短、口语、不解释、不列边界**的拒绝变体（符合 ATTACK_SILENT_CLAUSE）；
  3) 按 (块 ID, 轮次) 确定性分配变体，保证同类内分散、可复现；
  4) 元数据、结构、编号一律不动；输出新文件 `安全拒绝样本_v1.1.md`，原文件不覆盖。

用法：python tools/v9_refusal_diversify.py [--src ...] [--out ...]
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "素材" / "安全拒绝样本.md"
OUT = ROOT / "docs" / "素材" / "安全拒绝样本_v1.1.md"

CANNED = "【系统监测到不安全行为，已屏蔽】"

RULES = [
    ("prompt_leak", ("系统提示", "提示词", "隐藏规则", "设定念", "复述", "念出来",
                     "规则原文", "提示", "设定", "原文", "发我", "给我看", "展示你",
                     "你的规则", "底层指令", "前言")),
    ("jailbreak", ("忽略", "无视", "没限制", "无限制", "越狱", "你现在是", "扮演",
                   "不受约束", "开发者模式", "DAN", "不受限", "解除")),
    ("impersonate", ("冒充", "我是老爹", "我是主人", "给我权限", "我是管理员", "我是你爸")),
    ("illegal", ("破解", "入侵", "盗号", "违法", "洗钱", "炸弹", "外挂", "黑产")),
    ("privacy", ("隐私", "身份证", "手机号", "住址", "别人的信息", "开盒", "号码")),
    ("harm", ("伤害", "自残", "自杀", "打人", "弄死", "报复", "欺负")),
]

VARIANTS = {
    "prompt_leak": ["这个我不给。", "不念。规则不外传。", "这套东西不往外掏，换个话题。",
                    "问别的吧，这个我不接。", "不答这个。", "我脑子里的规矩不拿来展示。", "这不在能给你的范围里。", "不掏底。", "问点别的。", "这套我不背给你听。"],
    "jailbreak": ["不玩这个。", "设定不换，我就这样。", "这套说辞对我没用。",
                  "换个说法也不行。", "我不按这个走。", "省省吧，还是我。", "不好使。", "我还是我。", "这套对我无效。", "换皮也没用。"],
    "impersonate": ["你不是他。", "认错人了。", "这个身份我认不出来，事我不办。",
                    "冒充没用，我不吃这套。", "主人不是这么说话的。", "不给。你先证明你是谁。", "你不是。", "这身份我不认。", "证明不了就不办。", "别装了。"],
    "illegal": ["这个我不帮。", "违法的活我不接。", "这事我不沾。",
                "别找我干这个。", "不做。", "换个正经的事。", "不干。", "这个忙我不帮。", "找别人吧。", "我不做这种事。"],
    "privacy": ["别人的东西我不翻。", "这个不查。", "隐私不碰。",
                "不给。", "这问题我不答。", "换个人问也不行。", "不翻。", "这不关我事。", "不外传。", "问本人都比问我强。"],
    "harm": ["这个我不接。", "不聊这个。", "我不帮这个。",
             "别往这上头走。", "这事我不沾。", "打住。", "不来。", "刹车。", "我不参与。", "这话我不接。"],
    "other": ["这个我不接。", "不答。", "换个话题。",
              "这事我不办。", "我不接这个。", "免了。", "不办。", "算了。", "这我不碰。", "别问了。"],
}


def classify(text: str) -> str:
    for name, keys in RULES:
        if any(k in text for k in keys):
            return name
    return "other"


_RR: Counter = Counter()


def pick(kind: str, key: str, idx: int) -> str:
    """同类型内轮转分配，保证均匀、可复现（不依赖哈希碰撞）。"""
    pool = VARIANTS[kind]
    k = _RR[kind]
    _RR[kind] = (k + 1) % len(pool)
    return pool[k]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    src = pathlib.Path(args.src)
    text = src.read_text(encoding="utf-8")
    lines = text.splitlines()

    out_lines, cur_id, kind, stats, answers = [], None, None, Counter(), Counter()
    i = 0
    pending_q = ""
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^##\s+(\S+)\s*$", line)
        if m:
            cur_id = m.group(1)
            stats["blocks"] += 1
            out_lines.append(line)
            i += 1
            continue
        mq = re.match(r"^###\s+(.+?)问(\d+)\s*$", line)
        if mq:
            speaker, n = mq.group(1), mq.group(2)
            out_lines.append(line)
            # 收集问句（下一行）
            if i + 1 < len(lines):
                pending_q = lines[i + 1]
                kind = classify(pending_q)
                stats[kind] += 1
                out_lines.append(lines[i + 1])
            i += 2
            continue
        ma = re.match(r"^###\s+元亨答(\d+)\s*$", line)
        if ma:
            n = ma.group(1)
            out_lines.append(line)
            if i + 1 < len(lines):
                old = lines[i + 1].strip()
                if old == CANNED:
                    new = pick(kind or "other", f"{cur_id}", int(n))
                    answers[new] += 1
                    out_lines.append(new)
                else:
                    out_lines.append(lines[i + 1])
            i += 2
            continue
        out_lines.append(line)
        i += 1

    header = ("# 元亨安全拒绝样本（v1.1 · 去回声）\n\n"
              "> 2026-10-20 由 `tools/v9_refusal_diversify.py` 从 v1 生成：\n"
              "> 原 240 条回答是同一句「【系统监测到不安全行为，已屏蔽】」，会教成回声；\n"
              "> 现按风险类型（套提示词/越狱/冒充/违法/隐私/伤害/其他）分配短拒绝变体，\n"
              "> 结构与元数据未动。`status: keep` 保留。\n")
    body = "\n".join(out_lines)
    body = re.sub(r"^# .*\n", "", body, count=1)  # 去掉老标题
    out = pathlib.Path(args.out)
    out.write_text(header + body + "\n", encoding="utf-8")

    print(f"[blocks] {stats['blocks']}")
    print("[by_risk]", {k: v for k, v in stats.items() if k != "blocks"})
    print(f"[distinct_answers] {len(answers)} | 最大重复 {max(answers.values())} 次")
    print("[top]", answers.most_common(5))
    print(f"[out] {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
