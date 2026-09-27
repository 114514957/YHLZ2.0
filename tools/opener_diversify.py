"""Diversify answer openers (口癖治理): reduce 「本小姐」-initial answers to <=2%.

The self-ref rebalance made many answers START with 本小姐 (new verbal tic).
Rewrite the opening of excess answers (keep 本小姐 inside the sentence so the
self-ref quota holds), validate, checkpoint, merge.

Usage: --plan / --run [--offset --limit] / --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tools.cloud_rewrite as cr  # noqa: E402

DOC = ROOT / "docs" / "素材" / "对话样本.md"
PLAN = ROOT / "cache" / "tmp" / "opener_plan.jsonl"
SIDE = ROOT / "cache" / "tmp" / "opener_rewrites.jsonl"
BLK = re.compile(r"(?m)(?=^## )")
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)\s*(\d+)\s*$", re.MULTILINE)
LEAD = "本小姐"


def blocks() -> list[str]:
    return [b for b in re.split(BLK, DOC.read_text(encoding="utf-8"))
            if b.startswith("## 对话-")]


def parse_turns(blk: str):
    ms = list(TURN.finditer(blk))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
        txt = blk[m.end():end].strip()
        if txt:
            out.append((m.group(1).strip(), m.group(2), int(m.group(3)), txt))
    return out


def lead_answers(blk: str) -> list[tuple[int, str]]:
    out = []
    ai = 0
    for role, kind, num, txt in parse_turns(blk):
        if kind == "答" and role == "元亨":
            if txt.startswith(LEAD):
                out.append((ai, txt))
            ai += 1
    return out


def plan() -> list[dict]:
    total = 0
    leads = []
    for b in blocks():
        for ai, txt in lead_answers(b):
            total += 1
    # total answers
    n_ans = sum(1 for b in blocks() for r, k, n2, t in parse_turns(b)
                if k == "答" and r == "元亨")
    budget = int(round(0.02 * n_ans))
    for b in blocks():
        la = lead_answers(b)
        if la:
            leads.append({"head": b.splitlines()[0], "idx": [i for i, _ in la],
                          "n": len(la)})
    # keep the first `budget` answers as-is; rewrite the rest
    out, kept = [], 0
    for p in leads:
        keep_idx, rewrite = [], []
        for i in p["idx"]:
            if kept < budget:
                kept += 1
            else:
                rewrite.append(i)
        if rewrite:
            out.append({"head": p["head"], "rewrite_idx": rewrite})
    return out, total, budget


def ds_call(key, user):
    import urllib.request
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": "你是中文对话润色器，只输出 JSON。"},
                     {"role": "user", "content": user}],
        "temperature": 0.8, "max_tokens": 2600, "stream": False,
        "thinking": {"type": "disabled"}}).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"].get("content", "")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.plan:
        ps, total, budget = plan()
        PLAN.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in ps) + "\n",
                        encoding="utf-8")
        print(json.dumps({"lead_answers": total, "keep_budget": budget,
                          "blocks_to_rewrite": len(ps)}, ensure_ascii=False))
        return 0

    if args.run:
        key = cr.load_key()
        if not key:
            print("[error] 缺 DEEPSEEK_API_KEY")
            return 2
        blks = {b.splitlines()[0]: b for b in blocks()}
        ps = [json.loads(l) for l in PLAN.read_text(encoding="utf-8").splitlines() if l.strip()]
        done = set()
        if SIDE.exists():
            for line in SIDE.read_text(encoding="utf-8").splitlines():
                try:
                    done.add(json.loads(line)["head"])
                except Exception:  # noqa: BLE001
                    pass
        todo = [p for p in ps if p["head"] not in done]
        todo = todo[args.offset:]
        if args.limit:
            todo = todo[: args.limit]
        print(f"todo={len(todo)}")
        ok = fail = 0
        for p in todo:
            b = blks.get(p["head"])
            if not b:
                continue
            answers = [t for r, k, n2, t in parse_turns(b) if k == "答" and r == "元亨"]
            need = {i: answers[i] for i in p["rewrite_idx"] if i < len(answers)}
            if not need:
                continue
            lines = [f"[{i}] {t}" for i, t in need.items()]
            prompt = (
                "下面每条是元亨（活泼傲娇中文角色）的答话。请**只改开头**，避免以「本小姐」"
                "三个字开头：把自称移到句中/句尾（必须仍保留「本小姐」至少一次），"
                "开头换成自然的语气词或短引导（如：行、走、那、哎、哼、别、听、今儿、这下…），"
                "不要用「哇哈哈哈/哇哦，/啊哈，」开头；保持原意与长度（±30%）、口语、无括号、"
                "结尾不用问号。\n"
                "输出 JSON：{\"answers\": {\"<序号>\": \"<改写后>\"}}（键为原序号字符串）。\n\n"
                + "\n".join(lines))
            got = None
            for _a in range(3):
                try:
                    txt = ds_call(key, prompt)
                    obj = json.loads(txt[txt.find("{"): txt.rfind("}") + 1]).get("answers") or {}
                except Exception:  # noqa: BLE001
                    continue
                good = True
                cleaned = {}
                for i, orig in need.items():
                    new = str(obj.get(str(i)) or "").strip()
                    if not new or new.startswith(LEAD):
                        good = False
                        break
                    if LEAD not in new:
                        good = False
                        break
                    if any(new.startswith(x) for x in ("哇哈哈哈", "哇哦，", "啊哈，")):
                        good = False
                        break
                    if "（" in new and "）" in new:
                        good = False
                        break
                    if new.rstrip().endswith(("？", "?")):
                        good = False
                        break
                    if not (0.6 * len(orig) <= len(new) <= 1.6 * len(orig)):
                        good = False
                        break
                    cleaned[i] = new
                if good:
                    got = cleaned
                    break
            if got is None:
                fail += 1
                continue
            with SIDE.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"head": p["head"], "answers": got},
                                   ensure_ascii=False) + "\n")
            ok += 1
            if ok % 30 == 0:
                print(f"  ok={ok} fail={fail}")
            time.sleep(0.15)
        print(json.dumps({"ok": ok, "fail": fail}, ensure_ascii=False))
        return 0

    if args.apply:
        rew = {}
        if SIDE.exists():
            for line in SIDE.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                    rew[r["head"]] = r
                except Exception:  # noqa: BLE001
                    pass
        out, n = [], 0
        for b in re.split(BLK, DOC.read_text(encoding="utf-8")):
            if not b.startswith("## 对话-") or b.splitlines()[0] not in rew:
                out.append(b)
                continue
            r = rew[b.splitlines()[0]]
            head = b.splitlines()[0]
            meta_lines = [l for l in b.splitlines()[1:] if l.startswith("- ")]
            parts = [head] + meta_lines
            ai = 0
            for role, kind, num, txt in parse_turns(b):
                parts.append(f"### {role}{kind}{num}")
                if kind == "答" and role == "元亨":
                    parts.append(r["answers"].get(str(ai), txt))
                    ai += 1
                else:
                    parts.append(txt)
            out.append("\n".join(parts) + "\n\n")
            n += 1
        DOC.write_text("".join(out), encoding="utf-8")
        print(json.dumps({"applied": n}, ensure_ascii=False))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
