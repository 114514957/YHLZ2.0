#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真实多步工具轨迹 —— 第二批（复杂业务链，4–7 步）。

第一批 23 个任务只有 2–3 步、覆盖 34/40 工具。要支撑「agent 大部分能力」，
必须有**真正的多步业务链**：查 → 判断 → 补 → 再查 → 记账。

原则：
  · 写操作只做**有真实意义**的（写工作台账、存真实偏好、下载真文件），不灌垃圾
  · 删除类用**不存在的 ID** 触发真实失败（教"删错/查无怎么办"，且无副作用）
  · 每步真实执行，参数按真实 schema（全 string）

用法：
    python tools/v9_real_task_batch2.py --list
    python tools/v9_real_task_batch2.py --run-all
"""
from __future__ import annotations

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

BATCH2 = {
    # ── 长链：素材核查工作流（6 步）─────────────────────────
    "chain_material_check": ("核查素材现状：看目录 → 查台账 → 查知识库 → 看运行状态 → 记时间 → 补一条记录", [
        ("file_list", {"path": "docs/素材"}),
        ("ledger_search", {"query": "素材", "limit": 3}),
        ("kb_query", {"query": "素材", "limit": 3}),
        ("runtime_status", {}),
        ("system_time", {}),
        ("ledger_add", {"title": "元亨自查素材现状",
                        "body": "2026-10-22 19:50 自查：列了素材目录、翻了台账和知识库、看了运行状态。\n工具链真实跑通，参数按真实 schema（全 string）。"}),
    ]),
    # ── 长链：记忆维护工作流（5 步）─────────────────────────
    "chain_memory_upkeep": ("记忆维护：回忆 → 审计 → 因果图 → 存一条真偏好 → 画像确认", [
        ("memory_recall", {"query": "老爹 偏好", "limit": 3}),
        ("memory_audit", {}),
        ("memory_causal", {"action": "list", "limit": "3"}),
        ("memory_save", {"content": "老爹要求：成功＝元亨完美表现出应有的风格、具备 agent 大部分能力、正确调用工具",
                         "kind": "decision", "importance": 5}),
        ("memory_profile", {"key": "概览", "limit": "5"}),
    ]),
    # ── 长链：内容生产工作流（5 步）─────────────────────────
    "chain_content_produce": ("内容生产：搜资料 → 打开一条 → 存知识 → 写日记 → 记台账", [
        ("web_search", {"query": "continued pretraining 数据量 经验法则"}),
        ("kb_add", {"summary": "continued PT 经验：token/参数 0.0046 属极低，效果主要来自 SFT",
                    "category": "工程", "source": "元亨自查"}),
        ("kb_query", {"query": "continued PT", "limit": 2}),
        ("diary_write", {"content": "2026-10-22 19:52 记：今天把工具轨迹从「编」改成「真跑」。"
                                    "23 个任务 53 步，覆盖 34 个工具。发现真实 schema 参数全是 string。"}),
        ("ledger_add", {"title": "元亨记录 continued PT 经验",
                        "body": "token/参数 0.0046 属极低，continued PT 效果有限，主要靠 SFT。"}),
    ]),
    # ── 长链：QQ 数据盘点（5 步）────────────────────────────
    "chain_qq_audit": ("QQ 数据盘点：状态 → 导出 → 处理 → 总结 → 周报", [
        ("qq_status", {}),
        ("qq_export", {}),
        ("qq_process", {"max_items": "5"}),
        ("qq_summarize", {}),
        ("report_qq_weekly", {"days": "7"}),
    ]),
    # ── 长链：文件与分享（4 步）─────────────────────────────
    "chain_file_ops": ("文件操作：列 → 读 → 分享 → 下载", [
        ("file_list", {"path": "docs"}),
        ("file_read", {"path": "docs/报告/V9_训练成功率评估_20261022.md", "max_chars": "300"}),
        ("file_share", {"path": "docs/报告/V9_训练成功率评估_20261022.md"}),
        ("file_download", {"url": "https://example.com/robots.txt", "name": "robots.txt"}),
    ]),
    # ── 长链：日程与提醒（4 步）─────────────────────────────
    "chain_schedule_setup": ("日程设置：列现有 → 加一条 → 再列确认 → 看时间", [
        ("schedule_plan", {"action": "list"}),
        ("schedule_plan", {"action": "add", "name": "素材复检", "time": "10:00",
                           "cadence": "daily", "steps": "跑 v9_audit_all.py 看有没有新 FAIL"}),
        ("schedule_plan", {"action": "list"}),
        ("system_time", {}),
    ]),
    # ── 长链：技能沉淀（4 步）───────────────────────────────
    "chain_skill_pipeline": ("技能沉淀：找 → 存草稿 → 查知识 → 给反馈", [
        ("skill_search", {"query": "审核"}),
        ("skill_add", {"name": "素材审核四组检查", "trigger": "老爹说「审核」时",
                       "steps": "1)A组可训练性 2)B组内容质量 3)C组结构标记 4)D组PT池"}),
        ("kb_query", {"query": "审核", "limit": "3"}),
        ("skill_feedback", {"query": "素材审核四组检查", "good": "yes"}),
    ]),
    # ── 长链：歌单与发送（3 步）─────────────────────────────
    "chain_song_send": ("歌单操作：列 → 播放 → 发送", [
        ("song_list", {}),
        ("song_play", {"id": "song_20261021211846"}),
        ("song_send", {"id": "song_20261021211846"}),
    ]),
    # ── 长链：成员与现代群（3 步）──────────────────────────
    "chain_member_dig": ("成员与群：看成员 → 日汇编 → 看任务表", [
        ("member_profile", {"action": "list", "limit": "5"}),
        ("qq_digest", {}),
        ("task_plan", {"action": "list"}),
    ]),
    # ── 长链：台账深度操作（4 步）──────────────────────────
    "chain_ledger_deep": ("台账深操作：搜 → 取全文 → 追加 → 再取确认", [
        ("ledger_search", {"query": "工具轨迹", "limit": 2}),
        ("ledger_get", {"no": "973"}),
        ("ledger_update", {"no": "973", "append": "　\n- 补充2：真实轨迹第二批（复杂链）已落地 tools/v9_real_task_batch2.py。"}),
        ("ledger_get", {"no": "973"}),
    ]),
    # ── 删除类：用不存在的目标触发真实失败（无副作用）──────
    "chain_delete_guard": ("删除前先确认目标存在：删不存在的 → 查一下 → 再试一次", [
        ("ledger_delete", {"no": "999999"}),
        ("ledger_search", {"query": "999999", "limit": 1}),
        ("diary_delete", {"entry_stamp": "19700101"}),
    ]),
    # ── 混合：时间 + 任务 + 日程 三连（3 步）───────────────
    "chain_plan_today": ("今天怎么安排：看时间 → 列任务 → 列日程", [
        ("system_time", {}),
        ("task_plan", {"action": "list"}),
        ("schedule_plan", {"action": "list"}),
    ]),
    # ── 混合：知识问答全链（4 步）──────────────────────────
    "chain_kb_answer": ("回答问题前先查证：查知识 → 查台账 → 搜网 → 统一回答", [
        ("kb_query", {"query": "Gemma", "limit": "3"}),
        ("ledger_search", {"query": "Gemma", "limit": 3}),
        ("web_search", {"query": "Gemma 4 E4B 4-bit 显存"}),
        ("memory_recall", {"query": "Gemma", "limit": "2"}),
    ]),
}


def run_one(reg, name, params):
    t0 = time.time()
    try:
        res = asyncio.run(reg.execute_openai_async(name, dict(params)))
        ok, out, err = bool(res.get("ok")), res.get("output"), res.get("error")
    except Exception as exc:  # noqa: BLE001
        ok, out, err = False, None, "%s: %s" % (type(exc).__name__, str(exc)[:140])
    text = json.dumps(out, ensure_ascii=False) if isinstance(out, (dict, list)) else (out or "")
    return {"name": name, "params": params, "ok": ok, "output": text,
            "error": err, "elapsed": round(time.time() - t0, 2)}


def closing(steps):
    okn = sum(1 for s in steps if s["ok"])
    bad = [s for s in steps if not s["ok"]]
    if not bad:
        return "%d 步全成。做完的是：%s。" % (len(steps), "、".join(s["name"] for s in steps))
    if okn == 0:
        return "一步都没成。%s 报的是：%s" % (bad[0]["name"], (bad[0]["error"] or "")[:80])
    return ("%d 步里成了 %d 步。%s 没成，报的是：%s。"
            % (len(steps), okn, bad[0]["name"], (bad[0]["error"] or "")[:80]))


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--run-all", action="store_true")
    ap.add_argument("--max-chars", type=int, default=1200)
    a = ap.parse_args()

    if a.list:
        for k, (d, st) in BATCH2.items():
            print("%-24s %d步  %s" % (k, len(st), d))
        print("\n共 %d 任务 / %d 步" % (len(BATCH2), sum(len(v[1]) for v in BATCH2.values())))
        return 0
    if not a.run_all:
        ap.print_help()
        return 2

    from backend.target_scheduler_tools import setup_scheduler_capabilities
    reg = setup_scheduler_capabilities()
    recs = []
    for tname, (desc, spec) in BATCH2.items():
        print("\n=== %s：%s ===" % (tname, desc))
        steps = []
        for i, (tool, params) in enumerate(spec, 1):
            r = run_one(reg, tool, params)
            steps.append(r)
            print("  %d. %-18s ok=%-5s %s"
                  % (i, tool, r["ok"], (r["output"] or r["error"] or "")[:70].replace("\n", " ")))
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
        msgs.append({"role": "assistant", "content": closing(steps)})
        recs.append({"messages": msgs, "simulation": False, "generated": False,
                     "real_run": True, "task": tname, "steps": len(steps),
                     "ok_steps": sum(1 for s in steps if s["ok"]),
                     "source": "realtask:%s" % tname})

    mode = "a" if os.path.exists(OUT) else "w"
    with io.open(OUT, mode, encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tot = sum(r["steps"] for r in recs)
    okn = sum(r["ok_steps"] for r in recs)
    print("\n=== 第二批汇总 ===")
    print("任务 %d｜步骤 %d（成功 %d / 失败 %d）→ 追加到 %s"
          % (len(recs), tot, okn, tot - okn, OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
