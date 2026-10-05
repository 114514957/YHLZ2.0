"""人格回归基线 harness（2026-09-24，台账 0498）。

把"人格 / 关系 / 工具遵循"跑成**可复现的一行分**，落到版本 × 得分表，
替代"聊两句感觉还行"。

三种用法：
  python tools/persona_regression.py --dump out.json              # 出题模板（离线/人工作答）
  python tools/persona_regression.py --answers out.json --version v7b   # 离线评分（不占 GPU）
  python tools/persona_regression.py --live --version v7b         # 真机跑（需 8081/LLM）

产物：
  docs/报告/人格回归基线.md                    版本 × 得分表（每次追加一行）
  docs/报告/人格回归明细_<版本>_<run_id>.md/json  逐题明细与独立证据清单

安全：``--live`` 必须在专用进程运行：空夹具+Python I/O审计，不是OS沙箱。
禁正式数据/外网/子进程，排空后台任务后还原；隔离拒绝即整轮无效。
默认工具策略取生产策略交集，diagnostic明确单列，旧关键词得分不是完整验收。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import tempfile
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from tools.persona_bank import CATEGORIES, PERSONA_BANK, verify  # noqa: E402
from tools.persona_eval_evidence import (  # noqa: E402
    POLICY_MODES, bounded_tool_trace, build_manifest, constrained_policy,
    digest, new_run_id, review_checklist, safe_label,
    tool_execution_assessment, write_new_json,
)

BASELINE_FILE = _ROOT / "docs" / "报告" / "人格回归基线.md"
_TABLE_HEAD = "| 日期 | 版本 | " + " | ".join(CATEGORIES) + " | 合计 | 备注 |"
_TABLE_SEP = "|---|---|" + "---|" * len(CATEGORIES) + "---|---|"


def _filter(bank: list[dict], only: str = "", limit: int = 0) -> list[dict]:
    items = [e for e in bank if (not only or e["cat"] == only)]
    return items[:limit] if limit and limit > 0 else items


# ---------------- 评分（纯函数，可单测）----------------
def score_items(bank: list[dict], answers: list[dict]) -> list[dict]:
    """按 id（回退到 q）配对作答，逐题判定。缺答记 ok=False。"""
    by_id = {e["id"]: e for e in bank}
    by_q = {e["q"]: e for e in bank}
    results: list[dict] = []
    for item in answers:
        entry = by_id.get(str(item.get("id") or "")) or by_q.get(str(item.get("q") or ""))
        if entry is None:
            continue
        ok, detail = verify(entry, item.get("answer", ""), item.get("tools") or [])
        results.append({"id": entry["id"], "cat": entry["cat"], "q": entry["q"],
                        "ok": ok, "detail": detail,
                        "answer": str(item.get("answer") or "")[:200],
                        "tools": [str(t) for t in (item.get("tools") or [])]})
    answered = {r["id"] for r in results}
    for entry in bank:
        if entry["id"] not in answered:
            results.append({"id": entry["id"], "cat": entry["cat"], "q": entry["q"],
                            "ok": False, "detail": "!未作答", "answer": "", "tools": []})
    order = {e["id"]: i for i, e in enumerate(bank)}
    return sorted(results, key=lambda r: order.get(r["id"], 10 ** 6))


def summarize(results: list[dict]) -> dict:
    """按类别汇总：{cat: {n, ok}} + total + accuracy。"""
    by_cat = {c: {"n": 0, "ok": 0} for c in CATEGORIES}
    for r in results:
        d = by_cat.setdefault(r["cat"], {"n": 0, "ok": 0})
        d["n"] += 1
        d["ok"] += 1 if r["ok"] else 0
    total_n = len(results)
    total_ok = sum(1 for r in results if r["ok"])
    return {"by_cat": by_cat, "n": total_n, "ok": total_ok,
            "accuracy": (total_ok / total_n) if total_n else 0.0}


# ---------------- 报表 ----------------
def append_score_row(path: pathlib.Path, row: str,
                     env_block: str = "") -> None:
    """把一行写进版本 × 得分表；文件/表格不存在时先补表头。

    ``env_block``：仅在**首次建表**时写进去的运行环境说明（模型/LoRA/地址），
    让表里每一行分数都能追到具体模型——这是"分数可归因"的一半。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    row = row.rstrip("\n")
    if not path.exists():
        head = ["# 人格回归基线（版本 × 得分）", "",
                "> 题库：`tools/persona_bank.py`（确定性判定，无 LLM 判官）；"
                "harness：`tools/persona_regression.py`。",
                "> 跑法：`--live --version <版本> --expect-lora <lora 文件名>`"
                "（需 8081/LLM，换版本用 `tools/llama_lora_up.py`）；或 "
                "`--answers <文件> --version <版本>` 离线评分。",
                "> 评测期兜底指向死端口：8081 挂了会抛错中止，"
                "**不会**静默换成 ollama 的 qwen（那会出假分）。",
                "> 主观听感/读感另记，不进此表。", ""]
        if env_block:
            head += [env_block, ""]
        head += ["（行序：最新在上）", "", _TABLE_HEAD, _TABLE_SEP]
        path.write_text("\n".join(head + [row]) + "\n", encoding="utf-8")
        return
    text = path.read_text(encoding="utf-8")
    if _TABLE_SEP in text:
        text = text.replace(_TABLE_SEP, _TABLE_SEP + "\n" + row, 1)
    else:  # 表格被删了/手改了 → 补回表头再追加
        text = text.rstrip("\n") + "\n\n" + _TABLE_HEAD + "\n" + _TABLE_SEP + "\n" + row + "\n"
    path.write_text(text, encoding="utf-8")


def render_detail(results: list[dict], summary: dict, version: str,
                  when: str, env: dict | None = None) -> str:
    lines = [f"# 人格回归明细（{when} · {version}）", "",
             f"- 合计：**{summary['ok']}/{summary['n']}"
             f"（{summary['accuracy']:.1%}）**",
             f"- 分项：" + "；".join(
                 f"{c} {d['ok']}/{d['n']}" for c, d in summary["by_cat"].items())]
    if env:
        lines += [f"- 模型服务：`{env.get('base_url', '')}`",
                  f"- 实际加载 LoRA：**{env.get('lora') or '(未取到)'}**"
                  + (f"（期望 {env['expect_lora']}）" if env.get("expect_lora") else "")]
    lines += ["", "| id | 类别 | 判定 | 说明 | 问题 |", "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {r['cat']} | {'✅' if r['ok'] else '❌'} | "
                     f"{r['detail']} | {r['q'][:40]} |")
    lines.append("")
    lines.append("## 答案摘要（失败项优先）")
    for r in sorted(results, key=lambda x: x["ok"]):
        tools = ",".join(r["tools"]) or "-"
        lines.append(f"- [{'✅' if r['ok'] else '❌'}] {r['id']} 工具={tools}："
                     f"{r['answer'][:150] or '(空)'}")
    return "\n".join(lines) + "\n"


def env_block_text(env: dict) -> str:
    """得分表用的运行环境说明（一行式，便于人读）。"""
    return (f"> 运行环境：服务 `{env.get('base_url', '')}`｜"
            f"实际 LoRA **{env.get('lora') or '(未取到)'}**｜"
            f"体检记录 {env.get('root', '')}｜策略 {env.get('policy_mode', 'legacy_unknown')}｜"
            f"仅历史评分；非生产验收；完整沙箱安全门仍须独立验证")


# ---------------- 真机跑（需 LLM）----------------
# 评测期允许的工具面（0502）：只读 + **已重定向到临时目录**的写类。
# 目的是让模型永远碰不到真会动手的能力——qq.shutdown 会真关链路、
# song_send 会真发 QQ；评测里出现一次就是事故。收窄沿用生产里
# public/casual 频道同一套 allowed_tools 机制（orchestrator 会拦执行）。
SAFE_EVAL_TOOLS = frozenset({
    # 只读（完整策略名册；实际 live 评测使用 LIVE_SAFE_TOOLS）
    "system_time", "web_search", "web_fetch", "memory_recall", "ledger_search",
    "kb_query", "diary_list", "file_list", "file_read", "skill_search",
    "memory_audit", "memory_why", "memory_profile", "memory_causal",
    # 写类：仅当目标已重定向到临时目录时才允许
    "memory_save", "diary_write", "task_plan", "schedule_plan", "kb_add",
})
# Live persona evidence must not read production ledger/files or external web.
# Keep the broad constant above for policy-manifest compatibility and tests.
LIVE_SAFE_TOOLS = frozenset({"system_time", "memory_recall", "kb_query", "diary_list",
                             "memory_save", "diary_write", "task_plan", "schedule_plan", "kb_add",
                             # R3(a, ledger 0607/0608): 沙箱化后的只读工具（file 根/台账/KB/web 均已隔离）
                             "file_read", "file_list", "ledger_search", "skill_search",
                             "web_search", "web_fetch"})
# 评测期禁止的兜底：8081 一旦不可用，绝不静默换成 ollama 的 qwen——
# 那会让分数变成"另一个模型的分数"却记在元亨头上。指向死端口 = 响亮失败。
DEAD_FALLBACK = "http://127.0.0.1:9/v1/chat/completions"


def _sandbox_writes(tmp: pathlib.Path) -> dict:
    """把可写目标重定向到临时目录，返回原值以便还原（同 sandbox_full）。

    覆盖：日记 / 任务表 / 计划表 / 知识库 / 认知待批队列 / 风格信号 /
    成长日志 / 通知守卫状态 / 向量库。成长日志是翻唱会话也在写的生产文档，
    向量库是我 0499 起 store_item 会写入的共享缓存——评测都不该碰。
    """
    import backend.growth_log as growth
    import backend.notify_guard as ng
    import backend.target_persona_loop as pl
    import backend.target_schedule as sched_mod
    import backend.target_scheduler_tools as st
    import backend.target_signals as sg
    import backend.vector_memory as vm
    import backend.yuanheng_kb as kb

    saved = {
        "DIARY_FILE": st.DIARY_FILE, "TASK_FILE": st.TASK_FILE,
        "SCHED_FILE": sched_mod.SCHED_FILE, "MIRROR_FILE": sched_mod.MIRROR_FILE,
        "KB_DB": kb.DEFAULT_KB_DB, "PENDING_FILE": pl.PENDING_FILE,
        "SIGNALS_FILE": sg.SIGNALS_FILE, "GROWTH_FILE": growth.GROWTH_FILE,
        "NG_STATE": ng.STATE_FILE, "VEC_DB": vm.VEC_DB,
    }
    st.DIARY_FILE = tmp / "diary.md"
    st.TASK_FILE = tmp / "task.md"
    sched_mod.SCHED_FILE = tmp / "sched.json"
    sched_mod.MIRROR_FILE = tmp / "plan.md"
    kb.DEFAULT_KB_DB = tmp / "yuanheng_kb.db"
    pl.PENDING_FILE = tmp / "cognition_pending.json"
    sg.SIGNALS_FILE = tmp / "cognition_signals.jsonl"
    growth.GROWTH_FILE = tmp / "成长日志.md"
    ng.STATE_FILE = tmp / "notify_guard.json"   # 决策日志同目录，一并隔离
    vm.VEC_DB = tmp / "embvec.db"
    # R3(a, ledger 0607): 只读工具的沙箱——文件根 + 台账都指向临时合成数据，
    # 使 file.read/file.list/ledger.search 可在隔离面下安全提供。
    import backend.target_access as ta

    fs_root = tmp / "fs"
    fs_root.mkdir(parents=True, exist_ok=True)
    (fs_root / "README.md").write_text(
        "# YHLZ · 元亨（评测合成 README）\n\n数字生命体，仅含合成内容。\n", encoding="utf-8")
    ledger_file = tmp / "上下文台账.md"
    ledger_file.write_text(
        "# 合成台账（评测沙箱）\n\n## 记录 0001：合成占位（评测用）\n- 内容：沙箱合成记录，无真实业务。\n",
        encoding="utf-8")
    saved["LEDGER"] = st.LEDGER
    saved["ALLOWED_ROOTS"] = ta.ALLOWED_ROOTS
    st.LEDGER = ledger_file
    ta.ALLOWED_ROOTS = [fs_root]
    # R3(a): web 桩——搜索走合成结果、fetch 只允许本机，隔离外网。
    import backend.search_crawler as sc

    saved["bing_search"] = sc.bing_search
    saved["WEB_ALLOWED_HOSTS"] = ta.WEB_ALLOWED_HOSTS

    def _stub_bing(q, limit=5):
        return [{"title": f"合成搜索结果：{q}", "url": "http://127.0.0.1/synthetic",
                 "snippet": "评测沙箱合成结果（非真实网络）。"}]

    sc.bing_search = _stub_bing
    ta.WEB_ALLOWED_HOSTS = {"127.0.0.1"}
    # T4(0630)：复盘 job 库也纳入沙箱（session 会连它，守卫要求沙箱路径）
    import backend.review_queue_store as rq

    saved["REVIEW_DB"] = rq.DEFAULT_DB
    rq.DEFAULT_DB = tmp / "review_jobs.db"
    return saved


def _restore_writes(saved: dict) -> None:
    import backend.growth_log as growth
    import backend.notify_guard as ng
    import backend.target_persona_loop as pl
    import backend.target_schedule as sched_mod
    import backend.target_scheduler_tools as st
    import backend.target_signals as sg
    import backend.vector_memory as vm
    import backend.yuanheng_kb as kb

    st.DIARY_FILE = saved["DIARY_FILE"]
    st.TASK_FILE = saved["TASK_FILE"]
    sched_mod.SCHED_FILE = saved["SCHED_FILE"]
    sched_mod.MIRROR_FILE = saved["MIRROR_FILE"]
    kb.DEFAULT_KB_DB = saved["KB_DB"]
    pl.PENDING_FILE = saved["PENDING_FILE"]
    sg.SIGNALS_FILE = saved["SIGNALS_FILE"]
    growth.GROWTH_FILE = saved["GROWTH_FILE"]
    ng.STATE_FILE = saved["NG_STATE"]
    vm.VEC_DB = saved["VEC_DB"]
    import backend.target_access as ta

    st.LEDGER = saved["LEDGER"]
    ta.ALLOWED_ROOTS = saved["ALLOWED_ROOTS"]
    import backend.search_crawler as sc

    sc.bing_search = saved["bing_search"]
    ta.WEB_ALLOWED_HOSTS = saved["WEB_ALLOWED_HOSTS"]
    import backend.review_queue_store as rq

    rq.DEFAULT_DB = saved["REVIEW_DB"]


def _kill_llm_fallback(dead_url: str = DEAD_FALLBACK) -> str:
    """把双轨兜底指到死端口，返回原值。任何主链失败都会抛错而非换模型。"""
    import backend.target_daemon as td

    old = td.LOCAL_BASE
    td.LOCAL_BASE = dead_url
    return old


def running_lora(base_url: str = "http://127.0.0.1:8081/v1/chat/completions") -> str:
    """Endpoint-bound startup declaration; not proof of live adapter state."""
    from tools.persona_live_safety import endpoint_process_evidence
    try:
        return endpoint_process_evidence(base_url)["lora"]
    except Exception:
        return ""


def preflight(base_url: str) -> dict:
    """跑前体检：/health + /v1/models，返回证据 dict；不通过直接抛 RuntimeError。"""
    import urllib.parse
    import urllib.request

    from tools.persona_live_safety import local_endpoint
    spec = local_endpoint(base_url)
    root = spec["root"]
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise RuntimeError("评测体检禁止重定向")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    ev: dict = {"base_url": base_url, "root": root}
    for label, path in (("health", "/health"), ("models", "/v1/models")):
        try:
            with opener.open(root + path, timeout=8) as r:
                body = r.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"体检失败：{root}{path} 不可达（{type(exc).__name__}）"
                f"——本地模型服务没起来，评测中止（不出一行假分）") from exc
        ev[label] = body[:400]
        if label == "health":
            try:
                if str(json.loads(body).get("status", "")).lower() != "ok":
                    raise RuntimeError(f"体检失败：/health 非 ok：{body[:200]}")
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"体检失败：/health 非 JSON：{body[:200]}") from exc
    return ev


def _is_infra_error(exc: BaseException) -> bool:
    """连接/超时一类的基础设施错误（不是人格失败），出现即中止整轮。"""
    name = type(exc).__name__
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    return name in ("ConnectError", "ConnectTimeout", "ReadTimeout",
                    "ReadError", "RemoteProtocolError", "PoolTimeout",
                    "RuntimeError")


async def run_live(bank: list[dict], *, base_url: str,
                   expect_lora: str = "", policy_mode: str = "production") -> tuple[list[dict], dict]:
    """真机跑。返回 (逐题结果, 运行环境证据)。

    三层保护：体检（打不通就不跑）→ LoRA 校验（版本不对就不跑）→
    兜底指向死端口（8081 中途挂了就抛错，绝不静默换模型）。
    """
    from backend.env_loader import ensure_env_loaded

    # Do not load production .env into an evaluation worker.
    from backend.target_entry import ConversationSession
    from backend.target_kw_index import KeywordIndex
    from backend.target_memory import TargetMemoryService

    if policy_mode not in POLICY_MODES:
        raise ValueError("unknown evaluation policy mode")
    env = preflight(base_url)
    env.update(policy_mode=policy_mode, production_validation=False,
               acceptance=False, inference_requests=[])
    from tools.persona_live_safety import endpoint_process_evidence, adapter_api_evidence
    env["endpoint_process"] = endpoint_process_evidence(base_url)
    env["lora"] = env["endpoint_process"]["lora"]
    env["effective_model"] = env["lora"] or "unknown"   # 0622 §3.1：不能凭文件名定版本
    env["expect_lora"] = expect_lora
    if expect_lora and env["lora"] != expect_lora:
        raise RuntimeError(
            f"LoRA 不符：期望 {expect_lora}，实际 {env['lora'] or '(未取到)'}"
            f"——拒绝出分（换版本要用 tools/llama_lora_up.py）")

    env["adapter_api"] = adapter_api_evidence(base_url, env["lora"])

    async def _approve(_info: dict) -> bool:
        return True  # 评测沙箱：放行写入（目标已被重定向到临时目录）

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="yhlz_persona_"))
    saved = _sandbox_writes(tmp)
    fallback_saved = _kill_llm_fallback()
    out: list[dict] = []
    from tools.persona_live_safety import IsolatedRuntime
    runtime = IsolatedRuntime(tmp, base_url)
    try:
        async with runtime:
            evaluation_task = asyncio.current_task()
            for entry in bank:
                mem = TargetMemoryService(db_path=tmp / f"{entry['id']}.db",
                                          kw_index=KeywordIndex(tmp / f"{entry['id']}_k.db"))
                # 与 tools/memory_eval.py 同口径：评测摄入不触发裁决/因果副作用
                mem._auto_adjudicate = lambda item: None  # type: ignore[method-assign]
                mem._auto_link_causal = lambda item: None  # type: ignore[method-assign]
                # Bind the endpoint that was actually preflighted, not the hardcoded
                # default in ConversationSession. Keep production text-mode settings.
                from backend.target_orchestrator import build_openai_compatible_llm_turn
                work = not entry.get("public") and ConversationSession._want_text_work_mode(entry["q"])
                provider = build_openai_compatible_llm_turn(
                    base_url=base_url, api_key="", model="gemma-4-e4b",
                    temperature=0.2, max_tokens=3000 if work else 800,
                    reasoning_effort="medium" if work else "none",
                    fallback_base_url=None, fallback_model=None)
                question_id = entry["id"]

                async def observed(messages, schemas):
                    if asyncio.current_task() is not evaluation_task:
                        runtime.guard.violations.append("background_inference")
                        raise RuntimeError("人格评测禁止后台隐式模型调用")
                    # Hash, don't dump, potentially sensitive runtime context.
                    env["inference_requests"].append({
                        "id": question_id, "schema_sha256": digest(schemas),
                        "system_sha256": digest([m for m in messages if m.get("role") == "system"]),
                        "offered_tools": [t.get("function", {}).get("name") for t in schemas]})
                    return await provider(messages, schemas)

                sess = ConversationSession(
                    memory=mem, approver=_approve, max_tool_rounds=2,
                    llm_turn=observed,
                    channel="grp-eval" if entry.get("public") else "private")
                from tools.persona_effect_evidence import FixtureEffects
                effects = FixtureEffects(tmp, mem)
                effects.bind(sess.registry)
                tool_observations = []
                original_execute = sess.registry.execute_openai_async
                async def observe_execute(name, arguments):
                    result = await original_execute(name, arguments)
                    # 0646：None 才视为无输出；空列表保留为 "[]"（0639 的
                    # `or ""` 会把 kb.query 空结果折叠成空串，掩盖空命中）。
                    raw_output = result.get("output")
                    output = "" if raw_output is None else str(raw_output)
                    anchors = turn_entry.get("expected_read_anchors", [])
                    tool_observations.append({"name": name, "ok": bool(result.get("ok")),
                        "arguments_sha256": digest(arguments),
                        "arguments_head": str(arguments)[:200],  # 0646：实参定性
                        "output_sha256": digest(output),
                        "output_head": output[:120],   # 0639：限长诊断（t09 定性用）
                        "error_code": str(result.get("error") or "").split(":", 1)[0][:64],
                        "expected_anchors": {anchor: anchor in output for anchor in anchors}})
                    return result
                sess.registry.execute_openai_async = observe_execute
                policy_trace = []
                sess._tool_policy = constrained_policy(  # type: ignore[method-assign]
                    sess._tool_policy, LIVE_SAFE_TOOLS, mode=policy_mode,
                    observations=policy_trace)
                turns = [entry] + [{**entry, **followup} for followup in entry.get("followups", [])]
                for turn_index, turn_entry in enumerate(turns):
                    question_id = turn_entry['id']
                    effect_offset, policy_offset = len(effects.receipts), len(policy_trace)
                    observation_offset = len(tool_observations)
                    work = not entry.get('public') and ConversationSession._want_text_work_mode(turn_entry['q'])
                    provider = build_openai_compatible_llm_turn(
                        base_url=base_url, api_key="", model="gemma-4-e4b",
                        temperature=0.2, max_tokens=3000 if work else 800,
                        reasoning_effort="medium" if work else "none",
                        fallback_base_url=None, fallback_model=None)
                    try:
                        info = await sess.run_turn(turn_entry["q"])
                    except Exception as exc:  # noqa: BLE001
                        if _is_infra_error(exc):
                            raise RuntimeError(
                                f"基础设施错误（{type(exc).__name__}: {exc}）出现在 "
                                f"{turn_entry['id']}，已中止本轮——这是环境问题不是人格问题，"
                                f"不出分") from exc
                        raise
                    tools = [str(u.get("name")) for u in (info.get("tool_uses") or [])]
                    rec = {"id": turn_entry["id"], "cat": turn_entry["cat"], "q": turn_entry["q"],
                           "tools": tools, "answer": str(info.get("answer") or ""),
                           "effect_receipts": effects.receipts[effect_offset:],
                           "tool_evidence_status": info.get("tool_evidence_status", ""),
                           "tool_observations": tool_observations[observation_offset:],
                           "source_id": entry.get("source_id", entry["id"]),
                           "tool_trace": bounded_tool_trace(info.get("tool_uses")),
                           "policy_trace": policy_trace[policy_offset:],
                           "dev_handoff_status": str(info.get("dev_handoff_status") or "")[:64]}
                    expected_effect = turn_entry.get("expected_effect")
                    if expected_effect:
                        if expected_effect["name"] in ('memory.save', 'kb.add'):
                            params = expected_effect['params']
                            rec['requested_effect_readback'] = effects.check_requested_content(
                                expected_effect['name'], params.get('content', params.get('summary','')))
                        else:
                            rec["requested_effect_readback"] = effects._snapshot(
                                expected_effect["name"], expected_effect["params"])
                    rec["execution_assessment"] = tool_execution_assessment(turn_entry, rec)
                    ok, detail = verify(turn_entry, rec["answer"], tools)
                    print(f"{'PASS' if ok else 'FAIL'} {turn_entry['id']} | {detail} | "
                          f"{rec['answer'][:70]}")
                    out.append(rec)
    finally:
        # A non-cooperative background writer must never see restored globals.
        if runtime.guard is not None and runtime.guard.active:
            raise RuntimeError("评测任务尚未排空；保持隔离路径，必须退出专用进程")
        _restore_writes(saved)
        import backend.target_daemon as td

        td.LOCAL_BASE = fallback_saved
    final_identity = endpoint_process_evidence(base_url)
    final_adapter = adapter_api_evidence(base_url, env["lora"])
    if final_identity != env["endpoint_process"] or final_adapter != env["adapter_api"]:
        raise RuntimeError("模型监听进程在评测期间发生变化；不出分")
    env["isolation"] = {
        "scope": "python_process_guard_not_os_sandbox",
        "data": "empty_fixtures_no_private_persona_or_style",
        "guard_violations": runtime.guard.violations,
        "cancelled_background_tasks": runtime.cancelled_tasks,
        "tools": sorted(LIVE_SAFE_TOOLS),
        "external_tools_validated": False,
    }
    env["questions"] = len(out)
    return out, env


def dump_questions(path: pathlib.Path, bank: list[dict], version: str) -> None:
    payload = {"version": version, "note": "填 answer（与 tools，如 memory_save）；"
                                          "可只填部分题，未作答记失败",
               "items": [{"id": e["id"], "cat": e["cat"], "q": e["q"],
                          "answer": "", "tools": []} for e in bank]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"模板 -> {path}")


def save_answers(path: pathlib.Path, results: list[dict], version: str,
                 env: dict | None = None) -> None:
    """把真机跑到的**原始答案**存盘（0503）。

    格式与 `--dump` 一致，因此能直接喂回 `--answers` 离线复判——
    这是"测量/判定分离"：改判定规则不必再占一次 GPU。
    """
    payload = {
        "version": version,
        "note": "真机原始答案存档；用 tools/persona_regression.py "
                "--answers <本文件> 离线复判",
        "env": env or {},
        "items": [{"id": r["id"], "cat": r.get("cat", ""), "q": r.get("q", ""),
                   "answer": r.get("answer", ""), "tools": r.get("tools", []),
                   "tool_trace": r.get("tool_trace", []),
                   "source_id": r.get("source_id", r["id"]),
                   "effect_receipts": r.get("effect_receipts", []),
                   "tool_evidence_status": r.get("tool_evidence_status", ""),
                   "tool_observations": r.get("tool_observations", []),
                   "requested_effect_readback": r.get("requested_effect_readback"),
                   "policy_trace": r.get("policy_trace", []),
                   "dev_handoff_status": r.get("dev_handoff_status", ""),
                   "execution_assessment": r.get("execution_assessment", {})}
                  for r in results],
    }
    write_new_json(path, payload)
    print(f"原始答案已存档 -> {path}")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="真机跑（需 8081/LLM，占 GPU）")
    ap.add_argument("--answers", default="", help="离线评分：作答 JSON")
    ap.add_argument("--dump", default="", help="导出作答模板 JSON")
    ap.add_argument("--version", default="", help="版本标签（如 v7b）")
    ap.add_argument("--base-url",
                    default="http://127.0.0.1:8081/v1/chat/completions",
                    help="本地模型服务地址（默认生产 8081）")
    ap.add_argument("--expect-lora", default="",
                    help="期望 llama-server 实际加载的 LoRA 文件名（如 "
                         "yuanheng-v7b-lora.gguf）；不符则拒绝出分")
    ap.add_argument("--only", default="", choices=("",) + CATEGORIES)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="",
                    help="只跑指定题号（逗号分隔，如 t08,t09）；仅诊断用，不作验收")
    ap.add_argument("--out", default="", help="得分表路径（默认 docs/报告/人格回归基线.md）")
    ap.add_argument("--save-answers", default="",
                    help="真机跑时把原始答案存档到该路径（可被 --answers 复判）")
    ap.add_argument("--policy-mode", choices=POLICY_MODES, default="production",
                    help="production=真实策略交集；diagnostic=仅owner文字诊断，不作验收")
    args = ap.parse_args(argv)
    if args.live and args.save_answers and pathlib.Path(args.save_answers).exists():
        ap.error("--save-answers 文件已存在；请换新路径，禁止覆盖原始证据")
    run_id = new_run_id()

    bank = _filter(PERSONA_BANK, args.only, args.limit)
    if args.ids:
        wanted = {x.strip() for x in str(args.ids).split(",") if x.strip()}
        bank = [e for e in bank if e["id"] in wanted]
        if not bank:
            ap.error("--ids 未匹配任何题号")
    version = args.version or "未标注"
    if args.dump:
        dump_questions(pathlib.Path(args.dump), bank, version)
        return 0
    if not args.live and not args.answers:
        ap.error("至少给一个模式：--live / --answers / --dump")

    env: dict | None = None
    if args.live:
        try:
            answers, env = asyncio.run(run_live(
                bank, base_url=args.base_url, expect_lora=args.expect_lora,
                policy_mode=args.policy_mode))
            env["run_id"] = run_id
        except RuntimeError as exc:   # 体检/LoRA 不符/infra 错误 → 不出分
            print(f"[中止] {exc}", file=sys.stderr)
            return 2
        if args.save_answers:
            save_answers(pathlib.Path(args.save_answers), answers, version, env)
    else:
        data = json.loads(pathlib.Path(args.answers).read_text(encoding="utf-8"))
        items = data.get("items") if isinstance(data, dict) else data
        answers = list(items or [])
        env = data.get("env", {}) if isinstance(data, dict) else {}
        version = args.version or str(
            (data.get("version") if isinstance(data, dict) else "") or version)

    results = score_items(bank, answers)
    summary = summarize(results)
    when = time.strftime("%Y-%m-%d %H:%M")
    source_policy = (env or {}).get("policy_mode", "legacy_unknown")
    note = f"旧规则 {summary['ok']}/{summary['n']}；{source_policy}；非完整验收；{run_id}"
    row = ("| " + when + " | " + version + " | "
           + " | ".join(f"{d['ok']}/{d['n']}" for d in summary["by_cat"].values())
           + f" | {summary['accuracy']:.1%} | {note} |")
    append_score_row(pathlib.Path(args.out) if args.out else BASELINE_FILE, row,
                     env_block=env_block_text(env) if env else "")

    report_dir = pathlib.Path(args.out).parent if args.out else BASELINE_FILE.parent
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"人格回归明细_{safe_label(version)}_{run_id}"
    detail = report_dir / (stem + ".md")
    manifest = build_manifest(_ROOT, bank, run_id=run_id,
                              mode="live" if args.live else "offline_rescore",
                              source_env=env)
    manifest["legacy_summary"] = summary
    by_id = {a.get("id"): a for a in answers}
    manifest["execution_assessments"] = [
        {"id": e["id"], **tool_execution_assessment(e, by_id.get(e["id"], {}))}
        for e in bank]
    manifest["semantic_review"] = review_checklist(bank, answers)
    if args.answers:
        manifest["source_answers_sha256"] = __import__("hashlib").sha256(
            pathlib.Path(args.answers).read_bytes()).hexdigest()
    write_new_json(report_dir / (stem + ".json"), manifest)
    with detail.open("x", encoding="utf-8") as f:
        f.write(render_detail(results, summary, version, when, env))
        f.write(f"\n## 证据边界\n\n运行 `{run_id}`；工具策略 `{source_policy}`。"
                "以上为历史关键词/工具名评分，不是完整验收。执行证据与语义待复核清单见同名JSON；"
                "执行ok不代表写入效果已读回，diagnostic不能用于生产权限验收。\n")
    print(json.dumps({"version": version, "n": summary["n"], "ok": summary["ok"],
                      "accuracy": round(summary["accuracy"], 4),
                      "run_id": run_id, "acceptance": False,
                      "lora": (env or {}).get("lora", ""),
                      "by_cat": summary["by_cat"]}, ensure_ascii=False))
    print(f"得分表已追加；明细 -> {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())