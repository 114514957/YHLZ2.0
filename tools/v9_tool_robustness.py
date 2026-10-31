#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""工具调用鲁棒性探针：用错误/畸形参数打每个工具，看会不会抛异常。

老爹 2026-10-20：「工具要经过测试可用，别写错调用就坏了」。
本脚本只做**安全**调用：
  · 只读工具 → 空参、缺参、类型错、未知参数、超长字符串
  · 有副作用/花钱的工具（qq_process/qq_summarize/web_*/file_download/song_play…）
    → 只打**会提前失败**的参数，确保不真干活

用法：
    python tools/v9_tool_robustness.py            # 探针报告
    python tools/v9_tool_robustness.py --json out.json
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

# 2026-10-20 教训：**探针不能再真干活**。
# 上一版把 qq_summarize 归到"只打提前失败的参数"，但它不接参数，
# 空参就直接跑云端归纳（913 条），实测真生成了 QQ-主题总结-2026-10-20.md、烧了一次 API。
# 现在分三档：
#   ① SCHEMA_ONLY：完全不执行，只查 schema/注册
#   ② EARLY_FAIL：只打"必然在校验阶段就失败"的参数
#   ③ 其余只读工具：全量畸形参数
SCHEMA_ONLY = {"qq_summarize", "song_play", "song_send", "file_download",
               "web_fetch", "web_search", "qq_digest"}
EARLY_FAIL = {
    # 这两个能靠畸形参数在校验阶段就返回，不会真跑
    "qq_process": [("max_items 非数字", {"max_items": "abc"}),
                   ("max_items 负数", {"max_items": -5})],
}


def hostile_cases(name: str) -> list[tuple[str, dict]]:
    if name in SCHEMA_ONLY:
        return []
    if name in EARLY_FAIL:
        return EARLY_FAIL[name]
    return [
        ("空参", {}),
        ("垃圾键", {"__bad__": 1}),
        ("类型错-数字当字符串", {"limit": "not-a-number", "group_id": 12345}),
        ("类型错-字符串当数字", {"max_items": "abc", "days": "xx"}),
        ("超长串", {"query": "群" * 5000, "path": "x" * 2000}),
        ("空串", {"group_id": "", "query": "", "path": ""}),
        ("None 值", {"group_id": None, "limit": None, "query": None}),
    ]


async def probe(reg, name: str) -> list[dict]:
    out = []
    for label, params in hostile_cases(name):
        rec = {"tool": name, "case": label}
        try:
            res = await reg.execute_openai_async(name, dict(params))
        except Exception as exc:  # noqa: BLE001
            rec.update(status="CRASH", exc=type(exc).__name__, msg=str(exc)[:160],
                       tb=traceback.format_exc().splitlines()[-3:])
            out.append(rec)
            continue
        if not isinstance(res, dict):
            rec.update(status="BADRET", msg="返回不是 dict: %r" % (type(res),))
        elif "ok" not in res:
            rec.update(status="BADRET", msg="返回缺 ok 字段: %s" % list(res)[:6])
        elif res.get("ok") is False:
            err = str(res.get("error") or res.get("output") or "")[:100]
            rec.update(status="ERR", msg=err)
        else:
            rec.update(status="OK", msg=str(res.get("output"))[:80])
        out.append(rec)
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    from backend.target_scheduler_tools import setup_scheduler_capabilities
    reg = setup_scheduler_capabilities()
    names = sorted(t["function"]["name"] for t in reg.export_openai_tools())
    print("探针目标：%d 个工具\n" % len(names))

    allrecs = []
    for n in names:
        cases = hostile_cases(n)
        if not cases:
            print("⏭  %-18s 只查 schema（会真干活，不执行）" % n)
            continue
        recs = asyncio.run(probe(reg, n))
        allrecs += recs
        crash = [r for r in recs if r["status"] == "CRASH"]
        bad = [r for r in recs if r["status"] == "BADRET"]
        flag = "❌" if (crash or bad) else "✅"
        print("%s %-18s 用例 %d ｜崩 %d ｜返回异常 %d"
              % (flag, n, len(recs), len(crash), len(bad)))
        for r in crash + bad:
            print("     [%s] %s: %s" % (r["case"], r.get("exc") or r["status"],
                                        r.get("msg", "")[:110]))
            for ln in r.get("tb") or []:
                print("        " + ln.strip()[:110])

    ncrash = sum(1 for r in allrecs if r["status"] == "CRASH")
    nbad = sum(1 for r in allrecs if r["status"] == "BADRET")
    print("\n合计：用例 %d ｜崩溃 %d ｜返回异常 %d" % (len(allrecs), ncrash, nbad))
    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(
            json.dumps(allrecs, ensure_ascii=False, indent=1))
        print("明细 ->", a.json)
    return 0 if (ncrash == 0 and nbad == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
