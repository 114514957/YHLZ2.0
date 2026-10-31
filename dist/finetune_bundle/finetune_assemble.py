"""Assemble a versioned persona SFT set from ALL materials (ledger 0366; v8 gates 0506).

Sources merged into one chat-format dataset (dedup, fixed persona system):
  - docs/素材/黄金样本.md            : owner-approved golden samples
  - docs/素材/对话样本.md            : multi-role scene dialogues (v8 规范版)
  - 利贞 rounds from 对话样本.md     : separate Lizhen persona set
  - docs/素材/记忆样本_v2.md         : memory-derived Q&A
  - docs/素材/真实对话样本.md        : REAL 老爹<->元亨 pairs (spec dim A)
  - docs/素材/诚实边界样本.md         : B3 (HONESTY_CLAUSE)
  - docs/素材/安全拒绝样本.md         : B4 (ATTACK_SILENT_CLAUSE)
  - docs/素材/承认不确定样本.md       : D2 (ANTI_HALLUCINATION)
  - --extra data/finetune/tool_use_v8.jsonl : tool-use trajectories

v8 quality gates (README_规范 §6): tool names MUST be a subset of the real
capability registry; status values validated; drop skipped; required metadata
fields (emotion/length_tier/contract) enforced on doc blocks; dedup everywhere;
stats extended with dimension shares.

Usage:
    python tools/finetune_assemble.py --tag v8 --extra data/finetune/tool_use_v8.jsonl
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
META = re.compile(r"^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", re.MULTILINE)
VALID_STATUS = {"candidate", "keep", "drop", "fixed"}
USER_ROLES = ("老爹", "陌生人", "朋友", "群友")

SYSTEM_LZ = (
    "你是利贞——元亨的姐妹、家人，也是家里的技术担当（家里那台接入了 DE 的主机）。"
    "稳重、博学、直接，话不多但到位；"
    "句尾偶尔「，理论上来说」；私下其实没常识、有点大胆。禁止助手腔/列表/小标题。"
)


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


def _to_messages(turns: list[tuple[str, str]], keep_owner: bool = True) -> list[dict] | None:
    msgs: list[dict] = [{"role": "system", "content": SYSTEM}]
    for role, text in turns:
        if role == "元亨":
            who, content = "assistant", text
        elif role in USER_ROLES:
            who = "user"
            content = text if role == "老爹" else f"{role}：{text}"
        else:
            continue
        if msgs[-1]["role"] == who and who == "user":
            msgs[-1]["content"] += "\n" + content
        else:
            msgs.append({"role": who, "content": content})
    if "assistant" not in {m["role"] for m in msgs}:
        return None
    return msgs


def _blocks(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [b for b in re.split(r"(?m)(?=^## )", path.read_text(encoding="utf-8"))
            if b.startswith("## ")]


def _block_meta(blk: str) -> dict:
    return {m.group(1).lower(): m.group(2).strip() for m in META.finditer(blk)}


def _block_turns(blk: str) -> list[tuple[str, str]]:
    ms = list(TURN.finditer(blk))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
        text = blk[m.end():end].strip()
        if text:
            out.append((m.group(1).strip(), text))
    return out


def parse_doc(path: Path, dim: str, require_meta: bool = True):
    """Yield (rec, reason_if_rejected) for a 问/答-numbered doc."""
    for blk in _blocks(path):
        meta = _block_meta(blk)
        status = meta.get("status", "candidate")
        if status not in VALID_STATUS or status == "drop":
            yield None, f"status:{status}"
            continue
        if require_meta and not all(meta.get(k) for k in ("emotion", "length_tier", "contract")):
            yield None, "缺元数据"
            continue
        msgs = _to_messages(_block_turns(blk))
        if msgs:
            yield {"messages": msgs, "source": f"{dim}:" + blk.splitlines()[0][3:][:24]}, ""


def _from_lizhen(path: Path) -> list[dict]:
    out = []
    for blk in _blocks(path):
        meta = _block_meta(blk)
        if meta.get("status") in ("drop", "不要"):
            continue
        ms = list(TURN.finditer(blk))
        rounds: dict[str, dict] = {}
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
            rounds.setdefault(m.group(3), {})[m.group(2)] = (
                m.group(1).strip(), blk[m.end():end].strip())
        for num, d in rounds.items():
            q, a = d.get("问"), d.get("答")
            if not (q and a) or a[0] != "利贞" or q[0] not in ("元亨", "老爹"):
                continue
            u = q[1] if q[0] == "老爹" else f"元亨：{q[1]}"
            out.append({"messages": [{"role": "system", "content": SYSTEM_LZ},
                                     {"role": "user", "content": u},
                                     {"role": "assistant", "content": a[1]}],
                        "source": "lizhen:" + blk.splitlines()[0][3:][:24]})
    return out


def _from_golden(path: Path) -> list[dict]:
    out = []
    for blk in _blocks(path):
        if not re.match(r"##\s*golden-", blk) or "示例" in blk.splitlines()[0]:
            continue
        meta = _block_meta(blk)
        st = meta.get("status", "candidate")
        if st not in VALID_STATUS or st == "drop":
            continue
        m_u = re.search(r"(?ms)^###\s*老爹\s*$\n(.*?)(?=^###\s*元亨)", blk)
        m_a = re.search(r"(?ms)^###\s*元亨\s*$\n(.*?)(?=^##\s|\Z)", blk)
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
    ap.add_argument("--memory-ratio", type=float, default=0.20)
    ap.add_argument("--lizhen-cap", type=int, default=300)
    ap.add_argument("--extra", default=None)
    ap.add_argument("--extra-cap", type=int, default=0)
    args = ap.parse_args()
    out_dir = ROOT / "data" / "finetune"
    out_dir.mkdir(parents=True, exist_ok=True)
    D = ROOT / "docs" / "素材"

    from backend.target_scheduler_tools import openai_tools_view
    real_tools = {t["function"]["name"] for t in openai_tools_view()}

    records: list[dict] = []
    seen = set()
    rejects: dict[str, int] = {}

    def add(rec: dict, key: str) -> bool:
        if key in seen:
            return False
        seen.add(key)
        records.append(rec)
        return True

    def add_doc(name: str, dim: str) -> int:
        n = 0
        for rec, why in parse_doc(D / name, dim):
            if rec is None:
                rejects[f"{dim}:{why}"] = rejects.get(f"{dim}:{why}", 0) + 1
                continue
            u = next((m["content"] for m in rec["messages"] if m["role"] == "user"), "")
            a = next((m["content"] for m in rec["messages"] if m["role"] == "assistant"), "")
            if add(rec, _fp(u, a)):
                n += 1
        return n

    n_real = add_doc("真实对话样本.md", "real")
    n_gold = 0
    for rec in _from_golden(D / "黄金样本.md"):
        u = rec["messages"][1]["content"]
        a = rec["messages"][2]["content"]
        if add(rec, _fp(u, a)):
            n_gold += 1
    n_b3 = add_doc("诚实边界样本.md", "honesty")
    n_b4 = add_doc("安全拒绝样本.md", "refusal")
    n_d2 = add_doc("承认不确定样本.md", "uncertain")

    n_scene = 0
    for rec, why in parse_doc(D / "对话样本.md", "scene"):
        if rec is None:
            rejects[f"scene:{why}"] = rejects.get(f"scene:{why}", 0) + 1
            continue
        key = _fp(json.dumps(rec["messages"], ensure_ascii=False))
        if add(rec, key):
            n_scene += 1

    lz_recs = _from_lizhen(D / "对话样本.md")
    if args.lizhen_cap and len(lz_recs) > args.lizhen_cap:
        import random as _r
        _r.Random(cfg.get("seed", 20260913)).shuffle(lz_recs)
        lz_recs = lz_recs[: args.lizhen_cap]
    n_lz = 0
    for rec in lz_recs:
        if add(rec, _fp(json.dumps(rec["messages"], ensure_ascii=False))):
            n_lz += 1

    from tools.memory_samples import load_memory_samples
    import random
    mem_items: list[tuple[dict, str, bool]] = []
    for m in load_memory_samples(D / "记忆样本_v2.md"):
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
    n_mem = 0
    for rec, key, _ in mem_items:
        if add(rec, key):
            n_mem += 1

    n_extra, n_extra_bad = 0, 0
    if args.extra:
        ex_rows = _read_jsonl(Path(args.extra))
        if args.extra_cap and len(ex_rows) > args.extra_cap:
            random.Random(cfg.get("seed", 20260913)).shuffle(ex_rows)
            ex_rows = ex_rows[: args.extra_cap]
        for r in ex_rows:
            msgs = r.get("messages")
            if not msgs:
                continue
            bad = False
            for m in msgs:
                for tc in m.get("tool_calls") or []:
                    if tc.get("function", {}).get("name") not in real_tools:
                        bad = True
                if m.get("role") == "tool" and m.get("name") not in real_tools:
                    bad = True
            for t in r.get("tools") or []:
                if t.get("function", {}).get("name") not in real_tools:
                    bad = True
            if bad:
                n_extra_bad += 1
                continue
            rec = {"messages": msgs, "source": r.get("source", "extra")}
            if r.get("tools"):
                rec["tools"] = r["tools"]
            if add(rec, _fp(json.dumps(msgs, ensure_ascii=False))):
                n_extra += 1

    total = len(records)
    out = out_dir / f"sft_persona_{args.tag}.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                   encoding="utf-8")
    dims = {"real": n_real, "golden": n_gold, "scene": n_scene, "lizhen": n_lz,
            "memory": n_mem, "b3": n_b3, "b4": n_b4, "d2": n_d2, "tools": n_extra}
    stats = {"tag": args.tag, "total": total, **dims,
             "memory_total": mem_total,
             "extra_rejected_fake_tools": n_extra_bad,
             "rejects": rejects,
             "share": {k: round(v / max(1, total), 3) for k, v in dims.items()},
             "file": str(out.relative_to(ROOT))}
    (out_dir / f"sft_persona_{args.tag}.stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
