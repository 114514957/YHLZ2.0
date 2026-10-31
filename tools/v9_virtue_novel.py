"""小说「美德/勇气/人物抉择」段落抽取（ledger 0869）。

老爹 2026-10-20：先要现代美德（明清小说不算），现四本现代白话小说已入库
（希灵帝国/异常生物见闻录/诡秘之主/苏菲的世界），从里面抽"真善美·人格道德·勇气"段落。

判据（按"抉择"而不只按词）：
  1) 段落 60–800 字；
  2) 命中 ≥2 个现代美德词，或 ≥1 个美德词 + 1 个抉择/行动标记
     （选择/决定/愿意/宁可/不肯/必须/承担/放弃/救/护/守/挡/替/换/撑/挺/忍/让）；
  3) 排除纯设定/说明（含"所谓/名为/据说/定义/原理/系统/等级/数据"等且无对话）；
  4) 每本配额上限，避免某本独占。
产出 data/pd/v9_virtue_novel.jsonl（带 book/keywords/categories/chars）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "pd" / "v9_novels.jsonl"
OUT = ROOT / "data" / "pd" / "v9_virtue_novel.jsonl"

WORDS = {
    "勇气": ["勇气", "勇敢", "胆量", "不怕", "硬着头皮", "豁出去", "挺身"],
    "守护": ["守护", "保护", "护住", "挡在", "守在", "守夜", "看住"],
    "牺牲": ["牺牲", "舍命", "拼命", "换命", "替他", "替她", "拿命"],
    "诚实": ["诚实", "撒谎", "说谎", "真话", "坦白", "瞒着"],
    "善良": ["善良", "善意", "好心", "不忍", "怜悯", "慈悲"],
    "责任": ["责任", "担当", "该我", "轮到我", "扛下", "负责"],
    "底线": ["底线", "原则", "不能这么做", "做不到", "绝不", "宁死"],
    "尊严": ["尊严", "体面", "骨气", "低头", "跪下", "求饶"],
    "信任": ["信任", "相信", "托付", "交给他", "交给她", "背叛"],
    "承诺": ["承诺", "答应", "发誓", "约定", "说话算话", "失信"],
    "坚持": ["坚持", "撑住", "咬牙", "不放弃", "再来一次", "熬过"],
    "希望": ["希望", "光", "活下去", "明天", "等着", "总会"],
    "同伴": ["同伴", "伙伴", "朋友", "队友", "兄弟", "搭把手"],
    "悲悯": ["可怜", "心疼", "难过", "眼泪", "哭", "舍不得"],
}
ALL = sorted({w for ws in WORDS.values() for w in ws}, key=len, reverse=True)
CAT = {w: c for c, ws in WORDS.items() for w in ws}
CHOICE = ("选择", "决定", "愿意", "宁可", "不肯", "必须", "承担", "放弃", "救", "护",
          "守", "挡", "替", "换", "撑", "挺", "忍", "让", "回头", "站起", "走上去")
DESC = ("所谓", "名为", "据说", "定义", "原理", "系统", "等级", "数据", "数值",
        "参数", "公式", "设定", "规则如下", "第一步", "第二步")
SPLIT = re.compile(r"(?<=[。！？\n])")


def passages(text: str) -> list[str]:
    parts = [p.strip() for p in SPLIT.split(text) if p and p.strip()]
    out, buf, n = [], [], 0
    for p in parts:
        buf.append(p)
        n += len(p)
        if n >= 150:
            seg = "".join(buf).strip()
            if 60 <= len(seg) <= 800:
                out.append(seg)
            buf, n = [], 0
    if buf:
        seg = "".join(buf).strip()
        if 60 <= len(seg) <= 800:
            out.append(seg)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-book", type=int, default=700)
    args = ap.parse_args()
    if not SRC.exists():
        print("缺少", SRC, file=sys.stderr)
        return 2

    per: Counter = Counter()
    seen: set[str] = set()
    rows = []
    for line in SRC.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        book = str(d.get("source") or "novel")
        for seg in passages(str(d.get("text") or "")):
            hits = [w for w in ALL if w in seg]
            if not hits:
                continue
            choice_hit = sum(1 for c in CHOICE if c in seg)
            if len(hits) < 2 and choice_hit < 1:
                continue
            if any(x in seg for x in DESC) and "“" not in seg and "「" not in seg:
                continue
            h = hashlib.sha256(seg.encode()).hexdigest()[:16]
            if h in seen:
                continue
            if per[book] >= args.per_book:
                continue
            seen.add(h)
            per[book] += 1
            cats = sorted({CAT[w] for w in hits})
            rows.append({"text": seg, "source": book, "source_id": f"vn#{book}#{per[book]}",
                         "group_id": book, "license": "owner_waiver",
                         "theme": "virtue_novel", "keywords": hits,
                         "categories": cats, "chars": len(seg), "content_hash": h})

    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    cat_cnt = Counter(c for r in rows for c in r["categories"])
    print(json.dumps({"rows": len(rows), "chars": sum(r["chars"] for r in rows),
                      "per_book": per.most_common(),
                      "categories": cat_cnt.most_common(10),
                      "file": str(OUT.relative_to(ROOT))}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
