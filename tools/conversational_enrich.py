"""Enrich 元亨 answers with conversational patterns (dialogue feel, not Q&A).

Per 老爹: add 设问/双重否定/感叹/单语气词/尾句反问/举例 — make it sound like
talking, not answering.

Patterns to inject (natural mix, not every answer gets all):
  语气词开头: 不是哥们！/ 哇！/ 哎呦！/ 好家伙！/ 切！/ 嘿！/ 啊这… / 我的天！
  设问: 你猜怎么着？/ 为啥？/ 问题在哪？/ 怎么说？/ 啥意思？
  尾句反问: 对不对？/ 对吧？/ 是吧？/ 你说呢？
  举例: 就拿…来说 / 比如 / 打个比方 / 你想想
  双重否定: 不是不行 / 不得不说 / 不是不 / 并非不

Overrides old rules:
  - ALLOW trailing 对不对/对吧/是吧/你说呢 (conversational tag questions)
  - ALLOW interjection openers (不/哇/哎/好/切/嘿/啊/我)
  - STILL BAN: 你觉得呢/要不要我/怎么样 (old trailing ban)
  - STILL BAN: 哇哈哈哈/哇哦，/啊哈， (口癖 openers)
  - STILL BAN: brackets/markdown/assistant tone/foreign

Usage: --plan / --run [--offset --limit] / --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tools.cloud_rewrite as cr  # noqa: E402

DOC = ROOT / "docs" / "素材" / "对话样本.md"
PLAN = ROOT / "cache" / "tmp" / "conv_plan.jsonl"
SIDE = ROOT / "cache" / "tmp" / "conv_enrich.jsonl"
BLK = re.compile(r"(?m)(?=^## )")
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)\s*(\d+)\s*$", re.MULTILINE)
REFS = ("本小姐", "老娘", "元亨", "咱")
ALLOWED_TRAIL = ("对不对", "对吧", "是吧", "你说呢")
BANNED_TRAIL = ("你觉得呢", "要不要我", "怎么样")
BANNED_OPEN = ("哇哈哈哈", "哇哦，", "啊哈，")
STYLE_EXAMPLES = (
    "【风格示范（对比）】\n"
    "Q: 今天吃啥？\n"
    "A（旧·答题式）: 我要吃烤肉。\n"
    "A（新·对话式）: 烤肉啊！不是我说，这都几点了还纠结？就拿上次那家店来说，"
    "肉一上来你就抢，对不对？\n"
    "——有语气词开头（烤肉啊！）、有反问（这都几点了还纠结？）、有举例（就拿上次那家店来说）、"
    "有尾句反问（对不对？）。\n"
    "再来一个：\n"
    "Q: 利贞，这个 bug 怎么修？\n"
    "A: 哎呦，这还不简单？你猜怎么着——先加个断言试试，不是不行的。"
    "就拿上次那个超时来说，加了断言一眼就看出来了，对吧？"
)


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


def ref_of(text: str) -> str:
    for r in REFS:
        if r in text:
            return r
    return "我"


def plan(target_fraction: float = 0.35) -> list[dict]:
    out = []
    for b in blocks():
        answers = [t for r, k, n, t in parse_turns(b) if k == "答" and r == "元亨"]
        if not answers:
            continue
        # skip if already conversational (has interjection/rhetorical/example)
        joined = "".join(answers)
        already = any(x in joined for x in ("对不对", "对吧", "是吧", "你说呢",
                                             "你猜怎么着", "就拿", "比如说", "打个比方"))
        if already:
            continue
        fam = ref_of(joined)
        out.append({"head": b.splitlines()[0], "ref": fam, "n": len(answers)})
    # sample target_fraction
    import random
    rng = random.Random(20260927)
    rng.shuffle(out)
    n_target = int(round(target_fraction * len(out)))
    out = out[:n_target]
    out.sort(key=lambda p: p["head"])
    return out


def ds_call(key, user):
    import urllib.request
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content":
                      "你是中文对话润色器，只输出 JSON，不解释。"},
                     {"role": "user", "content": user}],
        "temperature": 0.85, "max_tokens": 3200, "stream": False,
        "thinking": {"type": "disabled"}}).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"].get("content", "")


def validate(arr, answers, ref):
    if len(arr) != len(answers):
        return "条数不一致"
    for a in arr:
        if not a or len(a) < 4:
            return "太短"
        if "（" in a and "）" in a:
            return "括号"
        if "**" in a:
            return "markdown"
        if re.search(r"[\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff]", a):
            return "外文"
        tail = a.rstrip()
        if any(tail.endswith(b) for b in BANNED_TRAIL):
            return "禁用尾句"
        if any(a.startswith(b) for b in BANNED_OPEN):
            return "口癖开场"
    if ref != "我" and ref not in "".join(arr):
        return "缺自称"
    return ""


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
        ps = plan()
        PLAN.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in ps) + "\n",
                        encoding="utf-8")
        print(f"blocks_to_enrich={len(ps)}")
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
            answers = [t for r, k, n, t in parse_turns(b) if k == "答" and r == "元亨"]
            asks = [t for r, k, n, t in parse_turns(b) if k == "问"]
            prompt = (
                f"{STYLE_EXAMPLES}\n\n"
                f"请把下面对话块里**元亨的答话**改写得更有对话感（不是答题感）：\n"
                f"- 加入语气词开头（如：不是哥们！/ 哇！/ 哎呦！/ 好家伙！/ 切！/ 嘿！）或设问"
                f"（如：你猜怎么着？/ 为啥？/ 问题在哪？）或双重否定（如：不是不行 / 不得不说）\n"
                f"- 正常阐述观点时，尾句可以用「对不对？/ 对吧？/ 是吧？」收住（不是反问抛回，是确认语气）\n"
                f"- 用举例子来表达（就拿…来说 / 比如 / 打个比方），不要平铺直叙\n"
                f"- 保持原意与信息量；长度 ±30%；元亨自称「{p['ref']}」；提问方和利贞台词不动\n"
                f"- 输出 JSON：{{\"answers\": [...]}}，条数必须={len(answers)}\n\n"
                f"对话上下文：\n" + "\n".join(asks[:3]) +
                "\n\n原答话：\n" + "\n---\n".join(answers))
            got = None
            for _a in range(3):
                try:
                    txt = ds_call(key, prompt)
                    arr = json.loads(txt[txt.find("{"): txt.rfind("}") + 1]).get("answers") or []
                except Exception:  # noqa: BLE001
                    continue
                err = validate(arr, answers, p["ref"])
                if not err:
                    got = arr
                    break
            if got is None:
                fail += 1
                continue
            with SIDE.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"head": p["head"], "answers": got,
                                    "ref": p["ref"]}, ensure_ascii=False) + "\n")
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
