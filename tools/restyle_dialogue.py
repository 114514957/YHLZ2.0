"""Restyle existing dialogue blocks to the CURRENT persona (ledger 0378).

Keeps topic and round count; rewrites tone/self-reference/catchphrase. Uses the
scene_dataset persona + gates; replaces turns in place (keeps header/category).

Usage:
    python tools/restyle_dialogue.py --n 8            # 预览前 8 个候选块
    python tools/restyle_dialogue.py --n 8 --write    # 写回
    python tools/restyle_dialogue.py --match 故事-
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools.scene_dataset as sd  # noqa: E402
from tools.scene_dataset import _gemma, _check_turns, _normalize, parse  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "素材" / "对话样本.md"
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.MULTILINE)


def turns_of(blk):
    ms = list(TURN.finditer(blk))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
        out.append((m.group(1).strip(), m.group(2), int(m.group(3)), blk[m.end():end].strip()))
    return ms[0].start() if ms else None, out


def render_turns(turns):
    out = []
    for r, k, n, t in turns:
        out.append(f"### {r}{k}{n}\n{t}")
    return "\n".join(out) + "\n"


def split_roles(turns):
    out = []
    for r, k, n, t in turns:
        segs = re.split(r"；?(老爹|元亨|利贞)：", t)
        out.append((r, k, n, segs[0].strip()))
        j = 1
        while j + 1 < len(segs):
            out.append((segs[j], k, n, segs[j + 1].strip()))
            j += 2
    return [x for x in out if x[3]]


def thin_theory(turns, keep=1):
    seen = 0
    out = []
    for r, k, n, t in turns:
        if "理论上来说" in t:
            if seen >= keep:
                t = re.sub(r"[，,]理论上来说([。！？]?)", r"\1", t)
            else:
                seen += 1
        out.append((r, k, n, t))
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--match", default=None)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    text = DOC.read_text(encoding="utf-8")
    parts = re.split(r"(?m)(?=^## )", text)
    targets = []
    for idx, b in enumerate(parts):
        if not b.startswith("## "):
            continue
        if "- status: keep" in b.split("###")[0]:
            continue
        if args.match and args.match not in b.splitlines()[0]:
            continue
        targets.append(idx)
    targets = targets[: args.n]

    done = 0
    for idx in targets:
        b = parts[idx]
        name = b.splitlines()[0][3:].strip()
        cat_m = re.search(r"(?m)^- category:\s*(.*)$", b)
        cat = cat_m.group(1).strip() if cat_m else "故事"
        start, turns = turns_of(b)
        if not turns:
            continue
        head = b[:start]
        orig = "\n".join(f"{r}{k}{n}：{t}" for r, k, n, t in turns)
        user = ("把下面这段对话，按你的**人设与风格**重写。保持题材与轮数不变，但**必须体现当前设定**：\n"
                "- 元亨：活泼·乐观·傲娇·**毒舌**（会吐槽、一针见血），**哲学由她主讲**；\n"
                "- 利贞：稳重·博学·直接、**技术由她主讲**，句尾**偶尔**「，理论上来说」（每 3–5 句一次，别每句都挂）；\n"
                "- 老爹：懒散、爱开玩笑；大肥鱼：**不发言**（只被提起）。\n"
                "每行**一个角色**，输出 `### 角色问K` / `### 角色答K`，每轮恰好一问一答。\n\n" + orig)
        try:
            out = _gemma(sd.PERSONA, user)
        except Exception as e:  # noqa: BLE001
            print(f"[skip] {name} :: {type(e).__name__}")
            continue
        nt = parse(out)
        if nt is None or _check_turns(nt, cat):
            print(f"[skip] {name} :: 校验不过")
            continue
        nn = thin_theory(split_roles(_normalize(nt)), keep=1)
        if args.write:
            parts[idx] = head + render_turns(nn) + "\n"
        done += 1
        if not args.write:
            print(f"===== {name} =====")
            print("--- 旧 ---"); print(orig)
            print("--- 新 ---"); print("\n".join(f"{r}{k}{n}：{t}" for r, k, n, t in nn))
    print(("written: " if args.write else "[dry] would restyle: ") + str(done))
    if args.write:
        DOC.write_text("".join(parts), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
