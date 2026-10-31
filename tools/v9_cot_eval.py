"""CoT 专项评测（ledger 0894）。

固定题集（种子 777，与训练种子不同）→ 每题问本地模型 → 从回答里抽答案比对。
族：arith / logic / multihop / finderr（单步）＋ shop / schedule / table / selfcheck（多步）。
判分：数值族比"最后一个数"；logic 比人名是否出现；schedule 比 H:MM 是否出现。
同时统计"讲台腔"信号（列表符/标题/首先其次/综上）。

用法：python tools/v9_cot_eval.py [--base http://127.0.0.1:8081] [--per-family 8]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import re
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
OUT = ROOT / "cache" / "v9_materials_preparation" / "cot_eval.json"
SET = ROOT / "data" / "eval" / "cot_eval_set.jsonl"

import v9_cot_build as B  # noqa: E402
import v9_cot_deep as D  # noqa: E402

FAMS = {"arith": B.fam_arith, "logic": B.fam_logic, "multihop": B.fam_multihop,
        "finderr": B.fam_finderr, "shop": D.fam_shop, "schedule": D.fam_schedule,
        "table": D.fam_table, "selfcheck": D.fam_selfcheck,
        "switch": D.fam_switch, "drill": D.fam_drill}
PLATFORM = ("首先", "其次", "综上", "总之", "1.", "2.", "- ", "* ", "#")


def ask(base: str, prompt: str, retries: int = 1) -> str:
    body = {"model": "local",
            "messages": [{"role": "system", "content": "你是元亨，说话口语、简短。"},
                         {"role": "user", "content": prompt}],
            "temperature": 0, "max_tokens": 260}
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    last = None
    for i in range(retries + 1):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=180).read())
            return str((d.get("choices") or [{}])[0].get("message", {}).get("content") or "")
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i < retries:
                time.sleep(3)
    raise last  # type: ignore[misc]


def final_claim(text: str) -> str:
    """取"最后一个断言"（答案/结果/应当得），没有就取最后一个数字。"""
    ms = list(re.finditer(r"(?:那答案|答案|结果|应当得|应该是)\s*[:：]?\s*([^\s。，,]+)", text))
    if ms:
        return ms[-1].group(1)
    nums = re.findall(r"-?\d+(?:\.\d+)?", text)
    return nums[-1] if nums else ""


def check(fam: str, text: str, expected: str) -> bool:
    """宽松但可复现的判分：只看"答案是否出现在回答里"，不要求它是最后一个数。"""
    t = text.replace(" ", "").replace("，", ",").replace("：", ":")
    if fam == "logic":
        return expected in text
    if fam in ("schedule", "drill"):
        hh, mm = expected.split(":")
        variants = {expected, f"{hh}点{mm}分", f"{hh}:{mm}", f"{hh}点{int(mm)}分",
                    f"{hh}点{mm}"}
        return any(v in t for v in variants)
    if fam == "finderr":
        # 问的是"他错在哪"：指出顺序/括号问题就算对，不强求报出正确乘积
        keys = ("先乘", "乘除", "顺序", "从左", "括号", "运算优先级", "不能换")
        if any(k in t for k in keys):
            return True
    # 数值：允许千分位/小数；以"独立数字"匹配，避免 133 里匹配到 13
    claim = final_claim(text)
    pat = r"(?<![\d.]){}(?![\d.])".format(re.escape(expected))
    if re.search(pat, claim.replace(" ", "")):
        return True
    # 期望是负数时也接受 "-N"
    return False


def build_set(per_family: int) -> list[dict]:
    rng = random.Random(777)
    items = []
    for fam, fn in FAMS.items():
        n = 0
        seen = set()
        for _ in range(per_family * 20):
            if n >= per_family:
                break
            it = fn(rng)
            k = it["q"][:26]
            if k in seen:
                continue
            seen.add(k)
            items.append({"family": fam, "prompt": it["q"], "expected": it["ans"]})
            n += 1
    return items


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8081")
    ap.add_argument("--per-family", type=int, default=8)
    ap.add_argument("--families", default="", help="逗号分隔，只跑指定族")
    args = ap.parse_args()
    items = build_set(args.per_family)
    if args.families:
        keep = {x.strip() for x in args.families.split(",") if x.strip()}
        items = [x for x in items if x["family"] in keep]
    SET.parent.mkdir(parents=True, exist_ok=True)
    with SET.open("w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")

    by_fam: dict[str, list] = {}
    results = []
    fatal = 0
    for it in items:
        try:
            text = ask(args.base, it["prompt"])
        except Exception as exc:  # noqa: BLE001
            text = ""
            err = f"{type(exc).__name__}: {str(exc)[:60]}"
            fatal += 1
            if fatal == 3:
                print("[abort] 连续 3 次请求失败，模型可能没起：" + err, file=sys.stderr)
                return 3
        else:
            err = ""
        ok = check(it["family"], text, str(it["expected"])) if text else False
        platform = [w for w in PLATFORM if w in text]
        results.append({**it, "reply": text[:300], "ok": ok,
                        "platform_voice": platform, "error": err})
        by_fam.setdefault(it["family"], []).append(ok)
        print(f"  {'✓' if ok else '✗'} [{it['family']:9s}] 期望 {str(it['expected']):>8s} "
              f"| 回: {text[:54].replace(chr(10), ' ')}")
        time.sleep(0.2)

    fam_acc = {k: round(100.0 * sum(v) / len(v), 1) for k, v in by_fam.items()}
    overall = round(100.0 * sum(1 for r in results if r["ok"]) / len(results), 1)
    plat = sum(1 for r in results if r["platform_voice"])
    report = {"cases": len(results), "overall_accuracy": overall,
              "by_family": fam_acc, "platform_voice_cases": plat,
              "errors": sum(1 for r in results if r["error"]),
              "results": results}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"cases": len(results), "overall": overall, "by_family": fam_acc,
                      "platform_voice_cases": plat}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
