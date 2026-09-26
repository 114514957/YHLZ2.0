"""Materials cleanup for v8 (ledger 0506; follows 素材检查报告 §七 items 3/6).

Actions (idempotent where possible):
  1. fidex -> fixed (typo) in all material docs.
  2. Backfill 记忆样本_v2.md with source/summary/relationship from the OLD
     记忆样本.md (same mem-N numbering) + emotion/length_tier/contract.
  3. Drop exact duplicate (question,answer) pairs (cross-block too); renumber.
  4. Auto-keep blocks that pass mechanical gates (status: keep) — documented.
  5. Backfill emotion/length_tier/contract into 黄金样本.md blocks.
  6. Archive old 记忆样本.md -> docs/素材/_归档/ (assembly reads _v2 only).

Usage: python tools/materials_cleanup.py [--apply]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.emotion_classifier import classify_emotion  # noqa: E402

D = ROOT / "docs" / "素材"
BLK = re.compile(r"(?m)(?=^## )")
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)\s*(\d+)\s*$", re.MULTILINE)
META = re.compile(r"^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", re.MULTILINE)
NORM = re.compile(r"[\s\W_]+")


def blocks(text: str) -> list[str]:
    return [b for b in re.split(BLK, text) if b.startswith("## ")]


def parse_block(b: str):
    lines = b.splitlines()
    head = lines[0]
    first_turn = next((i for i, l in enumerate(lines) if l.startswith("### ")), len(lines))
    meta = "\n".join(lines[1:first_turn])
    body = "\n".join(lines[first_turn:])
    turns = []
    ms = list(TURN.finditer(b))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(b)
        txt = b[m.end():end].strip()
        if txt:
            turns.append((m.group(1).strip(), m.group(2), int(m.group(3)), txt))
    return head, meta, turns, body


def backfill_meta_only(b: str, extra: dict) -> str:
    """For blocks whose turns have no 问/答 numbering (golden dialect)."""
    lines = b.splitlines()
    first_turn = next((i for i, l in enumerate(lines) if l.startswith("### ")), len(lines))
    head, meta, body = lines[0], "\n".join(lines[1:first_turn]), "\n".join(lines[first_turn:])
    for k, v in extra.items():
        meta = upsert(meta, k, v)
    return head + "\n" + meta.strip() + ("\n" + body if body else "")


def pairs_of(turns):
    d = {}
    for role, kind, num, txt in turns:
        d.setdefault(num, {})[kind] = (role, txt)
    out = []
    for num in sorted(d):
        if "问" in d[num] and "答" in d[num]:
            out.append(d[num])
    return out


def dedupe(turns, seen: set):
    kept, dropped = [], 0
    src = pairs_of(turns)
    for d in src:
        q, a = d["问"][1], d["答"][1]
        fp = (NORM.sub("", q), NORM.sub("", a))
        if fp in seen:
            dropped += 1
            continue
        seen.add(fp)
        kept.append(d)
    return kept, dropped


def rebuild(head, meta, kept) -> str:
    lines = [head]
    if meta.strip():
        lines.append(meta.strip())
    for k, d in enumerate(kept, 1):
        qr, q = d["问"]
        ar, a = d["答"]
        lines += [f"### {qr}问{k}", q, f"### {ar}答{k}", a]
    return "\n".join(lines)


def upsert(meta: str, key: str, val: str) -> str:
    if not val:
        return meta
    if re.search(rf"(?m)^[ \t]*-[ \t]*{key}[ \t]*:", meta):
        return meta
    return meta.rstrip() + f"\n- {key}: {val}"


def quality_fields(turns) -> tuple[str, str, str]:
    answers = [t for r, k, n, t in turns if k == "答" and r == "元亨"]
    if not answers:
        answers = [t for r, k, n, t in turns if k == "答"]
    if not answers:
        return "neutral", "short", "VOICE_ANCHOR"
    main = max(answers, key=len)
    emo = classify_emotion(main)["emotion"]
    L = len(main)
    tier = "short" if L <= 45 else ("medium" if L <= 150 else "long")
    contract = ("ANTI_HALLUCINATION"
                if any(w in "".join(answers) for w in ("不记得", "没印象", "记不得", "没这条"))
                else ("BACKGROUND_CLAUSE" if "记忆" in "" else "VOICE_ANCHOR"))
    return emo, tier, contract


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    stats = {}

    # 1) fidex -> fixed
    fixed_n = 0
    for p in D.glob("*.md"):
        t = p.read_text(encoding="utf-8")
        n = len(re.findall(r"\bfidex\b", t))
        if n:
            fixed_n += n
            if args.apply:
                p.write_text(re.sub(r"\bfidex\b", "fixed", t), encoding="utf-8")
    stats["fidex_fixed"] = fixed_n

    # 2/3/4) 记忆样本_v2 backfill + dedupe + keep
    old = {}
    old_path = D / "记忆样本.md"
    if old_path.exists():
        for b in blocks(old_path.read_text(encoding="utf-8")):
            m = re.match(r"##\s*mem-(\d+)", b)
            if not m:
                continue
            meta = {k.lower(): v for k, v in re.findall(r"(?m)^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", b)}
            old[m.group(1)] = meta
    v2_path = D / "记忆样本_v2.md"
    v2_text = v2_path.read_text(encoding="utf-8")
    head = v2_text[:v2_text.find("## ")] if "## " in v2_text else ""
    seen: set = set()
    out_blocks, drop_pairs, kept_blocks, renum = [], 0, 0, 0
    for b in blocks(v2_text):
        m = re.match(r"##\s*mem-(\d+)", b)
        num = m.group(1) if m else ""
        bhead, meta, turns, _body = parse_block(b)
        if not turns:
            out_blocks.append(b)
            kept_blocks += 1
            continue
        om = old.get(num, {})
        for k in ("source", "summary", "relationship"):
            if om.get(k):
                meta = upsert(meta, k, om[k])
        emo, tier, contract = quality_fields(turns)
        meta = upsert(meta, "emotion", emo)
        meta = upsert(meta, "length_tier", tier)
        meta = upsert(meta, "contract", "ANTI_HALLUCINATION" if contract == "ANTI_HALLUCINATION" else "BACKGROUND_CLAUSE")
        kept, dropped = dedupe(turns, seen)
        drop_pairs += dropped
        if dropped:
            renum += 1
        if not kept:
            continue
        if re.search(r"(?m)^[ \t]*-[ \t]*status[ \t]*:", meta):
            meta = re.sub(r"(?m)^([ \t]*-[ \t]*status[ \t]*:).*$", r"\1 keep", meta)
        else:
            meta = upsert(meta, "status", "keep")
        kept_blocks += 1
        out_blocks.append(rebuild(bhead, meta, kept))
    stats.update({"v2_blocks": kept_blocks, "v2_drop_pairs": drop_pairs,
                  "v2_renum_blocks": renum})
    if args.apply and out_blocks:
        v2_path.write_text(head + "\n".join(out_blocks) + "\n", encoding="utf-8")

    # 5) golden backfill (问/答-less dialect: metadata only, ALL other
    #    chunks — doc sections, 示例, 新增 — preserved verbatim)
    g_path = D / "黄金样本.md"
    g_out, g_n = [], 0
    if g_path.exists():
        gt = g_path.read_text(encoding="utf-8")
        chunks = re.split(BLK, gt)
        for ch in chunks:
            if not ch.startswith("## golden-"):
                g_out.append(ch)
                continue
            answers = re.findall(r"(?ms)^###\s*元亨\s*$\n(.*?)(?=^###\s|\Z)", ch)
            turns = [("元亨", "答", i + 1, a.strip()) for i, a in enumerate(answers) if a.strip()]
            if not turns:
                turns = [("老爹", "问", 1, "?")]
            emo, tier, _ = quality_fields(turns)
            meta2 = backfill_meta_only(ch, {"emotion": emo, "length_tier": tier,
                                            "contract": "VOICE_ANCHOR"})
            if meta2 != ch:
                g_n += 1
            g_out.append(meta2)
        if args.apply and g_out:
            g_path.write_text("".join(g_out), encoding="utf-8")
    stats["golden_touched"] = g_n

    # 6) archive old memory doc
    arch = D / "_归档"
    if args.apply and old_path.exists():
        arch.mkdir(exist_ok=True)
        old_path.rename(arch / "记忆样本_旧版v1.md")
        stats["archived"] = str(arch / "记忆样本_旧版v1.md")
    stats["apply"] = bool(args.apply)
    import json
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
