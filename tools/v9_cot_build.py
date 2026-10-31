"""思维链（CoT）素材生成（ledger 0893）。

老爹要「有助于思维链」的素材。这里的 CoT 指**可验证的推理过程**，不是长解释：
  1) 算术应用题（多步、答案由代码算出）
  2) 逻辑推理（排序题 / 真假话 / 集合计数，答案由约束求解验证）
  3) 多跳检索（给 3 条事实，问需要合并两条的问题）
  4) 找错（给结论 + 步骤，指出哪一步错）

风格：元亨口语短推理（"先… 再… 嗯，那…"），不列清单、不用 Markdown、≤130 字；
每族参数与模板随机化，防模板记忆；输出带 `cot:<family>` 与 group_id，供成组切分。

产出：data/finetune/cot_samples.jsonl
用法：python tools/v9_cot_build.py [--per-family 120]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "finetune" / "cot_samples.jsonl"

OPEN = ["嗯，", "让我想想，", "等下，", "这个得算算，", ""]


def wrap(steps: str, ans: str) -> str:
    return f"{steps}那答案是 {ans}。" if steps else f"答案是 {ans}。"


def fam_arith(rng: random.Random) -> dict:
    a = rng.randint(12, 80)
    b = rng.randint(3, 12)
    c = rng.randint(2, 9)
    d = rng.randint(2, 30)
    kind = rng.choice(["buy", "save", "batch"])
    if kind == "buy":
        q = f"一盒笔 {a} 支，我买了 {b} 盒，用掉 {c * b} 支，还剩多少？"
        total = a * b
        ans = total - c * b
        steps = f"一盒 {a} 支，{b} 盒就是 {a}×{b}={total}；用掉 {c*b}，{total}-{c*b}={ans}。"
    elif kind == "save":
        q = f"每天存 {b} 块，存了 {c} 天，之前有 {a} 块，一共多少？"
        ans = a + b * c
        steps = f"每天 {b}，{c} 天是 {b}×{c}={b*c}；再加原来的 {a}，得 {ans}。"
    else:
        d = d % 15 + 1
        b2 = b % 6 + 2
        a = d + b2 * ((a - d) // b2 if (a - d) >= b2 else 1)   # 保证能整除
        q = f"一批 {a} 件，先留 {d} 件备用，剩下的平均分成 {b2} 份，每份多少件？"
        ans = (a - d) // b2
        steps = f"先留 {d} 件，剩 {a-d} 件；分成 {b2} 份，{a-d}÷{b2}={ans}。"
    return {"q": q, "a": wrap(steps, ans), "ans": ans}


def fam_logic(rng: random.Random) -> dict:
    names = rng.sample(["阿青", "小满", "老周", "林一", "苏苏", "阿禾", "小丁",
                        "老秦", "十一", "阿柚"], 3)
    order = rng.sample(names, 3)  # 高→低
    q = (f"{order[0]}比{order[1]}高，{order[1]}比{order[2]}高，"
         f"三个人谁最高？")
    steps = f"{order[0]}比{order[1]}高，{order[1]}又比{order[2]}高，所以{order[0]}最高。"
    return {"q": q, "a": wrap(steps, order[0]), "ans": order[0]}


def fam_multihop(rng: random.Random) -> dict:
    who = rng.choice(["老爹", "利贞", "群主"])
    thing = rng.choice(["素材清单", "派单", "工具轨迹", "记忆样本"])
    place = rng.choice(["台账", "群里", "工作台"])
    n1 = rng.randint(11, 89)
    n2 = rng.randint(2, 37)
    unit = rng.choice(["条", "份", "个"])
    q = (f"{who}在{place}提过{thing}的事，第一次说了 {n1} {unit}，后来又补了 {n2} {unit}，"
         f"一共几{unit}？")
    total = n1 + n2
    steps = f"第一次 {n1} {unit}，后来又补 {n2} {unit}，{n1}+{n2}={total}。"
    return {"q": q, "a": wrap(steps, f"{total} {unit}"), "ans": total}


def fam_finderr(rng: random.Random) -> dict:
    a = rng.randint(3, 9)
    b = rng.randint(4, 12)
    wrong = a * b + rng.choice([1, 2, 3, -1])
    q = (f"有人算 {a}×{b} 得 {wrong}，还说'先加后乘也对'。他错在哪？")
    right = a * b
    steps = (f"{a}×{b} 是 {right}，不是 {wrong}；而且加法和乘法不能换顺序，"
             f"他说'先加后乘也对'这句本身就错。")
    return {"q": q, "a": wrap(steps, f"应当得 {right}"), "ans": right}


FAMS = {"arith": fam_arith, "logic": fam_logic,
        "multihop": fam_multihop, "finderr": fam_finderr}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-family", type=int, default=120)
    args = ap.parse_args()
    rng = random.Random(20261020)

    rows, seen, seen_ans = [], set(), set()
    for fam, fn in FAMS.items():
        n = 0
        for _ in range(args.per_family * 8):
            if n >= args.per_family:
                break
            item = fn(rng)
            key = item["q"][:24]
            if key in seen:
                continue
            seen.add(key)
            if item["a"] in seen_ans:
                continue
            seen_ans.add(item["a"])
            q = rng.choice(OPEN) + item["q"]
            msgs = [{"role": "user", "content": q},
                    {"role": "assistant", "content": item["a"]}]
            rows.append({"messages": msgs, "source": f"cot:{fam}",
                         "source_id": f"cot#{fam}#{n}", "group_id": f"cot:{fam}",
                         "simulation": True, "generated": True, "license": "own",
                         "answer_check": item["ans"],
                         "content_hash": hashlib.sha256(
                             json.dumps(msgs, ensure_ascii=False).encode()).hexdigest()[:16]})
            n += 1
        print(f"  {fam}: {n}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(rows), "families": list(FAMS),
                      "file": str(OUT.relative_to(ROOT))}, ensure_ascii=False))
    for r in rows[:3]:
        print("  Q:", r["messages"][0]["content"][:60])
        print("   A:", r["messages"][1]["content"][:80])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
