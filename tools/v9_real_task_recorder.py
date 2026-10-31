#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真实多步工具轨迹采集器 v2（老爹 2026-10-22「去」）。

v1 暴露的问题（已修）：
  · `memory_profile` 少了必填 `key` → `missing input: key`
  · `task_plan` 少了 `action` → `add/done require task content`
  这两个失败**本身有价值**（真实参数错），但任务设计要分两类：
    good_*  → 参数正确，跑通，教"该怎么调"
    bad_*   → 参数故意错/缺，真实报错，教"错了怎么处理"

v1 还发现：**真实 schema 里所有参数声明都是 string**（含 max_items/limit/id），
但 handler 内部会把数字字符串转 int，所以 `{"limit": 3}` 和 `{"limit": "3"}` 都能跑；
`max_items="abc"` 则返回 `{"ok":false,"error":"max_items..."}` 而不是崩溃。

覆盖目标：40 个暴露工具，每 2–5 步一串，写操作只做**有真实意义**的（kb_add 真知识、
diary_write 真日记、skill_add 真技能），不往台账/记忆里灌垃圾。
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = "data/finetune/tool_multistep_real.jsonl"
SYSTEM = ("你是元亨——数字生命体，老爹的伙伴。工具只能调用真实注册表中的能力；"
          "缺参先问、查无直说、失败照实讲，不编工具、不编结果。")

TASKS = {
    # ── 只读链路（参数正确，教"该怎么调"）────────────────────
    "good_qq_inventory": ("盘点 QQ 数据：状态 → 导出 → 记时间", [
        ("qq_status", {}),
        ("qq_export", {}),
        ("system_time", {}),
    ]),
    "good_ledger_dig": ("查台账：搜 → 列 → 按号取全文", [
        ("ledger_search", {"query": "素材", "limit": 3}),
        ("ledger_list", {"limit": 3}),
        ("ledger_get", {"no": "973"}),
    ]),
    "good_memory_probe": ("记忆体检：回忆 → 审计 → 画像", [
        ("memory_recall", {"query": "素材", "limit": 3}),
        ("memory_audit", {}),
        ("memory_profile", {"key": "概览", "limit": "10"}),
    ]),
    "good_memory_graph": ("记忆因果：看因果图 → 查某条为什么", [
        ("memory_causal", {"action": "list", "limit": "5"}),
        ("memory_why", {"id": "1", "limit": "3"}),
    ]),
    "good_diary": ("日记：列 → 读文件确认 → 写一条真日记", [
        ("diary_list", {"limit": 3}),
        ("file_list", {"path": "docs"}),
        ("diary_write", {"content": "2026-10-22 19:40 记：今天把工具轨迹从模拟改成真实调用，"
                                    "先跑通 9 个多步任务，下一步扩到覆盖 40 个工具。"}),
    ]),
    "good_kb_skill": ("知识库与技能：查 → 找技能 → 给反馈", [
        ("kb_query", {"query": "素材", "limit": 3}),
        ("skill_search", {"query": "素材"}),
        ("skill_feedback", {"query": "数据口径与汇报规范", "good": "yes"}),
    ]),
    "good_file": ("文件勘察：列目录 → 读文件", [
        ("file_list", {"path": "docs/素材"}),
        ("file_read", {"path": "README.md", "max_chars": "400"}),
    ]),
    "good_time_task": ("时间与任务表：现在几点 → 列任务", [
        ("system_time", {}),
        ("task_plan", {"action": "list"}),
    ]),
    "good_runtime": ("运行状态：运行时 → QQ → 时间", [
        ("runtime_status", {}),
        ("qq_status", {}),
        ("system_time", {}),
    ]),
    "good_song": ("歌单与播放：列歌单 → 播放", [
        ("song_list", {}),
        ("song_play", {"id": "1"}),
    ]),
    "good_qq_pipeline": ("群聊处理链：处理 → 日汇编 → 总结", [
        ("qq_process", {"max_items": "3"}),
        ("qq_digest", {}),
        ("qq_summarize", {}),
    ]),
    "good_weekly": ("周报链路：周报 → 看成员", [
        ("report_qq_weekly", {"days": "7"}),
        ("member_profile", {"action": "list", "limit": "3"}),
    ]),
    "good_web": ("网上查证：搜 → 打开一条", [
        ("web_search", {"query": "Gemma 4 E4B 参数量"}),
        ("web_fetch", {"url": "https://example.com"}),
    ]),
    "good_schedule": ("日程：列 → 排一条", [
        ("schedule_plan", {"action": "list"}),
        ("schedule_plan", {"action": "add", "name": "素材复检",
                           "time": "2026-10-23 10:00", "cadence": "once"}),
    ]),
    "good_skill_add": ("存技能：先找 → 再存一条真技能", [
        ("skill_search", {"query": "工具轨迹"}),
        ("skill_add", {"name": "工具轨迹采集", "trigger": "需要真实多步工具样本时",
                       "steps": "1)列任务 2)真实调用 3)记返回 4)转SFT格式"}),
    ]),
    "good_kb_sediment": ("知识沉淀：查 → 存一条真知识", [
        ("kb_query", {"query": "素材审核", "limit": 3}),
        ("kb_add", {"summary": "素材可训练性四项：arguments为对象/Dataset能建表/模板能渲染/截断率<5%",
                    "category": "工程", "source": "v9_audit_all.py"}),
    ]),
    "good_ledger_update": ("台账补记：先查号 → 再追加一行", [
        ("ledger_get", {"no": "973"}),
        ("ledger_update", {"no": "973", "append": "补充：真实轨迹采集器已落地 tools/v9_real_task_recorder.py"}),
    ]),
    # ── 故意出错（真实报错，教"错了怎么办"）─────────────────
    "bad_missing_key": ("记忆画像没给 key", [
        ("memory_profile", {}),
        ("memory_profile", {"key": "概览"}),
    ]),
    "bad_task_no_action": ("任务表没给 action", [
        ("task_plan", {}),
        ("task_plan", {"action": "list"}),
    ]),
    "bad_bad_number": ("数量参数给了文字", [
        ("qq_process", {"max_items": "abc"}),
        ("qq_process", {"max_items": "2"}),
    ]),
    "bad_wrong_id": ("歌 id 猜错", [
        ("song_play", {"id": "999999"}),
        ("song_list", {}),
    ]),
    "bad_no_such": ("查不存在的工具", [
        ("search_all", {"query": "x"}),
        ("ledger_search", {"query": "x", "limit": 1}),
    ]),
    "bad_missing_required": ("台账取详情没给号", [
        ("ledger_get", {}),
        ("ledger_get", {"no": "973"}),
    ]),
}


def run_one(reg, name, params):
    t0 = time.time()
    try:
        res = asyncio.run(reg.execute_openai_async(name, dict(params)))
        ok = bool(res.get("ok"))
        out = res.get("output")
        err = res.get("error")
    except Exception as exc:  # noqa: BLE001
        ok, out, err = False, None, "%s: %s" % (type(exc).__name__, str(exc)[:140])
    text = json.dumps(out, ensure_ascii=False) if isinstance(out, (dict, list)) else (out or "")
    return {"name": name, "params": params, "ok": ok, "output": text,
            "error": err, "elapsed": round(time.time() - t0, 2)}


def closing(steps, task: str) -> str:
    okn = sum(1 for s in steps if s["ok"])
    bad = [s for s in steps if not s["ok"]]
    if not bad:
        return "%d 步全成。做完的是：%s。" % (len(steps), "、".join(s["name"] for s in steps))
    if okn == 0:
        return "一步都没成。%s 报的是：%s" % (bad[0]["name"], (bad[0]["error"] or "")[:80])
    return ("%d 步里成了 %d 步。%s 没成，报的是：%s。"
            % (len(steps), okn, bad[0]["name"], (bad[0]["error"] or "")[:80]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--run", default="")
    ap.add_argument("--run-all", action="store_true")
    ap.add_argument("--max-chars", type=int, default=1200)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    if a.list:
        for k, (d, st) in TASKS.items():
            print("%-22s %d步  %s" % (k, len(st), d))
        print("\n共 %d 个任务 / %d 步" % (len(TASKS), sum(len(v[1]) for v in TASKS.values())))
        return 0

    names = list(TASKS) if a.run_all else ([a.run] if a.run else [])
    if not names:
        ap.print_help()
        return 2

    from backend.target_scheduler_tools import setup_scheduler_capabilities
    reg = setup_scheduler_capabilities()
    recs = []
    for tname in names:
        desc, spec = TASKS[tname]
        print("\n=== %s：%s ===" % (tname, desc))
        steps = []
        for i, (tool, params) in enumerate(spec, 1):
            r = run_one(reg, tool, params)
            steps.append(r)
            head = (r["output"] or r["error"] or "")[:80].replace("\n", " ")
            print("  %d. %-18s ok=%-5s %s" % (i, tool, r["ok"], head))
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": desc}]
        for i, s in enumerate(steps, 1):
            out = s["output"] if s["ok"] else json.dumps(
                {"ok": False, "error": s["error"] or "unknown"}, ensure_ascii=False)
            if len(out) > a.max_chars:
                out = out[:a.max_chars] + "…（截断，原长 %d）" % len(out)
            msgs.append({"role": "assistant", "content": "",
                         "tool_calls": [{"id": "c%d" % i, "type": "function",
                                         "function": {"name": s["name"],
                                                      "arguments": json.dumps(
                                                          s["params"], ensure_ascii=False)}}]})
            msgs.append({"role": "tool", "name": s["name"], "content": out})
        msgs.append({"role": "assistant", "content": closing(steps, tname)})
        recs.append({"messages": msgs, "simulation": False, "generated": False,
                     "real_run": True, "task": tname, "steps": len(steps),
                     "ok_steps": sum(1 for s in steps if s["ok"]),
                     "source": "realtask:%s" % tname})

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tot = sum(r["steps"] for r in recs)
    okn = sum(r["ok_steps"] for r in recs)
    print("\n=== 汇总 ===")
    print("任务 %d 个｜真实步骤 %d 步（成功 %d，失败 %d）→ %s"
          % (len(recs), tot, okn, tot - okn, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
