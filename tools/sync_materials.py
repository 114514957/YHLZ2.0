"""Deterministic persona sync across material docs (ledger 0381).

Applies the persona delta without rewriting content:
  - 元亨: 哈哈哈哈哈->哇哈哈哈; leading 哼 interjection -> 啊哈/哇哦/哇哈哈哈;
    drop stray 哼 / 元亨 misused '理论上来说'.
  - 利贞: keep at most one '理论上来说' per block.
  - non-哲学/记忆 blocks: neutralize ideology words.
  - every turn trimmed to <=32 chars at punctuation.
  - Q&A blocks whose rounds lack 问 or 答 get folded so each round has both.

Handles two block dialects: `### <role><问|答><n>` and `### <role>`.
Usage: python sync_materials.py [--apply]
"""
from __future__ import annotations
import re, sys, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "docs" / "素材" / n for n in
        ("对话样本.md", "记忆样本_v2.md", "黄金样本.md", "优质样本.md")]
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.M)
ROLE = re.compile(r"^###\s*(老爹|元亨|利贞|大肥鱼)\s*$", re.M)
PUNCT = "，。！？、；"
PARTICLES = ["啊哈", "哇哦", "哇哈哈哈"]
NEUTRAL = {"唯物": "实在", "辩证": "讲道理", "历史唯物": "来龙去脉", "阶级": "圈子",
           "意识形态": "成见", "生产资料": "家当", "异化": "跑偏", "商品拜物": "崇拜商品",
           "剩余价值": "差价", "剥削": "占便宜"}


def trim(s: str, limit: int = 32) -> str:
    if len(s) <= limit:
        return s
    sub = s[:limit]
    for i in range(len(sub) - 1, -1, -1):
        if sub[i] in PUNCT:
            return sub[: i + 1]
    return sub


def fix_yh(t: str, ctr: list[int], stats: dict) -> str:
    t = t.replace("哈哈哈哈哈", "哇哈哈哈")
    if "理论上来说" in t:
        t = t.replace("，理论上来说", "").replace("理论上来说", "").replace("，，", "，")
    m = re.match(r"^哼[！!，,。.、~～\s]*", t)
    if m:
        orig = t[:m.end()]
        punc = "！" if ("！" in orig or "!" in orig) else "，"
        t = PARTICLES[ctr[0] % len(PARTICLES)] + punc + t[m.end():]
        ctr[0] += 1
        stats["yh_particle"] += 1
    return t.replace("哼", "").replace("，，", "，").replace("。。", "。").replace("！。", "！")


def fold(turns):
    groups = []
    for t in turns:
        if t[1] == "问":
            groups.append([t])
        elif groups:
            groups[-1].append(t)
        else:
            groups.append([t])
    merged = []
    for g in groups:
        if any(x[1] == "问" for x in g) or not merged:
            merged.append(list(g))
        else:
            merged[-1].extend(g)
    final = []
    for i, g in enumerate(merged):
        if not any(x[1] == "答" for x in g) and i + 1 < len(merged):
            merged[i + 1] = g + merged[i + 1]
        else:
            final.append(g)
    out = []
    for num, g in enumerate(final, 1):
        for t in g:
            out.append([t[0], t[1], str(num), t[3]])
    return out


def process_block(p: str, stats: dict, do_trim: bool = True, seed: int = 0) -> str:
    ms = list(TURN.finditer(p))
    fmt = "qa"
    if not ms:
        ms = list(ROLE.finditer(p)); fmt = "role"
    if not ms:
        return p
    head = p[: ms[0].start()].rstrip("\n")
    mc = re.search(r"(?m)^- category:\s*(.*)$", p)
    cat = mc.group(1).strip() if mc else "?"
    turns = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(p)
        if fmt == "qa":
            turns.append([m.group(1).strip(), m.group(2), m.group(3), p[m.end():end].strip()])
        else:
            turns.append([m.group(1).strip(), None, None, p[m.end():end].strip()])
    ctr, theory_used = [seed], [0]
    before = len(turns)
    turns = [t for t in turns if t[0] in ("老爹", "元亨", "利贞")]
    stats["drop_role"] += before - len(turns)
    for t in turns:
        if t[0] == "元亨":
            t[3] = fix_yh(t[3], ctr, stats)
        elif t[0] == "利贞":
            c = t[3].count("理论上来说")
            if c:
                if theory_used[0] == 0:
                    first = t[3].index("理论上来说") + len("理论上来说")
                    t[3] = t[3][:first] + t[3][first:].replace("理论上来说", "")
                    theory_used[0] = 1
                    stats["lz_thin"] += c - 1
                else:
                    t[3] = t[3].replace("理论上来说", "")
                    stats["lz_thin"] += c
            t[3] = t[3].replace("，，", "，").replace("，。", "。").replace("，，", "，")
        if cat not in ("哲学", "记忆"):
            for w, r in NEUTRAL.items():
                if w in t[3]:
                    t[3] = t[3].replace(w, r); stats["ideo"] += 1
        t2 = trim(t[3]) if do_trim else t[3]
        if t2 != t[3]:
            stats["trim"] += 1; t[3] = t2
    if fmt == "qa":
        r = {}
        for t in turns:
            r.setdefault(t[2], {})[t[1]] = 1
        if r and not all(("问" in d and "答" in d) for d in r.values()):
            turns = fold(turns); stats["fold"] += 1
    if fmt == "qa":
        body = "".join(f"### {t[0]}{t[1]}{t[2]}\n{t[3]}\n" for t in turns)
    else:
        body = "".join(f"### {t[0]}\n{t[3]}\n" for t in turns)
    stats["blocks"] += 1
    return head + "\n" + body + "\n"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    for doc in DOCS:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        stats = {"blocks": 0, "yh_particle": 0, "lz_thin": 0, "ideo": 0, "trim": 0, "fold": 0, "drop_role": 0}
        do_trim = doc.name == "对话样本.md"
        parts = re.split(r"(?m)(?=^## )", text)
        out = [process_block(p, stats, do_trim, i) if p.startswith("## ") else p
               for i, p in enumerate(parts)]
        new = "".join(out)
        print(f"{doc.name}: {stats}")
        if args.apply and new != text:
            doc.write_text(new, encoding="utf-8", newline="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
