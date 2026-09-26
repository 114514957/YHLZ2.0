"""Harvest REAL 老爹<->元亨 pairs from cache/sessions -> 真实对话样本.md (spec §A).

Verbatim, no polishing. Scheduler-driven sessions (自主时刻/计划表) are excluded
— they are not natural conversation and would re-teach "内在因当台词".
Group sessions (other people) are included with relationship=朋友.

Usage: python tools/real_dialogue_build.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.emotion_classifier import classify_emotion  # noqa: E402

SESS = ROOT / "cache" / "sessions"
OUT = ROOT / "docs" / "素材" / "真实对话样本.md"
OWNER_FILES = ("console.json", "cook.json", "default.json", "qq_public.json")
OWNER_PREFIX = ("qq_qq_p", "archive_")

JUNK = re.compile(r"^[\W_?？!！。.．,，\s]*$")
SCHED_PREFIX = ("（计划表到点）", "(计划表到点)", "（系统", "[系统", "系统提示",
                "这是你的自主时刻")
META_MARK = ("元亨的内部状态", "**已锁定**", "**最终确认**", "（自主时刻）", "**内在因**")


def tier_of(n: int) -> str:
    return "short" if n <= 45 else ("medium" if n <= 150 else "long")


def _junk(s: str) -> bool:
    return bool(JUNK.match(s)) or len(re.sub(r"[\W_]", "", s)) < 2


def _sched(q: str, a: str) -> bool:
    return (any(q.startswith(s) for s in SCHED_PREFIX)
            or any(m in a for m in META_MARK)
            or "**" in a or "**" in q)


def _collect(seen: set) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for p in sorted(SESS.glob("*.json")):
        if not (p.name in OWNER_FILES or any(p.name.startswith(x) for x in OWNER_PREFIX)):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        cur_q = None
        for m in d.get("history") or []:
            role, content = m.get("role"), (m.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                cur_q = content
            elif role == "assistant" and cur_q:
                fp = re.sub(r"\s+", "", cur_q + content)
                if (fp not in seen and not _junk(cur_q) and not _junk(content)
                        and not _sched(cur_q, content)):
                    seen.add(fp)
                    out.append((cur_q, content, p.name))
                cur_q = None
    persona = ROOT / "data" / "finetune" / "sft_persona.jsonl"
    if persona.exists():
        for line in persona.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            q = next((m["content"] for m in r.get("messages", []) if m.get("role") == "user"), "")
            a = next((m["content"] for m in r.get("messages", []) if m.get("role") == "assistant"), "")
            q, a = (q or "").strip(), (a or "").strip()
            if not q or not a or _junk(q) or _junk(a) or _sched(q, a):
                continue
            fp = re.sub(r"\s+", "", q + a)
            if fp in seen:
                continue
            seen.add(fp)
            out.append((q, a, r.get("source") or "sft_persona"))
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    seen: set = set()
    pairs_all = _collect(seen)
    owner = [x for x in pairs_all if not x[2].startswith("qq_qq_g")]
    friend = [x for x in pairs_all if x[2].startswith("qq_qq_g")]
    blocks = []
    for tag, lst in (("老爹", owner), ("朋友", friend)):
        by_src: dict[str, list[tuple[str, str]]] = {}
        for q, a, src in lst:
            by_src.setdefault(src, []).append((q, a))
        for src, ps in by_src.items():
            lines = [f"## real-{src}",
                     f"- source: {src}",
                     f"- summary: {ps[0][0][:40]}",
                     f"- relationship: {tag}",
                     "- status: keep",
                     f"- emotion: {classify_emotion(ps[0][1])['emotion']}",
                     f"- length_tier: {tier_of(len(ps[0][1]))}",
                     "- contract: VOICE_ANCHOR"]
            for k, (q, a) in enumerate(ps, 1):
                lines += [f"### {tag}问{k}", q, f"### 元亨答{k}", a]
            blocks.append("\n".join(lines))
    header = ("# 元亨真实对话样本（原样保留·不得润色）\n\n"
              "> `tools/real_dialogue_build.py` 采集：`cache/sessions/*.json` + "
              "`data/finetune/sft_persona.jsonl`；排除系统驱动会话；"
              "老爹↔元亨为 A 维度，群聊对象标「朋友」。\n\n")
    text = header + "\n\n".join(blocks) + "\n"
    if args.apply:
        OUT.write_text(text, encoding="utf-8")
    print(json.dumps({"blocks": len(blocks), "pairs": len(pairs_all),
                      "owner": len(owner), "friend": len(friend),
                      "apply": bool(args.apply), "out": str(OUT)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
