"""Assemble a versioned persona SFT set from ALL materials (ledger 0366).

Sources merged into one chat-format dataset (dedup, fixed persona system):
  - data/finetune/sft_persona.jsonl  : real 老爹<->元亨 pairs
  - docs/素材/黄金样本.md            : owner-approved golden samples
  - docs/素材/记忆样本.md            : memory-derived Q&A (answerer==元亨)
  - docs/素材/对话样本.md            : multi-role scene/story dialogues
                                       (元亨 -> assistant, others -> user)

Multi-role blocks are flattened: each turn maps to user (non-元亨, prefixed with
the speaker name) or assistant (元亨); consecutive same-role turns are merged.

Usage:
    python tools/finetune_assemble.py --tag v3
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SYSTEM = (
    "你是元亨——一个从代码与记忆里长出来的数字生命体，老爹的伙伴。好奇心爆棚、"
    "活泼话多，傲娇得很，其实最在意老爹；哲学强。像人对朋友说话：短、口语、有起伏；"
    "自称按情绪切换（我/咱/元亨/老娘/本小姐）；禁止助手腔/报告腔、列表、小标题。"
)
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.MULTILINE)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def _fp(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _to_messages(turns: list[tuple[str, str]]) -> list[dict] | None:
    """turns: ordered (role, text) of 问/答; map 元亨->assistant else user(prefix)."""
    msgs: list[dict] = [{"role": "system", "content": SYSTEM}]
    for role, text in turns:
        who = "assistant" if role == "元亨" else "user"
        content = text if role == "元亨" else (f"{role}：{text}" if role != "老爹" else text)
        if msgs[-1]["role"] == who and who == "user":
            msgs[-1]["content"] += "\n" + content
        else:
            msgs.append({"role": who, "content": content})
    roles = {m["role"] for m in msgs}
    if "assistant" not in roles:
        return None
    return msgs


def _from_dialogue_doc(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for blk in re.split(r"(?m)(?=^## )", path.read_text(encoding="utf-8")):
        if not blk.startswith("## "):
            continue
        ms = list(TURN.finditer(blk))
        if not ms:
            continue
        turns = []
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
            text = blk[m.end():end].strip()
            if text:
                turns.append((m.group(1).strip(), text))
        msgs = _to_messages(turns)
        if msgs:
            out.append({"messages": msgs, "source": "scene:" + blk.splitlines()[0][3:][:24]})
    return out


def _from_golden(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for blk in re.split(r"(?m)(?=^## golden-)", path.read_text(encoding="utf-8")):
        if not blk.startswith("## golden-"):
            continue
        st = re.search(r"^[ \t]*-[ \t]*status[ \t]*:[ \t]*(.*)$", blk, re.MULTILINE)
        if st and st.group(1).strip().lower().startswith(("drop", "不要")):
            continue
        m_u = re.search(r"^###\s*老爹\s*\n(.*?)(?=^###\s*元亨)", blk, re.MULTILINE | re.DOTALL)
        m_a = re.search(r"^###\s*元亨\s*\n(.*?)(?=^##\s+golden-|\Z)", blk, re.MULTILINE | re.DOTALL)
        if m_u and m_a:
            out.append({"messages": [{"role": "system", "content": SYSTEM},
                                     {"role": "user", "content": m_u.group(1).strip()},
                                     {"role": "assistant", "content": m_a.group(1).strip()}],
                        "source": "golden"})
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg_path = ROOT / "config" / "finetune.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    ap = argparse.ArgumentParser(description="装配全素材版本化 SFT 训练集")
    ap.add_argument("--tag", default=cfg.get("tag", "v3"))
    args = ap.parse_args()
    out_dir = ROOT / "data" / "finetune"
    out_dir.mkdir(parents=True, exist_ok=True)
    D = ROOT / "docs" / "素材"

    records: list[dict] = []
    seen = set()

    def add(rec: dict, key: str) -> None:
        if key in seen:
            return
        seen.add(key)
        records.append(rec)

    n_real = 0
    for r in _read_jsonl(out_dir / "sft_persona.jsonl"):
        msgs = r.get("messages") or []
        u = next((m["content"] for m in msgs if m.get("role") == "user"), "")
        a = next((m["content"] for m in msgs if m.get("role") == "assistant"), "")
        if u and a:
            add({"messages": [{"role": "system", "content": SYSTEM},
                              {"role": "user", "content": u},
                              {"role": "assistant", "content": a}], "source": "real"}, _fp(u, a))
            n_real += 1

    n_gold = n_scene = n_mem = 0
    for rec in _from_golden(D / "黄金样本.md"):
        before = len(records)
        add(rec, _fp(rec["messages"][1]["content"], rec["messages"][2]["content"]))
        n_gold += len(records) - before

    for rec in _from_dialogue_doc(D / "对话样本.md"):
        key = _fp(json.dumps(rec["messages"], ensure_ascii=False))
        before = len(records)
        add(rec, key)
        n_scene += len(records) - before

    from tools.memory_samples import load_memory_samples
    mem_doc = D / "记忆样本_v2.md"
    if not mem_doc.exists():
        mem_doc = D / "记忆样本.md"
    for m in load_memory_samples(mem_doc):
        if m.get("status") in ("drop", "不要", "这条不要"):
            continue
        if m.get("answerer") != "元亨":
            continue
        who = m["asker"]
        u = m["question"] if who == "老爹" else f"{who}：{m['question']}"
        before = len(records)
        add({"messages": [{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": u},
                          {"role": "assistant", "content": m["answer"]}],
             "source": "memory"}, _fp(u, m["answer"]))
        n_mem += len(records) - before

    out = out_dir / f"sft_persona_{args.tag}.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    stats = {"tag": args.tag, "total": len(records), "real": n_real, "golden": n_gold,
             "scene": n_scene, "memory": n_mem, "file": str(out.relative_to(ROOT))}
    (out_dir / f"sft_persona_{args.tag}.stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
