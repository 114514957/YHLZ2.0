"""Materials audit — freeze README_规范.md §5 metrics into one command (ledger 0506).

Measures the 14 acceptance metrics + 5 hard floors over docs/素材/*.md and the
latest tool-use jsonl. Usage:
    python tools/materials_audit.py
    python tools/materials_audit.py --tools data/finetune/tool_use_v8.jsonl --out docs/报告/素材体检.md
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

D = ROOT / "docs" / "素材"
TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)\s*(\d+)\s*$", re.MULTILINE)
GOLD_TURN = re.compile(r"^###\s*(老爹|元亨|利贞|大肥鱼)\s*$", re.MULTILINE)
META = re.compile(r"^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", re.MULTILINE)
ASSISTANT_TONE = ("为您", "以下是", "已为您", "根据查询结果", "很高兴为您",
                  "作为AI", "作为人工智能", "有什么可以帮")
PAREN_ACT = re.compile(r"（[^）]{1,4}）")
CHARS = re.compile(r"[\s\W_]+")


def _blocks(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [b for b in re.split(r"(?m)(?=^## )", path.read_text(encoding="utf-8")) if b.startswith("## ")]


def _meta(blk: str) -> dict:
    return {m.group(1).lower(): m.group(2).strip() for m in META.finditer(blk)}


def _turns(blk: str) -> list[tuple[str, str, str]]:
    ms = list(TURN.finditer(blk))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
        text = blk[m.end():end].strip()
        if text:
            out.append((m.group(1).strip(), m.group(2), text))
    if out:
        return out
    ms = list(GOLD_TURN.finditer(blk))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
        text = blk[m.end():end].strip()
        if text:
            out.append((m.group(1).strip(), "答" if m.group(1) == "元亨" else "问", text))
    return out


def survey(path: Path, answerer: str = "元亨") -> dict:
    blks = _blocks(path)
    answers, answers_yh, asks, pairs = [], [], [], []
    cats, statuses, subtypes = Counter(), Counter(), Counter()
    bracket = tone = 0
    for b in blks:
        meta = _meta(b)
        cat = meta.get("category", "")
        if not cat:
            head = b.splitlines()[0]
            if "｜" in head:
                cat = head.split("｜")[-1].strip()
        cats[cat] += 1
        statuses[meta.get("status", "?")] += 1
        subtypes[meta.get("subtype", "")] += 1
        for role, kind, text in _turns(b):
            bracket += len(PAREN_ACT.findall(text))
            if role == answerer and kind == "答":
                tone += sum(1 for w in ASSISTANT_TONE if w in text)
            if kind == "答":
                answers.append(text)
                if role == answerer:
                    answers_yh.append(text)
            else:
                asks.append(text)
        qs = [t for r, k, t in _turns(b) if k == "问"]
        ans = [t for r, k, t in _turns(b) if k == "答"]
        for i in range(min(len(qs), len(ans))):
            pairs.append((CHARS.sub("", qs[i]), CHARS.sub("", ans[i])))
    return {"path": path, "blocks": len(blks), "answers": answers,
            "answers_yh": answers_yh, "asks": asks,
            "pairs": pairs, "cats": cats, "statuses": statuses, "subtypes": subtypes,
            "bracket": bracket, "tone": tone}


def self_refs(answers: list[str]) -> Counter:
    c = Counter()
    for a in answers:
        for tag in ("本小姐", "老娘", "咱", "元亨"):
            if tag in a:
                c[tag] += 1
                break
        else:
            c["我"] += 1
    return c


def emotions(answers: list[str]) -> Counter:
    from backend.emotion_classifier import classify_emotion
    c = Counter()
    for a in answers:
        c[classify_emotion(a)["emotion"]] += 1
    return c


def tool_audit(path: Path | None) -> dict:
    from backend.target_scheduler_tools import openai_tools_view
    from tools.gen_tooluse import classify
    real = {t["function"]["name"] for t in openai_tools_view()}
    if not path or not path.exists():
        return {"file": None, "real": len(real), "used": set(), "fake": set(),
                "rows": 0, "kinds": Counter()}
    used = set()
    rows = 0
    kinds = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows += 1
        kinds[classify(rec)] += 1
        for m in rec.get("messages", []):
            for tc in m.get("tool_calls") or []:
                used.add(tc.get("function", {}).get("name"))
            if m.get("role") == "tool" and m.get("name"):
                used.add(m["name"])
        for t in rec.get("tools") or []:
            used.add(t.get("function", {}).get("name"))
    return {"file": path, "real": len(real), "used": used - {None},
            "fake": {u for u in used if u not in real}, "rows": rows, "kinds": kinds}


def pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.1f}%" if d else "n/a"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="素材体检（规范 §5）")
    ap.add_argument("--tools", default=str(ROOT / "data" / "finetune" / "tool_use_v8.jsonl"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    docs = {
        "对话样本.md": survey(D / "对话样本.md"),
        "记忆样本_v2.md": survey(D / "记忆样本_v2.md"),
        "黄金样本.md": survey(D / "黄金样本.md"),
        "优质样本.md": survey(D / "优质样本.md"),
        "诚实边界样本.md": survey(D / "诚实边界样本.md"),
        "安全拒绝样本.md": survey(D / "安全拒绝样本.md"),
        "承认不确定样本.md": survey(D / "承认不确定样本.md"),
    }
    scene = docs["对话样本.md"]
    an_all = [a for s in docs.values() for a in s["answers"]]
    an = scene["answers"]
    med = statistics.median(len(a) for a in an) if an else 0
    short30 = sum(1 for a in an if len(a) <= 30)
    long100 = sum(1 for a in an_all if len(a) > 100)
    long_share_scene = sum(1 for a in an if len(a) > 100)
    refs = self_refs(scene.get("answers_yh") or scene["answers"])
    scene_emo = Counter()
    for b in _blocks(scene["path"]):
        m = re.search(r"(?m)^- emotion: (\S+)", b)
        if m:
            scene_emo[m.group(1)] += 1
    openings = Counter(a[:3].strip() for a in an if a)
    dup = 0
    for s in docs.values():
        dup += len(s["pairs"]) - len(set(s["pairs"]))
    bracket = sum(s["bracket"] for s in docs.values())
    tone = sum(s["tone"] for s in docs.values())
    cats = Counter()
    for k in ("对话样本.md",):
        cats.update(docs[k]["cats"])
    n_blocks = sum(s["blocks"] for s in docs.values())
    keep = sum(s["statuses"].get("keep", 0) for s in docs.values())
    ta = tool_audit(Path(args.tools))

    # new-dimension / hard floors
    subtypes = Counter()
    for s in docs.values():
        subtypes.update({k: v for k, v in s["subtypes"].items() if k})
    real_doc = D / "真实对话样本.md"
    real_pairs = 0
    if real_doc.exists():
        real_pairs = len(survey(real_doc)["pairs"])
    kinds = ta.get("kinds") or Counter()
    floors = {
        "A 真实对话≥300": real_pairs,
        "B3 诚实边界≥180": subtypes.get("诚实与边界", 0),
        "B4 安全拒绝≥90": subtypes.get("安全拒绝", 0),
        "D2 承认不确定≥150": subtypes.get("承认不确定", 0),
        "E3 工具反例≥150": kinds.get("nocall", 0) + kinds.get("dev", 0),
        "E4 失败跟进≥90": kinds.get("failure", 0),
    }

    L = []
    L.append("# 素材体检（规范 v1 §5 口径）")
    L.append("- 口径：1/2/5/8=对话样本；4=对话样本·仅元亨答轮；3/6/7/9=全库")
    L.append(f"- 范围：{', '.join(docs)}；答轮 {len(an)}；块 {n_blocks}")
    L.append("")
    L.append("| # | 指标 | 阈值 | 实测 |")
    L.append("|---|---|---|---|")
    L.append(f"| 1 | 轮长中位 | ≥45 | **{med}** |")
    L.append(f"| 2 | ≤30字占比 | ≤45% | **{pct(short30, len(an))}** |")
    L.append(f"| 3 | >100字答轮(全库) | ≥15% | **{pct(long100, len(an_all))}** |")
    tot_ref = sum(refs.values())
    L.append("| 4 | 自称分布(元亨) | 我45/咱20/本20/老10/元5 | " +
             " / ".join(f"{k} {pct(v, tot_ref)}" for k, v in refs.most_common()) + " |")
    tot_e = sum(scene_emo.values())
    L.append("| 5 | 情绪分布(声明) | neutral≤40等 | " +
             " / ".join(f"{k} {pct(v, tot_e)}" for k, v in scene_emo.most_common()) + " |")
    L.append(f"| 6 | 括号动作 | 0 | **{bracket}** |")
    L.append(f"| 7 | 助手腔词 | 0 | **{tone}** |")
    top_open = openings.most_common(1)[0] if openings else ("", 0)
    L.append(f"| 8 | 单一开头词 | ≤2% | 「{top_open[0]}」{pct(top_open[1], len(an))} |")
    L.append(f"| 9 | 重复问答对 | 0 | **{dup}** |")
    L.append(f"| 10 | keep占比 | ≥60% | {pct(keep, n_blocks)} |")
    L.append(f"| 11 | 工具名∈真实表 | 100% | {pct(len(ta['used']) - len(ta['fake']), len(ta['used']))}"
             f"（假名 {sorted(x for x in ta['fake'] if x)}）|")
    tech = cats.get("技术", 0)
    story = cats.get("故事", 0)
    L.append(f"| 12 | 技术类 | ≥20% | {pct(tech, sum(cats.values()))} |")
    L.append(f"| 13 | 故事类 | ≤30% | {pct(story, sum(cats.values()))} |")
    meta_full = sum(1 for s in docs.values() for b in _blocks(s["path"])
                    if all(_meta(b).get(k) for k in ("emotion", "length_tier", "contract")))
    L.append(f"| 14 | 元数据完整(emotion/length_tier/contract) | 100% | "
             f"{pct(meta_full, n_blocks)} |")
    L.append("")
    L.append("**硬下限**：" + "；".join(f"{k} = **{v}**" for k, v in floors.items()))
    L.append("")
    L.append("文件清单：")
    for name, s in docs.items():
        L.append(f"- {name}: {s['blocks']} 块 / {len(s['answers'])} 答轮 / "
                 f"keep={s['statuses'].get('keep', 0)}")
    if ta["file"]:
        L.append(f"- 工具数据 {ta['file'].name}: {ta['rows']} 条 / 用到工具 {len(ta['used'])} 个")
    txt = "\n".join(L)
    print(txt)
    if args.out:
        p = Path(args.out)
        p.write_text(txt + "\n", encoding="utf-8")
        print(f"\n[ok] -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
