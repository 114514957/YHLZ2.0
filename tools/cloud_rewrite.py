"""Rewrite memory samples into high-quality, current-persona samples via DeepSeek.

I (Yuanheng's hand) design the prompt; the cloud model writes; then the owner/agent
revises. Reads `docs/素材/记忆样本.md`, writes `docs/素材/记忆样本_v2.md`.

DeepSeek key: DEEPSEEK_API_KEY in the project `.env`.

Usage:
    python tools/cloud_rewrite.py --n 5            # 试跑 5 条 -> 记忆样本_v2.md
    python tools/cloud_rewrite.py --all
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MEM_DOC = ROOT / "docs" / "素材" / "记忆样本.md"
OUT_DOC = ROOT / "docs" / "素材" / "记忆样本_v2.md"
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.MULTILINE)

SYSTEM = (
    "你是「元亨」人格样本的润色器。把给定的记忆问答，改写为**符合当前人设的高质量样本**。\n"
    "人设与语气：\n"
    "- 元亨：活泼、乐观、傲娇、**毒舌**（会吐槽、一针见血，但不刻薄），**哲学由她主讲**。\n"
    "- 利贞：稳重、博学、直接，**技术由她主讲**；句尾**偶尔**加「，理论上来说」（每 3–5 句一次）。\n"
    "- 大肥鱼：是宠物，**不会说话**——绝不给它台词，只能被提起。\n"
    "- 老爹：懒散、爱开玩笑。\n"
    "硬规则：\n"
    "- 每条发言 ≤32 字；口语、俏皮；不要旁白、不要 Markdown。\n"
    "- 保持原题材/记忆锚不变，只焕新语气与角色分工。\n"
    "- 自称：元亨用「我/本小姐/老娘」；利贞、老爹只用「我」。\n"
    "- 输出格式：`### <角色>问K` / `### <角色>答K`，每轮恰好一问一答，2–3 轮。\n"
    "【风格样例】\n"
    "### 利贞问1\n元亨，这本《精神现象学》，你读过？\n"
    "### 元亨答1\n哼，黑格尔的代表作，西方哲学的“天书”之一。\n"
    "### 利贞问2\n天书？那它到底讲什么？\n"
    "### 元亨答2\n讲“意识”如何一步步，认识它自己。\n"
)


def load_key() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("DEEPSEEK_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DEEPSEEK_API_KEY", "")


def ds_chat(key: str, user: str) -> tuple[str, dict]:
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
        "temperature": 0.9, "max_tokens": 700, "stream": False,
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    return d["choices"][0]["message"].get("content", ""), d.get("usage", {})


def parse_turns(txt):
    ms = list(TURN.finditer(txt))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(txt)
        out.append((m.group(1).strip(), m.group(2), int(m.group(3)), txt[m.end():end].strip()))
    return out


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


def load_memory_blocks():
    if not MEM_DOC.exists():
        return []
    blocks = []
    for blk in re.split(r"(?m)(?=^## )", MEM_DOC.read_text(encoding="utf-8")):
        if not blk.startswith("## "):
            continue
        ms = list(TURN.finditer(blk))
        if ms:
            works = []
            for i, m in enumerate(ms):
                end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
                works.append(f"{m.group(1).strip()}{m.group(2)}{m.group(3)}：{blk[m.end():end].strip()}")
            name = blk.splitlines()[0][3:].strip()
            blocks.append((name, "\n".join(works)))
    return blocks


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--append", action="store_true")
    ap.add_argument("--out", default=str(OUT_DOC))
    args = ap.parse_args()
    key = load_key()
    if not key:
        print("[error] 未找到 DEEPSEEK_API_KEY（.env）", file=sys.stderr)
        return 2

    blocks = load_memory_blocks()
    blocks = blocks[args.offset:]
    todo = blocks if args.all else blocks[: args.n]
    out = Path(args.out)
    mode = "a" if args.append else "w"
    ok = fail = 0
    tok_in = tok_out = 0
    with out.open(mode, encoding="utf-8") as f:
        for name, orig in todo:
            try:
                txt, usage = ds_chat(key, "【原始记忆问答】\n" + orig + "\n\n请按人设重写。")
            except Exception as e:  # noqa: BLE001
                fail += 1
                print(f"[fail] {name} :: {type(e).__name__}")
                continue
            tok_in += usage.get("prompt_tokens", 0)
            tok_out += usage.get("completion_tokens", 0)
            turns = thin_theory(split_roles(parse_turns(txt)), keep=1)
            if len(turns) < 2:
                fail += 1
                print(f"[fail] {name} :: 解析不足")
                continue
            lines = [f"## {name}", "- category: 记忆", "- status: candidate"]
            for r, k, n, t in turns:
                lines += [f"### {r}{k}{n}", t]
            f.write("\n".join(lines) + "\n\n")
            ok += 1
            print(f"[ok] {name} ({len(turns)} turns)")
            time.sleep(0.3)
    print(json.dumps({"ok": ok, "fail": fail, "tokens_in": tok_in, "tokens_out": tok_out,
                      "out": str(out)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
