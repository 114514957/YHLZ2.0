"""CoT 数据独立审计（ledger 0894）。

目的：**不复用生成器代码**，从题面文本重新解析并独立计算，再与样本里的
`answer_check` 和答案正文核对，抓出残留的逻辑错误。

审计三类：
  A. 标签一致性：answer_check vs 独立重算
  B. 正文一致性：答案正文里"那答案是 X / 结果是 X" vs answer_check
  C. 算式自洽：正文里出现的 `a×b=c` / `a+b=c` / `a-b=c` 是否真的成立

用法：python tools/v9_cot_audit.py [--files cot_samples.jsonl,cot_deep.jsonl]
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "finetune"
EVAL = ROOT / "data" / "eval" / "cot_eval_set.jsonl"
REPORT = ROOT / "cache" / "v9_materials_preparation" / "cot_audit.json"


def q_of(rec: dict) -> str:
    for m in rec.get("messages") or []:
        if m.get("role") == "user":
            return str(m.get("content") or "")
    return ""


def a_of(rec: dict) -> str:
    for m in rec.get("messages") or []:
        if m.get("role") == "assistant":
            return str(m.get("content") or "")
    return ""


def claim(a: str) -> str | None:
    m = re.search(r"(?:那)?答案(?:是|就是)\s*([^\s。，,]+)", a)
    if m:
        val = m.group(1).strip(" 。")
        if val in ("应当得", "应该得"):
            m2 = re.search(r"应当得体?\s*(\d+)", a)
            return m2.group(1) if m2 else None
        return val
    m = re.search(r"(?:应当得|应该得|结果[:：]?)\s*([^\s。，,]+)", a)
    return m.group(1).strip(" 。") if m else None


def audit_arith(q: str, a: str) -> tuple[str, str] | None:
    m = re.search(r"一盒笔 (\d+) 支，我买了 (\d+) 盒，用掉 (\d+) 支", q)
    if m:
        a1, b1, used = map(int, m.groups())
        return str(a1 * b1 - used), ""
    m = re.search(r"每天存 (\d+) 块，存了 (\d+) 天，之前有 (\d+) 块", q)
    if m:
        per, days, had = map(int, m.groups())
        return str(had + per * days), ""
    m = re.search(r"一批 (\d+) 件，先留 (\d+) 件备用，剩下的平均分成 (\d+) 份", q)
    if m:
        n, keep, parts = map(int, m.groups())
        if (n - keep) % parts:
            return "", "not-divisible"
        return str((n - keep) // parts), ""
    return None


def audit_logic(q: str, a: str) -> tuple[str, str] | None:
    m = re.search(r"([^\s，。；：]{1,4})比([^\s，。；：]{1,4})高，([^\s，。；：]{1,4})比([^\s，。；：]{1,4})高", q)
    if not m:
        return None
    x, y, y2, z = m.groups()
    if y != y2:
        return "", "relation-broken"
    return x, ""


def audit_multihop(q: str, a: str) -> tuple[str, str] | None:
    m = re.search(r"第一次说了 (\d+) [条份个]，后来又补了 (\d+) [条份个]", q)
    if m:
        return str(sum(map(int, m.groups()))), ""
    return None


def audit_finderr(q: str, a: str) -> tuple[str, str] | None:
    m = re.search(r"(\d+)×(\d+) 得 (\d+)", q)
    if m:
        x, y, wrong = map(int, m.groups())
        if x * y == wrong:
            return "", "wrong-value-equals-right"
        return str(x * y), ""
    return None


def audit_shop(q: str, a: str) -> tuple[str, str] | None:
    m = re.search(r"苹果 (\d+) 块一斤买 (\d+) 斤，牛奶 (\d+) 块一盒买 (\d+) 盒，"
                  r"结账满 100 减 (\d+)，我给了 (\d+)", q)
    if not m:
        return None
    p1, n1, p2, n2, cut, paid = map(int, m.groups())
    total = p1 * n1 + p2 * n2
    return str(paid - (total - cut)), ""


def audit_schedule(q: str, a: str) -> tuple[str, str] | None:
    m = re.search(r"会议 (\d+) 点\s*(\d+) 分开，路上要 (\d+) 分钟，"
                  r"进楼安检排队约 (\d+) 分钟，我还想提前 (\d+) 分钟", q)
    if not m:
        return None
    h, mi, drive, buf, early = map(int, m.groups())
    t = h * 60 + mi - (drive + buf + early)
    return f"{t // 60}:{t % 60:02d}", ""


def audit_table(q: str, a: str) -> tuple[str, str] | None:
    m = re.search(r"三个人这周交的素材条数[:：](.+?)。交得最多的?比最少的?多几条", q)
    if not m:
        return None
    pairs = re.findall(r"(\S{1,4}) (\d+) 条", m.group(1))
    if len(pairs) < 2:
        return None
    vals = [int(v) for _, v in pairs]
    return str(max(vals) - min(vals)), ""


def audit_selfcheck(q: str, a: str) -> tuple[str, str] | None:
    m = re.search(r"乘以 (\d+) 得 (\d+)", q)
    if m:
        b1, prod = map(int, m.groups())
        if prod % b1:
            return "", "not-divisible"
        return str(prod // b1), ""
    return None



def audit_switch(q: str, a: str) -> tuple[str, str] | None:
    m = re.search(r"我兜里 (\d+)，本来打算买 (\d+) 块的那个，后来换成 (\d+) 块的，"
                  r"又顺手拿了 (\d+) 块的配件", q)
    if not m:
        return None
    budget, _first, second, extra = map(int, m.groups())
    return str(budget - second - extra), ""


def audit_drill(q: str, a: str) -> tuple[str, str] | None:
    m = re.search(r"会议 (\d+) 点\s*(\d+) 分开，路上 (\d+) 分钟，安检 (\d+) 分钟，"
                  r"还要提前 (\d+) 分钟到", q)
    if not m:
        return None
    h, mi, drive, buf, early = map(int, m.groups())
    t = h * 60 + mi - (drive + buf + early)
    return f"{t // 60}:{t % 60:02d}", ""


AUDITORS = {"arith": audit_arith, "logic": audit_logic, "multihop": audit_multihop,
            "finderr": audit_finderr, "shop": audit_shop, "schedule": audit_schedule,
            "table": audit_table, "selfcheck": audit_selfcheck,
            "switch": audit_switch, "drill": audit_drill}


def fam_of(rec: dict) -> str:
    src = str(rec.get("source") or "")
    return src.split(":")[-1]


def expr_check(a: str) -> list[str]:
    """校验正文里的算式：支持链式 a+b+c=d，以及 a×b=c / a-b=c。"""
    bad = []
    # 先处理链式加法，并把已验证片段从文中移除，避免被当成 "20+10=133" 误报
    for m in re.finditer(r"(\d+(?:\s*\+\s*\d+)+)\s*=\s*(\d+)", a):
        parts = [int(x) for x in re.split(r"\s*\+\s*", m.group(1))]
        if sum(parts) != int(m.group(2)):
            bad.append(m.group(0))
        a = a.replace(m.group(0), " ")
    for m in re.finditer(r"(\d+)\s*[×x]\s*(\d+)\s*=\s*(\d+)", a):
        x, y, z = map(int, m.groups())
        if x * y != z:
            bad.append(f"{x}×{y}={z}")
    for m in re.finditer(r"(\d+)\s*\+\s*(\d+)\s*=\s*(\d+)", a):
        x, y, z = map(int, m.groups())
        if x + y != z:
            bad.append(f"{x}+{y}={z}")
    for m in re.finditer(r"(\d+)\s*-\s*(\d+)\s*=\s*(\d+)", a):
        x, y, z = map(int, m.groups())
        if x - y != z:
            bad.append(f"{x}-{y}={z}")
    return bad


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = ["cot_samples.jsonl", "cot_deep.jsonl"]
    records = []
    for name in files:
        p = DATA / name
        if p.exists():
            records += [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    # 评测集也审
    eval_rows = []
    if EVAL.exists():
        eval_rows = [json.loads(l) for l in EVAL.read_text(encoding="utf-8").splitlines() if l.strip()]

    stats = Counter()
    seen_answers = set()
    problems = defaultdict(list)
    per_fam = Counter()

    def audit_one(rec, *, has_answer_check=True, fam_override=None):
        fam = fam_override or fam_of(rec)
        q = rec.get("prompt") or q_of(rec)
        a = a_of(rec) if "messages" in rec else ""
        auditor = AUDITORS.get(fam)
        if not auditor:
            stats["unknown-family"] += 1
            return
        out = auditor(q, a)
        per_fam[fam] += 1
        if out is None:
            stats["unparsed"] += 1
            problems[fam].append({"q": q[:60], "why": "unparsed"})
            return
        expect, why = out
        if why:
            stats["label-error"] += 1
            problems[fam].append({"q": q[:60], "why": why})
            return
        stored = rec.get("answer_check")
        if has_answer_check and stored is not None and str(stored) != expect:
            stats["label-mismatch"] += 1
            problems[fam].append({"q": q[:60], "stored": stored, "recomputed": expect})
        cl = claim(a) if a else None
        if a and cl and cl != expect and cl.replace("块", "").replace("条", "") != expect:
            stats["text-mismatch"] += 1
            problems[fam].append({"q": q[:60], "claim": cl, "recomputed": expect})
        bad = expr_check(a)
        if bad:
            stats["expr-error"] += 1
            problems[fam].append({"q": q[:60], "expr": bad})
        # 风格门：长度 / Markdown / 列表符 / 是否有推理痕迹
        if a:
            if len(a) > 200:
                stats["too-long"] += 1
                problems[fam].append({"q": q[:40], "why": f"len={len(a)}"})
            if re.search(r"(^|\n)\s*(#|[-*]\s|\d+\.\s)", a):
                stats["markdown-or-list"] += 1
                problems[fam].append({"q": q[:40], "why": "markdown/list"})
            trace = re.search(r"[=×÷+\-]", a) or re.search(
                r"往前推|减去|减 |加起来|合计|一共|相差|差 ", a)
            if fam != "logic" and not trace:
                stats["no-reasoning-trace"] += 1
                problems[fam].append({"q": q[:40], "why": "no-trace"})
        # 重复检查（同族重复答案）
        h = hash(a)
        if a and h in seen_answers:
            stats["dup-answer"] += 1
        seen_answers.add(h)

    for r in records:
        audit_one(r)
    for r in eval_rows:
        audit_one({"prompt": r["prompt"], "answer_check": r["expected"], "messages": []},
                  fam_override=r["family"])

    report = {"audited": sum(per_fam.values()), "per_family": dict(per_fam),
              "stats": dict(stats), "problems": {k: v[:8] for k, v in problems.items()},
              "verdict": "PASS" if not any(stats.get(k) for k in
                          ("label-error", "label-mismatch", "text-mismatch", "expr-error")) else "FAIL"}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("audited", "per_family", "stats", "verdict")},
                     ensure_ascii=False, indent=1))
    for fam, items in report["problems"].items():
        for it in items[:3]:
            print(f"  [{fam}] {it}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
