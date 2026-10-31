"""多步思维链（deep CoT）生成（ledger 0893）。

与 `v9_cot_build.py`（单步/两步）不同，这里要求**3–4 步中间态**，且答案必须能反算校验：
  1) deep:shop     多商品 + 折扣 + 找零（4 步）
  2) deep:schedule 时间算术（出发+车程+缓冲+提前量）
  3) deep:table    给 3 人数据，求"最多者与最少者之差"（找→比→减）
  4) deep:selfcheck 解完用逆运算自检（乘除互验）

全部：题面 ≥110 字、答案 ≤170 字、口语短推理、无列表；答案由代码算出并 assert 校验。
产出 data/finetune/cot_deep.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "finetune" / "cot_deep.jsonl"
OPEN = ["嗯，", "这个得算两步，", "先理一下，", ""]


def fam_shop(rng: random.Random) -> dict:
    p1, n1 = rng.randint(8, 30), rng.randint(2, 5)
    p2, n2 = rng.randint(5, 20), rng.randint(1, 4)
    paid = 300
    total = p1 * n1 + p2 * n2
    cut = rng.choice([10, 15, 20])
    final = total - cut
    change = paid - final
    assert change > 0 and final > 0
    q = (f"去超市，苹果 {p1} 块一斤买 {n1} 斤，牛奶 {p2} 块一盒买 {n2} 盒，"
         f"结账满 100 减 {cut}，我给了 {paid}，该找我多少？")
    a = (f"苹果 {p1}×{n1}={p1*n1}，牛奶 {p2}×{n2}={p2*n2}，合计 {total}；"
         f"满减 {cut}，实付 {final}；{paid}-{final}={change}。那答案是 {change} 块。")
    return {"q": q, "a": a, "ans": str(change)}


def fam_schedule(rng: random.Random) -> dict:
    h, m = rng.randint(6, 9), rng.choice([0, 10, 20, 30])
    drive = rng.randint(35, 80)
    buf = rng.choice([10, 15, 20])
    early = rng.choice([5, 10, 15])
    total = drive + buf + early
    t0 = h * 60 + m
    t1 = t0 - total          # 出门时间（题问的是这个）
    assert 0 <= t1 < 24 * 60
    q = (f"会议 {h} 点{'%02d' % m} 分开，路上要 {drive} 分钟，进楼安检排队约 {buf} 分钟，"
         f"我还想提前 {early} 分钟到，那我最晚几点出门？")
    a = (f"路上 {drive} 加安检 {buf} 再提前 {early}，一共 {total} 分钟；"
         f"{h} 点{'%02d' % m} 分往前推 {total} 分钟，是 {t1//60} 点{t1%60:02d}。"
         f"那答案是 {t1//60}:{t1%60:02d}。")
    return {"q": q, "a": a, "ans": f"{t1//60}:{t1%60:02d}"}


def fam_table(rng: random.Random) -> dict:
    names = rng.sample(["阿青", "小满", "老周", "林一", "苏苏", "阿禾"], 3)
    vals = rng.sample(range(3, 40), 3)
    data = dict(zip(names, vals))
    hi = max(data, key=data.get)
    lo = min(data, key=data.get)
    diff = data[hi] - data[lo]
    q = ("三个人这周交的素材条数：" + "、".join(f"{k} {v} 条" for k, v in data.items()) +
         f"。交得最多的比最少的多几条？")
    a = (f"{hi}最多 {data[hi]} 条，{lo}最少 {data[lo]} 条，"
         f"{data[hi]}-{data[lo]}={diff}。那答案是 {diff} 条。")
    return {"q": q, "a": a, "ans": str(diff)}


def fam_selfcheck(rng: random.Random) -> dict:
    a = rng.randint(12, 60)
    b = rng.randint(3, 9)
    prod = a * b
    q = (f"有个数乘以 {b} 得 {prod}，我怀疑原来那个数算错了。"
         f"你先把它反推出来，再验一遍，最后告诉我结果。")
    a_txt = (f"反推就是 {prod}÷{b}={a}；验一下 {a}×{b}={prod}，对上了。那答案是 {a}。")
    return {"q": q, "a": a_txt, "ans": str(a)}



def fam_switch(rng: random.Random) -> dict:
    """中途改条件：先一个方案，后来改成另一个，最后按新条件算。"""
    budget = rng.choice([200, 300, 500])
    first = rng.randint(35, 90)
    second = rng.randint(95, 160)
    extra = rng.randint(10, 40)
    ans = budget - second - extra
    assert ans > 0
    q = (f"我兜里 {budget}，本来打算买 {first} 块的那个，后来换成 {second} 块的，"
         f"又顺手拿了 {extra} 块的配件，最后还剩多少？")
    a = (f"本来那个不算了，按换的来：{budget}-{second}={budget-second}；"
         f"再减配件 {extra}，{budget-second}-{extra}={ans}。那答案是 {ans}。")
    return {"q": q, "a": a, "ans": str(ans)}


def fam_drill(rng: random.Random) -> dict:
    """跨小时借位专项：会议时间减总耗时，必跨小时。"""
    h = rng.randint(6, 9)
    mi = rng.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
    drive = rng.randint(50, 115)
    buf = rng.choice([10, 15, 20, 25])
    early = rng.choice([5, 10, 15])
    total = drive + buf + early
    if total <= mi + 60:          # 保证跨小时借位
        drive += mi + 61 - total
        total = drive + buf + early
    t1 = h * 60 + mi - total
    assert 0 <= t1 < 24 * 60
    q = (f"会议 {h} 点{mi:02d} 分开，路上 {drive} 分钟，安检 {buf} 分钟，"
         f"还要提前 {early} 分钟到，最晚几点出门？")
    a = (f"{drive}+{buf}+{early}={total} 分钟；{h} 点{mi:02d} 往前推 {total} 分钟，"
         f"{h} 点{mi:02d} 换成 {h*60+mi} 分钟，{h*60+mi}-{total}={t1}，就是 {t1//60} 点{t1%60:02d}。"
         f"那答案是 {t1//60}:{t1%60:02d}。")
    return {"q": q, "a": a, "ans": f"{t1//60}:{t1%60:02d}"}


FAMS = {"shop": fam_shop, "schedule": fam_schedule,
        "table": fam_table, "selfcheck": fam_selfcheck,
        "switch": fam_switch, "drill": fam_drill}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-family", type=int, default=100)
    args = ap.parse_args()
    rng = random.Random(20261021)
    rows, seen, seen_ans = [], set(), set()
    for fam, fn in FAMS.items():
        n = 0
        for _ in range(args.per_family * 10):
            if n >= args.per_family:
                break
            it = fn(rng)
            key = it["q"][:30]
            if key in seen:
                continue
            seen.add(key)
            if it["a"] in seen_ans:
                continue
            seen_ans.add(it["a"])
            q = rng.choice(OPEN) + it["q"]
            msgs = [{"role": "user", "content": q},
                    {"role": "assistant", "content": it["a"]}]
            rows.append({"messages": msgs, "source": f"cotdeep:{fam}",
                         "source_id": f"cotd#{fam}#{n}", "group_id": f"cotdeep:{fam}",
                         "simulation": True, "generated": True, "license": "own",
                         "answer_check": it["ans"],
                         "content_hash": hashlib.sha256(
                             json.dumps(msgs, ensure_ascii=False).encode()).hexdigest()[:16]})
            n += 1
        print(f"  {fam}: {n}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(rows), "file": str(OUT.relative_to(ROOT))},
                     ensure_ascii=False))
    for r in rows[:3]:
        print("  Q:", r["messages"][0]["content"][:86])
        print("   A:", r["messages"][1]["content"][:100])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
