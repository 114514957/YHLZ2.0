"""Rebalance self-reference voices in 对话样本.md toward the spec quota (P1-1).

Spec: 元亨 answer turns 我45% / 咱20% / 本小姐20% / 老娘10% / 元亨5%, with
emotion consistency (平静用我；得意/轻快用本小姐；激动/生气用老娘).

Answer-level plan (deterministic, saved to cache/tmp/selfref_plan.jsonl):
  - happy answers        -> 本小姐 (until global quota, else 我)
  - angry answers        -> 老娘   (until quota, else 我)
  - surprised answers    -> 元亨 only as the FIRST answer of selected blocks
                            (until quota), else 我/本小姐
  - neutral/calm/sad     -> 咱 until quota, else 我
Rewrites are done per block via DeepSeek (all answers with per-answer target
refs), hard-validated (family present, tier bounds, no brackets/markdown,
no trailing question), checkpointed to cache/tmp/selfref_rewrites.jsonl.

Usage:
    python tools/selfref_rebalance.py --plan
    python tools/selfref_rebalance.py --run --offset 0 --limit 500
    python tools/selfref_rebalance.py --apply
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
PLAN = ROOT / "cache" / "tmp" / "selfref_plan.jsonl"
SIDE = ROOT / "cache" / "tmp" / "selfref_rewrites.jsonl"
BLK = re.compile(r"(?m)(?=^## )")
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)\s*(\d+)\s*$", re.MULTILINE)
REFS = ("本小姐", "老娘", "元亨", "咱")
QUOTA = {"我": 0.45, "咱": 0.20, "本小姐": 0.20, "老娘": 0.10, "元亨": 0.05}
FAM_OF_EMO = {
    "happy": "本小姐", "angry": "老娘",
    "neutral": None, "calm": None, "sad": None, "surprised": None,
}


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


def meta_of(blk: str) -> dict:
    return {m.group(1).lower(): m.group(2).strip()
            for m in re.finditer(r"(?m)^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", blk)}


def ref_of(text: str) -> str:
    for r in REFS:
        if r in text:
            return r
    return "我"


def build_plan() -> list[dict]:
    blks = blocks()
    answers = []  # (head, idx, text, emotion, tier)
    heads = {}
    for b in blks:
        head = b.splitlines()[0]
        meta = meta_of(b)
        emo, tier = meta.get("emotion", "neutral"), meta.get("length_tier", "short")
        ai = 0
        for role, kind, num, txt in parse_turns(b):
            if kind == "答" and role == "元亨":
                answers.append({"head": head, "ai": ai, "emotion": emo, "tier": tier})
                ai += 1
        heads[head] = b
    total = len(answers)
    caps = {k: int(round(v * total)) for k, v in QUOTA.items()}
    cur = Counter()
    for a in answers:
        a["cur"] = ref_of(_answer_text(heads[a["head"]], a["ai"]))
        cur[a["cur"]] += 1
    # 咱 quota: fill from neutral/calm/sad answers currently 我, biggest-value first
    deficit_za = max(0, caps["咱"] - cur["咱"])
    for a in answers:
        if deficit_za <= 0:
            break
        if a["emotion"] in ("neutral", "calm", "sad") and a["cur"] == "我":
            a["target"] = "咱"
            deficit_za -= 1
    # 本小姐 quota: happy answers first
    deficit_ben = max(0, caps["本小姐"] - cur["本小姐"])
    for a in answers:
        if deficit_ben <= 0:
            break
        if a["emotion"] == "happy" and a.get("target") is None and a["cur"] != "本小姐":
            a["target"] = "本小姐"
            deficit_ben -= 1
    # 老娘 quota: angry answers first
    deficit_lao = max(0, caps["老娘"] - cur["老娘"])
    for a in answers:
        if deficit_lao <= 0:
            break
        if a["emotion"] == "angry" and a.get("target") is None and a["cur"] != "老娘":
            a["target"] = "老娘"
            deficit_lao -= 1
    # 元亨 quota: first answer of surprised blocks
    deficit_yh = max(0, caps["元亨"] - cur["元亨"])
    seen_heads = set()
    for a in answers:
        if deficit_yh <= 0:
            break
        if (a["emotion"] == "surprised" and a["ai"] == 0
                and a["head"] not in seen_heads and a["cur"] != "元亨"):
            a["target"] = "元亨"
            seen_heads.add(a["head"])
            deficit_yh -= 1
    # leftovers: keep current if consistent, else 我
    for a in answers:
        if a.get("target") is None:
            allowed = ("我", "咱") if a["emotion"] in ("neutral", "calm", "sad") \
                else (("我", "本小姐") if a["emotion"] in ("happy", "surprised")
                      else ("我", "老娘"))
            a["target"] = a["cur"] if a["cur"] in allowed else "我"
    # group by block
    by_head = {}
    for a in answers:
        by_head.setdefault(a["head"], []).append(a)
    plan = []
    for head, arr in by_head.items():
        arr.sort(key=lambda x: x["ai"])
        if all(a["target"] == a["cur"] for a in arr):
            continue
        plan.append({"head": head, "tier": arr[0]["tier"],
                     "targets": [a["target"] for a in arr],
                     "current": [a["cur"] for a in arr]})
    return plan, total, cur


def _answer_text(blk: str, idx: int) -> str:
    out = []
    for role, kind, num, txt in parse_turns(blk):
        if kind == "答" and role == "元亨":
            out.append(txt)
    return out[idx] if idx < len(out) else ""


def ds_call(key, user):
    import urllib.request
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": "你是中文对话润色器，只输出 JSON，不解释。"},
                     {"role": "user", "content": user}],
        "temperature": 0.7, "max_tokens": 3000, "stream": False,
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
        plan, total, cur = build_plan()
        PLAN.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in plan) + "\n",
                        encoding="utf-8")
        tgt = Counter()
        for p in plan:
            for t in p["targets"]:
                tgt[t] += 1
        print(f"answers={total} current={dict(cur)}")
        print(f"blocks_to_rewrite={len(plan)} target_deltas={dict(tgt)}")
        return 0

    if args.run:
        key = cr.load_key()
        if not key:
            print("[error] 缺 DEEPSEEK_API_KEY")
            return 2
        blks = {b.splitlines()[0]: b for b in blocks()}
        plan = [json.loads(l) for l in PLAN.read_text(encoding="utf-8").splitlines() if l.strip()]
        done = set()
        if SIDE.exists():
            for line in SIDE.read_text(encoding="utf-8").splitlines():
                try:
                    done.add(json.loads(line)["head"])
                except Exception:  # noqa: BLE001
                    pass
        todo = [p for p in plan if p["head"] not in done]
        todo = todo[args.offset:]
        if args.limit:
            todo = todo[: args.limit]
        print(f"todo={len(todo)}")
        ok = fail = 0
        for p in todo:
            b = blks.get(p["head"])
            if not b:
                continue
            answers = [t for r, k, n, t in parse_turns(b) if k == "答" and r == "元亨"]
            asks = [t for r, k, n, t in parse_turns(b) if k == "问"]
            tgt = "、".join(p["targets"])
            prompt = (
                f"这是元亨（活泼傲娇的中文角色）对话块。改写要求：把元亨的**每一条答话**"
                f"改写为自带对应自称（依次为：{tgt}），保持原意与信息量；"
                f"长度档={p['tier']}（short≤30字 / medium 60–120字 / long 200–400字）；"
                f"口语自然、不添加括号/markdown/表情；结尾不用问号；"
                f"非元亨角色的台词不要动。\n"
                f"输出 JSON：{{\"answers\": [...]}}，条数必须={len(answers)}。\n\n"
                f"对话上下文：\n" + "\n".join(asks[:3]) +
                "\n\n原答话：\n" + "\n---\n".join(answers))
            try:
                txt = ds_call(key, prompt)
                arr = json.loads(txt[txt.find("{"): txt.rfind("}") + 1]).get("answers") or []
            except Exception:  # noqa: BLE001
                fail += 1
                continue
            if len(arr) != len(answers):
                fail += 1
                continue
            tier = p["tier"]
            lim = 30 if tier == "short" else (150 if tier == "medium" else 450)
            if any(len(a) > lim for a in arr):
                fail += 1
                continue
            if tier == "long" and max(len(a) for a in arr) < 200:
                fail += 1
                continue
            if any("（" in a and "）" in a for a in arr) or any("**" in a for a in arr):
                fail += 1
                continue
            if any(a.rstrip().endswith(("？", "?")) for a in arr):
                fail += 1
                continue
            oklist = []
            for a, t in zip(arr, p["targets"]):
                if t == "我" and any(x in a for x in ("本小姐", "老娘")):
                    fail += 1
                    oklist = []
                    break
                if t != "我" and t not in a:
                    fail += 1
                    oklist = []
                    break
                oklist.append(a)
            if not oklist:
                continue
            with SIDE.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"head": p["head"], "answers": oklist},
                                   ensure_ascii=False) + "\n")
            ok += 1
            if ok % 25 == 0:
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
                if kind == "答" and role == "元亨" and ai < len(r["answers"]):
                    parts.append(r["answers"][ai])
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
