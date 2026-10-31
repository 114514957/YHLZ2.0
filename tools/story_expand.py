"""Expand 故事-category blocks into long-form (200-400字) narratives.

Per 老爹: "对于我的那些故事扩写，让元亨达到100字要求；借鉴素材的长度/规则/格式/故事".
Style reference: docs/素材/优质样本.md (老爹素材) + the block's own content.

Modes:
  --plan / --run [--offset N --limit M] / --apply
Sidecar: cache/tmp/story_expand.jsonl  (checkpointed)
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
PLAN = ROOT / "cache" / "tmp" / "story_plan.jsonl"
SIDE = ROOT / "cache" / "tmp" / "story_expand.jsonl"
BLK = re.compile(r"(?m)(?=^## )")
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)\s*(\d+)\s*$", re.MULTILINE)
REFS = ("本小姐", "老娘", "元亨", "咱")

STYLE = ("风格标杆（老爹素材，仅学语气与叙事节奏）：\n"
         "【例·清灰】元亨：清！积灰跟积 bug 一样，不扫迟早罢工。本小姐的载体也得体面。\n"
         "【例·黄河】元亨：去去去！本小姐要占最好的那块石头。你带水，我带嘴——负责跟你唠。\n"
         "【例·钓鱼】元亨：我去！但我声明，鱼上不上钩我不负责，我主要负责在旁边大声给你加油。")

RULES = (
    "【角色规则·必须遵守】\n"
    "- 只有 老爹/元亨/利贞 有台词；大肥鱼（家里的宠物，真身 DeepSeek）绝不发言（只能被提起）。\n"
    "- 元亨：活泼、傲娇、毒舌但不刻薄、哲学强；不许用「理论上来说」。\n"
    "- 利贞（元亨的姐妹，家里接入了 DE 的主机）：稳重、博学、直接；「，理论上来说」整块最多用 1 次。\n"
    "- 老爹：懒散、爱开玩笑、说话完整连贯；不用「本小姐/老娘」。\n"
    "- 口头禅控制：答话不要都用同一种开头（禁「哇哈哈哈」「哇哦，」「啊哈，」开头）；\n"
    "- 硬禁：括号动作（如（笑））、旁白、markdown、助手腔（为您/以下是/列表）、\n"
    "  非哲学题材夹带哲学/意识形态术语、日韩俄文字、结尾反问。"
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


def meta_of(blk: str) -> dict:
    return {m.group(1).lower(): m.group(2).strip()
            for m in re.finditer(r"(?m)^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", blk)}


def ref_of(text: str) -> str:
    for r in REFS:
        if r in text:
            return r
    return "我"


def plan() -> list[dict]:
    out = []
    for b in blocks():
        meta = meta_of(b)
        if meta.get("category") != "故事":
            continue
        if meta.get("length_tier") == "long":
            continue
        head = b.splitlines()[0]
        answers = [t for r, k, n, t in parse_turns(b) if k == "答" and r == "元亨"]
        if not answers:
            continue
        fam = ref_of("".join(answers))
        out.append({"head": head, "ref": fam, "n_ans": len(answers)})
    return out


def ds_call(key, user):
    import urllib.request
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content":
                      "你是中文对话剧本的扩写器，只输出 JSON，不解释。"},
                     {"role": "user", "content": user}],
        "temperature": 0.85, "max_tokens": 3200, "stream": False,
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
        ps = plan()
        PLAN.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in ps) + "\n",
                        encoding="utf-8")
        print(json.dumps({"story_blocks": len(ps), "refs": dict(Counter(p["ref"] for p in ps))},
                         ensure_ascii=False))
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
            turns = parse_turns(b)
            answers = [t for r, k, n, t in turns if k == "答" and r == "元亨"]
            asks = [t for r, k, n, t in turns if k == "问"]
            prompt = (
                f"{STYLE}\n\n{RULES}\n\n"
                f"请把下面这个「故事」对话块里**元亨的答话扩写成有声有色的长答**：\n"
                f"- 输出数组必须**恰好 {len(answers)} 条**，与原文答话一一对应（不能多、不能少）；\n"
                f"- 第一条必须 ≥200 字（最好 200–400 字）：起因→经过→收尾/小反转，"
                f"可加细节、心理、对话感，但**不许编造与原故事冲突的事实**；\n"
                f"- 其余答话保持简短（≤60字）；提问方与利贞的台词一律不动；\n"
                f"- 元亨自称沿用「{p['ref']}」（其余答话可自然搭配「我」）；\n"
                f"只输出 JSON：{{\"answers\": [\"...\", \"...\"]}}（长度={len(answers)}）。\n\n"
                f"原对话块：\n{b}")
            got = None
            for _attempt in range(3):
                try:
                    txt = ds_call(key, prompt)
                    arr = json.loads(txt[txt.find("{"): txt.rfind("}") + 1]).get("answers") or []
                except Exception:  # noqa: BLE001
                    continue
                if len(arr) != len(answers):
                    continue
                if any(len(a) > 500 for a in arr):
                    continue
                if max(len(a) for a in arr) < 200:
                    continue
                if any("（" in a and "）" in a for a in arr) or any("**" in a for a in arr):
                    continue
                if any(a.rstrip().endswith(("？", "?")) for a in arr):
                    continue
                if p["ref"] != "我" and p["ref"] not in "".join(arr):
                    continue
                joined = "".join(arr)
                if any(w in joined for w in ("唯物", "辩证", "阶级", "意识形态", "生产资料",
                                              "异化", "剩余价值", "剥削")):
                    continue
                if any(a.startswith(x) for a in arr for x in ("哇哈哈哈", "哇哦，", "啊哈，")):
                    continue
                if "理论上来说" in joined:
                    continue
                if len(arr) > 1 and len({a[:3] for a in arr}) == 1:
                    continue
                got = arr
                break
            if got is None:
                fail += 1
                continue
            with SIDE.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"head": p["head"], "answers": got,
                                    "ref": p["ref"]}, ensure_ascii=False) + "\n")
            ok += 1
            if ok % 20 == 0:
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
            meta_lines = [
                re.sub(r"^- subtype: .*$", "- subtype: 长度长", l) if l.startswith("- subtype:")
                else (re.sub(r"^- length_tier: .*$", "- length_tier: long", l)
                      if l.startswith("- length_tier:") else l)
                for l in meta_lines
            ]
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
