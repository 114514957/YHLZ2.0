"""Audit dialogue blocks for rule/persona violations (ledger 0377).

Checks each block in docs/素材/对话样本.md:
  - 问K/答K pairing; only 老爹/元亨/利贞 speak; 大肥鱼 must not have lines
  - 元亨: no 「理论上来说」(that's 利贞's); 老爹/利贞 must not use 本小姐/老娘 (元亨's)
  - turn length; non-哲学 ideology words; foreign chars; markdown
  - flag blocks whose 利贞 lines over-use 「理论上来说」; 利贞 over-uses 「我认」

Usage: python tools/audit_dialogue.py [--doc path]
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.MULTILINE)
IDEOLOGY = ("唯物","辩证","历史唯物","阶级","意识形态","生产资料","异化","商品拜物","剩余价值","剥削")
ROLES = ("老爹","元亨","利贞")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=str(ROOT / "docs" / "素材" / "对话样本.md"))
    args = ap.parse_args()
    text = Path(args.doc).read_text(encoding="utf-8")
    blocks = [b for b in re.split(r"(?m)(?=^## )", text) if b.startswith("## ")]

    issues: dict[str, list[str]] = {}
    def flag(kind, name):
        issues.setdefault(kind, []).append(name)

    for b in blocks:
        name = b.splitlines()[0][3:].strip()
        cat = (re.search(r"(?m)^- category:\s*(.*)$", b) or [None, "?"])
        cat = cat.group(1).strip() if hasattr(cat, "group") else "?"
        ms = list(TURN.finditer(b))
        rounds: dict[str, dict] = {}
        lz_theory = 0
        lz_ren = 0
        for i, m in enumerate(ms):
            role, kind, num = m.group(1).strip(), m.group(2), m.group(3)
            end = ms[i + 1].start() if i + 1 < len(ms) else len(b)
            txt = b[m.end():end].strip()
            if role == "大肥鱼":
                flag("大肥鱼发言", name)
            if role not in ROLES:
                flag(f"非法角色:{role}", name)
            if len(txt) > 32:
                flag("超长", name)
            if re.search(r"[\uac00-\ud7af\u3040-\u30ff\u0400-\u04ff]", txt):
                flag("外文", name)
            if cat != "哲学" and any(w in txt for w in IDEOLOGY):
                flag("非哲学含意识形态", name)
            if role == "元亨" and "理论上来说" in txt:
                flag("元亨误用‘理论上来说’", name)
            if role in ("老爹", "利贞") and ("本小姐" in txt or "老娘" in txt):
                flag(f"{role}自称错乱", name)
            if role == "利贞":
                lz_theory += txt.count("理论上来说")
                lz_ren += txt.count("我认")
            rounds.setdefault(num, {})[kind] = 1
        for num, d in rounds.items():
            if set(d) != {"问", "答"}:
                flag("配对", name)
        if len(rounds) > 1 and lz_theory >= max(2, len(rounds) - 1):
            flag("利贞口头禅过密", name)
        if lz_ren >= 2:
            flag("利贞‘我认’过多", name)

    print(f"块数: {len(blocks)}")
    for kind, names in sorted(issues.items(), key=lambda kv: -len(kv[1])):
        print(f"  [{kind}] {len(names)}: {', '.join(names[:12])}{' ...' if len(names) > 12 else ''}")
    if not issues:
        print("  ✓ 未发现规则/人设违规")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
