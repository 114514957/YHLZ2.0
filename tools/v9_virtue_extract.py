"""从公版文本抽取「真善美 / 人格道德」段落（ledger 0859）。

老爹 2026-10-20：「那些故事书里对于真善美、人格道德的描述也要」。
只从**公有领域**文本（`data/pd/v9_pd.jsonl`）里抽，逐段带命中词与出处，不引在版作品。
产出 `data/pd/v9_virtue.jsonl`（每段 60–800 字），供 PT 语料的 context 池带 `theme=virtue` 使用。

用法：python tools/v9_virtue_extract.py [--max-per-source 400]
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
SRC = ROOT / "data" / "pd" / "v9_pd.jsonl"
OUT = ROOT / "data" / "pd" / "v9_virtue.jsonl"

# 美德/人格 关键词（单字词只在与道德语境搭配时计入，避免误抓）
WORDS = {
    "仁": ["仁爱", "仁义", "仁德", "仁心", "仁者"],
    "义": ["义气", "侠义", "大义", "见义勇为", "舍生取义", "义不容辞"],
    "礼": ["礼义", "礼数", "知礼", "守礼"],
    "智": ["智谋", "明智", "智慧", "睿智"],
    "信": ["信义", "守信", "诚信", "一诺千金"],
    "忠": ["忠诚", "忠义", "忠心", "尽忠"],
    "孝": ["孝顺", "孝心", "孝悌", "尽孝"],
    "勇": ["勇气", "勇敢", "英勇", "奋勇", "胆气", "胆略"],
    "德": ["德行", "品德", "道德", "厚德", "修德", "德行"],
    "善": ["善良", "善心", "从善", "行善", "积善", "善念"],
    "廉": ["清廉", "廉洁", "廉耻", "廉正"],
    "耻": ["羞耻", "知耻", "廉耻"],
    "节": ["气节", "节操", "操守", "贞节", "名节"],
    "担": ["担当", "挺身", "仗义", "主持公道"],
    "舍": ["舍己", "舍身", "牺牲", "忘我"],
    "慈": ["慈悲", "慈爱", "仁慈"],
    "直": ["正直", "刚正", "直言", "耿直"],
    "诚": ["诚实", "真诚", "至诚"],
    "谦": ["谦逊", "谦和", "谦让", "虚己"],
    "报": ["知恩图报", "感恩", "报恩", "滴水之恩"],
    "省": ["自省", "反省", "克己", "修身"],
    # —— 现代白话（2026-10-20 老爹：要现代美德，不要明清小说）——
    "现": ["勇气", "守护", "牺牲", "诚实", "善良", "选择", "底线",
            "尊严", "责任", "担当", "承诺", "坚持", "希望", "温柔",
            "体面", "正直", "良知", "朋友", "同伴", "信任", "自由",
            "光", "命运", "意义"],
}
ALL_WORDS = sorted({w for ws in WORDS.values() for w in ws}, key=len, reverse=True)
CAT_OF = {w: cat for cat, ws in WORDS.items() for w in ws}

SPLIT_RE = re.compile(r"(?<=[。！？；\n])")


def passages(text: str) -> list[str]:
    """按句切，合并到 60–800 字一段；过长再切。"""
    parts = [p.strip() for p in SPLIT_RE.split(text) if p and p.strip()]
    out, buf, n = [], [], 0
    for p in parts:
        buf.append(p)
        n += len(p)
        if n >= 120:
            seg = "".join(buf).strip()
            while len(seg) > 800:
                out.append(seg[:800])
                seg = seg[800:]
            if len(seg) >= 60:
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
    ap.add_argument("--max-per-source", type=int, default=400)
    ap.add_argument("--max-poetry-share", type=float, default=0.33)
    ap.add_argument("--src", action="append", default=None)
    args = ap.parse_args()
    srcs = [pathlib.Path(s) for s in (args.src or [str(SRC)])]
    srcs.append(ROOT / "data" / "pd" / "v9_ws_prose.jsonl")
    srcs.append(ROOT / "data" / "pd" / "v9_modern_prose.jsonl")
    srcs.append(ROOT / "data" / "pd" / "v9_game_quotes.jsonl")
    srcs = [p for p in srcs if p.exists()]
    if not srcs:
        print("没有可用源", file=sys.stderr)
        return 2

    per_source = Counter()
    seen: set[str] = set()
    rows = []
    kw_hits = Counter()
    for src in srcs:
      for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        source = str(d.get("source") or "pd")
        is_prose = source.startswith(("wikisource", "modern", "game"))
        is_game = source.startswith("game")
        for seg in passages(str(d.get("text") or "")):
            hits = [w for w in ALL_WORDS if w in seg]
            if not hits:
                continue
            # 质量门槛：散文源 1 命中即可；诗词源要求 >=2 命中（避免偶发词）
            if not is_prose and not is_game and len(hits) < 2:
                continue
            # 语境门槛：命中词所在段落要有人/心/行/事/君/臣/父/子/士/民 等主体或行为词
            if not any(k in seg for k in ("人", "心", "行", "事", "君", "臣", "父", "子", "士", "民", "德", "義", "义")):
                continue
            if per_source[source] >= args.max_per_source:
                break
            h = hashlib.sha256(seg.encode()).hexdigest()[:16]
            if h in seen:
                continue
            seen.add(h)
            per_source[source] += 1
            cats = sorted({CAT_OF[w] for w in hits})
            for w in hits:
                kw_hits[w] += 1
            rows.append({"text": seg, "source": source,
                         "source_id": f"virtue#{source}#{per_source[source]}",
                         "license": "public_domain",
                         "group_id": d.get("group_id") or f"virtue:{source}",
                         "theme": "virtue", "keywords": hits, "categories": cats,
                         "chars": len(seg), "content_hash": h,
                         "origin_url": d.get("url")})

    # 诗词配额：诗词行数不超过总量 1/3（真善美主要靠散文叙事）
    poetry = [r for r in rows if r["source"].startswith("poetry")]
    prose = [r for r in rows if not r["source"].startswith("poetry")]
    cap = int(len(prose) * args.max_poetry_share / max(1e-9, 1 - args.max_poetry_share))
    if cap and len(poetry) > cap:
        poetry = poetry[:cap]
    rows = prose + poetry
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    cat_cnt = Counter(c for r in rows for c in r["categories"])
    print(json.dumps({
        "rows": len(rows), "chars": sum(r["chars"] for r in rows),
        "sources": len(per_source),
        "top_sources": per_source.most_common(8),
        "top_keywords": kw_hits.most_common(12),
        "categories": cat_cnt.most_common(10),
        "out": str(OUT.relative_to(ROOT)),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
