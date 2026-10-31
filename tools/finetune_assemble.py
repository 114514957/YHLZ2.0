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
  - docs/素材/元亨说话_老爹故事.md    : V9 故事素材 (Phase 1, 老爹叙述/代写; status=keep 才写入)
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

# 2026-10-30 统一 prompt：训练/评测/部署共用一份（原简化版 86 tokens，
# 与部署用的 3,856 字真实 prompt 不一致，实测真实版让工具题 2/6 -> 0/6）。
from unified_prompt import UNIFIED_SYSTEM as SYSTEM  # noqa: E402
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.MULTILINE)
META = re.compile(r"^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", re.MULTILINE)
VALID_STATUS = {"candidate", "keep", "drop", "fixed"}
USER_ROLES = ("老爹", "陌生人", "朋友", "群友")
# R1(0652): 旧版只保留 USER_ROLES，利贞等在场角色的发言被丢弃，导致
# 「元亨答1 → (利贞问2被丢) → 元亨答2」变成相邻 assistant（实测 1000/3440）。
# 现改为：未列名角色（含利贞）一律保留为 user 上下文；同角色相邻合并。
_REPAIR_REPEATS = False
_REPAIR_COUNT = 0

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


def _strip_label(text: str) -> str:
    """剥掉正文开头的角色标签（2026-10-27）。

    两个实测出来的 bug：
      ① `role != 元亨` 时拼成 `f"{role}：{text}"`，若 text 本身以「利贞：」开头
         就变成「利贞：利贞：xxx」（philo 里有多条）；
      ② 元亨的台词本身写成「元亨：利贞，你问得好——…」，原样进训练后
         模型学会了输出「元亨：」前缀（56 题第 6 条实测复现：答「元亨：因为不睡会死。」）。

    只剥开头、且可连剥多次（防「利贞：利贞：」），不动正文中间。
    """
    t = str(text or "").lstrip()
    pat = re.compile(r"^(元亨|利贞|老爹|助手|AI)\s*[:：]\s*")
    for _ in range(3):
        m = pat.match(t)
        if not m:
            break
        t = t[m.end():].lstrip()
    return t


def _repair_repeat(text: str, min_len: int = 20) -> tuple[str, bool]:
    """R1: 去掉同一消息内相邻重复段（v8 第 20 行有 ~164 字复读）。"""
    global _REPAIR_COUNT
    pat = re.compile(r"(.{%d,}?)\1" % min_len, re.S)
    changed = False
    for _ in range(4):
        m = pat.search(text)
        if not m:
            break
        text = text[: m.start()] + m.group(1) + text[m.end():]
        changed = True
    if changed:
        _REPAIR_COUNT += 1
    return text, changed


def _to_messages(turns: list[tuple[str, str, str]], keep_owner: bool = True,
                 fiction: bool = False) -> list[dict] | None:
    msgs: list[dict] = [{"role": "system", "content": SYSTEM}]
    if fiction:
        # R1b(0657)：日常/闲聊场景是角色创作，显式注入虚构框架，
        # 防止教会"编造真实经历"（Codex 节点 A：把创作放进创作语境）。
        msgs.append({"role": "user", "content": "（虚构小剧场）"})
    for turn in turns:
        role, text = turn[0], turn[-1]
        if _REPAIR_REPEATS:
            text, _ = _repair_repeat(text)
        # v9t2(2026-10-27)：剥掉正文开头的角色标签，避免
        # 「利贞：利贞：」（user 侧重复拼前缀）和 assistant 台词带「元亨：」。
        text = _strip_label(text)
        if not text:
            continue
        if role == "元亨":
            who, content = "assistant", text
        elif role == "老爹":
            who, content = "user", text
        else:
            # R1: 利贞/陌生人/朋友/群友/未列名角色保留为 user 上下文
            who, content = "user", f"{role}：{text}"
        if msgs[-1]["role"] == who:
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


def _block_turns(blk: str) -> list[tuple[str, str, str]]:
    ms = list(TURN.finditer(blk))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
        text = blk[m.end():end].strip()
        if text:
            out.append((m.group(1).strip(), m.group(2), text))
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
        fiction = str(meta.get("fiction", "")).strip().lower() in ("1", "true", "yes", "是")
        msgs = _to_messages(_block_turns(blk), fiction=fiction)
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
    ap.add_argument("--extra", action="append", default=None,
                    help="可多次指定，例如 --extra a.jsonl --extra b.jsonl")
    ap.add_argument("--extra-cap", type=int, default=0)
    ap.add_argument("--memory-file", default="记忆样本_v2.md")
    ap.add_argument("--refusal-file", default="安全拒绝样本.md")
    ap.add_argument("--repair-repeats", action="store_true",
                    help="R1: 修复消息内相邻重复段（洁净候选用）")
    args = ap.parse_args()
    global _REPAIR_REPEATS
    _REPAIR_REPEATS = bool(args.repair_repeats)
    out_dir = ROOT / "data" / "finetune"
    out_dir.mkdir(parents=True, exist_ok=True)
    D = ROOT / "docs" / "素材"

    from backend.target_scheduler_tools import openai_tools_view
    real_tools = {t["function"]["name"] for t in openai_tools_view()}
    # 2026-10-20（ledger 0900）：工具范围扩到未来 agent harness——把 harness 注册表并入白名单
    _hs = ROOT / "data" / "tool_registry" / "harness_tools_latest.json"
    _ds = ROOT / "data" / "tool_registry" / "dsh_tools_latest.json"
    if _ds.exists():
        try:
            real_tools |= {t["name"] for t in json.loads(_ds.read_text(encoding="utf-8")).get("tools") or []}
        except Exception:
            pass
    if _hs.exists():
        try:
            real_tools |= {t["name"] for t in json.loads(_hs.read_text(encoding="utf-8")).get("tools") or []}
        except Exception:
            pass

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
    # 2026-10-22 全素材集检查发现：**优质样本.md 是孤儿**——8 块利贞手写的风格标杆
    # （日常3/哲学2/技术1/闲聊2），格式合规 `## 优质-N｜…`，但从来没有任何读取路径用到。
    # 内容正是"完美风格"最缺的标杆，接进 golden 维度。
    n_qual = add_doc("优质样本.md", "golden")
    n_gold += n_qual
    n_b3 = add_doc("诚实边界样本.md", "honesty")
    n_b4 = add_doc(args.refusal_file, "refusal")
    n_d2 = add_doc("承认不确定样本.md", "uncertain")
    n_story = add_doc("元亨说话_老爹故事.md", "story")
    # 2026-10-20 新增：哲学观点素材（来源代号 PHILO-A《苏菲的世界》；落法 B/C，见来源代号登记表）
    n_philo = add_doc("哲学观点样本.md", "philo")
    # 2026-10-20 新增：比喻理解素材（原创实体比喻讲抽象概念，无版权来源）
    n_meta = add_doc("比喻理解样本.md", "metaphor")
    # 2026-10-20 新增：情绪承接素材（机制学自 TreeHoleEcho，情景与台词全原创）
    n_emo = add_doc("情绪承接样本.md", "emotional")
    # 2026-10-20 新增：LCCC 开源真实对话原话直采（MIT）
    n_open = add_doc("开源对话样本.md", "opendialogue")
    # 2026-10-21 老爹：「元亨要的是个性，不是叛逆」→ 个性样本（她本来就有坐标系）
    n_pers = add_doc("个性样本.md", "personality")
    # 2026-10-21 老爹：「这些保留」→ 教样本（治毛病：被纠正就改的那种）
    n_teach = add_doc("教样本.md", "teaching")

    n_scene = 0
    for rec, why in parse_doc(D / "对话样本.md", "scene"):
        if rec is None:
            rejects[f"scene:{why}"] = rejects.get(f"scene:{why}", 0) + 1
            continue
        key = _fp(json.dumps(rec["messages"], ensure_ascii=False))
        if add(rec, key):
            n_scene += 1

    # 2026-10-20 修（老爹「重做」／素材体检 P0-1）：
    # lizhen 记录带的是 **SYSTEM_LZ（利贞人格）**，原来直接 add() 进主 records，
    # 导致 118 条利贞样本混进元亨训练集 → 模型会学到"某些情况该自称利贞"，身份污染。
    # 现改为**分流到独立文件**，不进元亨数据集。
    lz_recs = _from_lizhen(D / "对话样本.md")
    if args.lizhen_cap and len(lz_recs) > args.lizhen_cap:
        import random as _r
        _r.Random(cfg.get("seed", 20260913)).shuffle(lz_recs)
        lz_recs = lz_recs[: args.lizhen_cap]
    n_lz = len(lz_recs)
    if lz_recs:
        lz_out = out_dir / f"sft_lizhen_{args.tag}.jsonl"
        lz_out.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in lz_recs) + "\n",
            encoding="utf-8")
        print(f"[assemble] 利贞人格集已分流：{n_lz} 条 -> {lz_out.name}"
              f"（不进元亨训练集）")

    from tools.memory_samples import load_memory_samples
    import random
    mem_items: list[tuple[dict, str, bool]] = []
    for m in load_memory_samples(D / args.memory_file):
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
    for _ex_path in (args.extra or []):
        ex_rows = _read_jsonl(Path(_ex_path))
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
            # 2026-10-20（老爹「工具要经过测试可用，别写错调用就坏了」）：
            # **tool_calls[].function.arguments 必须是对象，不能是 JSON 字符串。**
            # Gemma 4 的 chat template 会直接报
            #   "tool_calls[].function.arguments must be a JSON object (mapping), not a string"
            # 训练脚本走 apply_chat_template，实测 train 35 / val 5 / test 1 条会因此崩。
            for _m in rec["messages"]:
                for _tc in _m.get("tool_calls") or []:
                    _fn = _tc.setdefault("function", {})
                    _a = _fn.get("arguments")
                    if isinstance(_a, str):
                        try:
                            _fn["arguments"] = json.loads(_a) if _a.strip() else {}
                        except Exception:
                            _fn["arguments"] = {}
                    elif _a is None:
                        _fn["arguments"] = {}
            if r.get("tools"):
                rec["tools"] = r["tools"]
            # 2026-10-20（ledger 0889）：simulation/generated 标记必须透传，
            # 否则门无法区分「真实轨迹」与「按 schema 生成的轨迹」。
            for k in ("simulation", "generated", "tool", "scenario"):
                if k in r:
                    rec[k] = r[k]
            if add(rec, _fp(json.dumps(msgs, ensure_ascii=False))):
                n_extra += 1

    total = len(records)
    out = out_dir / f"sft_persona_{args.tag}.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                   encoding="utf-8")
    dims = {"real": n_real, "golden": n_gold, "scene": n_scene, "lizhen": n_lz,
            "memory": n_mem, "b3": n_b3, "b4": n_b4, "d2": n_d2,
            "story": n_story, "philo": n_philo, "metaphor": n_meta,
            "emotional": n_emo, "opendialogue": n_open,
            "personality": n_pers, "teaching": n_teach, "tools": n_extra}
    adjacent_assistant = leading_assistant = lizhen_user_turns = 0
    for r in records:
        msgs = r["messages"]
        first_non_sys = next((m for m in msgs if m["role"] != "system"), None)
        if first_non_sys is not None and first_non_sys["role"] == "assistant":
            leading_assistant += 1
        for a, b in zip(msgs, msgs[1:]):
            if a["role"] == "assistant" and b["role"] == "assistant":
                adjacent_assistant += 1
                break
        for m in msgs:
            if m["role"] == "user" and str(m["content"]).startswith("利贞："):
                lizhen_user_turns += 1
    stats = {"tag": args.tag, "total": total, **dims,
             "memory_total": mem_total,
             "extra_rejected_fake_tools": n_extra_bad,
             "rejects": rejects,
             "quality_gates": {
                 "adjacent_assistant": adjacent_assistant,
                 "leading_assistant": leading_assistant,
                 "lizhen_user_turns": lizhen_user_turns,
                 "repeat_repairs": _REPAIR_COUNT,
             },
             "share": {k: round(v / max(1, total), 3) for k, v in dims.items()},
             "file": str(out.relative_to(ROOT))}
    (out_dir / f"sft_persona_{args.tag}.stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
