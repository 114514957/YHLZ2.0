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

# 利贞 persona（v4 新增）：把「利贞答」的轮次独立训成利贞=assistant，
# 推理时切换 system prompt 即可切换人格。
SYSTEM_LZ = (
    "你是利贞——元亨的伙伴、靠谱的技术担当。稳重、博学、直接，话不多但到位；"
    "句尾偶尔「，理论上来说」；私下其实没常识、有点大胆。禁止助手腔/列表/小标题。"
)


def _from_dialogue_doc_lizhen(path: Path) -> list[dict]:
    """抽对话块里「利贞答」的轮次 -> 利贞 persona 样本。"""
    if not path.exists():
        return []
    out = []
    for blk in re.split(r"(?m)(?=^## )", path.read_text(encoding="utf-8")):
        if not blk.startswith("## "):
            continue
        ms = list(TURN.finditer(blk))
        rounds: dict[str, dict] = {}
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
            rounds.setdefault(m.group(3), {})[m.group(2)] = (
                m.group(1).strip(), blk[m.end():end].strip())
        for num, d in rounds.items():
            q, a = d.get("问"), d.get("答")
            if not (q and a):
                continue
            if a[0] != "利贞" or q[0] not in ("元亨", "老爹"):
                continue
            u = q[1] if q[0] == "老爹" else f"元亨：{q[1]}"
            out.append({"messages": [{"role": "system", "content": SYSTEM_LZ},
                                     {"role": "user", "content": u},
                                     {"role": "assistant", "content": a[1]}],
                        "source": "lizhen:" + blk.splitlines()[0][3:][:24]})
    return out


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


def _to_messages(turns: list[tuple[str, str]], keep: tuple = ("老爹", "元亨")) -> list[dict] | None:
    """turns: ordered (role, text) of 问/答; map 元亨->assistant else user(prefix).

    v5: 默认**丢弃利贞轮次**——利贞已有独立 persona 集；保留会让模型学出
    「利贞：」面板模拟（前缀泄漏）。
    """
    msgs: list[dict] = [{"role": "system", "content": SYSTEM}]
    for role, text in turns:
        if role not in keep:
            continue
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
    ap.add_argument("--memory-ratio", type=float, default=0.20,
                    help="memory 占比上限（0-1，1=不限）")
    ap.add_argument("--lizhen-cap", type=int, default=300,
                    help="利贞 persona 样本上限（0=不限）")
    ap.add_argument("--extra", default=None,
                    help="额外 JSONL（如工具样本）；保留其 tools 字段")
    ap.add_argument("--extra-cap", type=int, default=0, help="extra 上限（0=不限）")
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

    n_lz = 0
    lz_recs = _from_dialogue_doc_lizhen(D / "对话样本.md")
    if args.lizhen_cap and len(lz_recs) > args.lizhen_cap:
        import random as _r
        _r.Random(cfg.get("seed", 20260913)).shuffle(lz_recs)
        lz_recs = lz_recs[: args.lizhen_cap]
    for rec in lz_recs:
        before = len(records)
        add(rec, _fp(json.dumps(rec["messages"], ensure_ascii=False)))
        n_lz += len(records) - before

    from tools.memory_samples import load_memory_samples
    import random
    mem_doc = D / "记忆样本_v2.md"
    if not mem_doc.exists():
        mem_doc = D / "记忆样本.md"
    mem_items: list[tuple[dict, str, bool]] = []
    for m in load_memory_samples(mem_doc):
        if m.get("status") in ("drop", "不要", "这条不要"):
            continue
        if m.get("answerer") != "元亨":
            continue
        who = m["asker"]
        u = m["question"] if who == "老爹" else f"{who}：{m['question']}"
        rec = {"messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": u},
                            {"role": "assistant", "content": m["answer"]}],
               "source": "memory"}
        mem_items.append((rec, _fp(u, m["answer"]), m.get("status") == "keep"))
    mem_total = len(mem_items)
    mem_cap = mem_total
    if args.memory_ratio < 1 and records:
        mem_cap = int(round(args.memory_ratio / (1 - args.memory_ratio) * len(records)))
        if mem_cap < mem_total:
            rnd = random.Random(cfg.get("seed", 20260913))
            keeps = [x for x in mem_items if x[2]]
            others = [x for x in mem_items if not x[2]]
            rnd.shuffle(keeps)
            rnd.shuffle(others)
            mem_items = (keeps + others)[:mem_cap]
    for rec, key, _ in mem_items:
        before = len(records)
        add(rec, key)
        n_mem += len(records) - before

    n_extra = 0
    if args.extra:
        ex_path = Path(args.extra)
        ex_rows = _read_jsonl(ex_path)
        if args.extra_cap and len(ex_rows) > args.extra_cap:
            random.Random(cfg.get("seed", 20260913)).shuffle(ex_rows)
            ex_rows = ex_rows[: args.extra_cap]
        for r in ex_rows:
            msgs = r.get("messages")
            if not msgs:
                continue
            rec = {"messages": msgs, "source": r.get("source", "extra")}
            if r.get("tools"):
                rec["tools"] = r["tools"]
            before = len(records)
            add(rec, _fp(json.dumps(msgs, ensure_ascii=False)))
            n_extra += len(records) - before

    out = out_dir / f"sft_persona_{args.tag}.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    stats = {"tag": args.tag, "total": len(records), "real": n_real, "golden": n_gold,
             "scene": n_scene, "lizhen": n_lz, "memory": n_mem, "memory_total": mem_total,
             "extra": n_extra,
             "memory_ratio": round(n_mem / max(1, len(records)), 3),
             "file": str(out.relative_to(ROOT))}
    (out_dir / f"sft_persona_{args.tag}.stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
