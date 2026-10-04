"""scorer_v2/v3（R3 包B+T1, 2026-10-03/04）：判分与工具事实分离。

- 旧分（persona_bank.verify 关键词命中）保留为历史可比项，不覆盖。
- v3 `classify_result` 用**结构化证据**：policy_trace.allowed_tools / tool_observations /
  effect_receipts / tool_evidence_status / execution_assessment / tool_trace。
- 关键新增：`not_offerable_in_harness` —— 期望工具**不在本轮 allowed_tools** 时，
  该题在本评测面下**结构上不可通过**（是评测面缺口，不是模型失败）。
不调用模型；只对既有原始答案离线重判。
"""
from __future__ import annotations

import re
import sys

sys.path.insert(0, ".")

import tools.persona_bank as pb  # noqa: E402

UNAVAILABLE_RE = re.compile(r"没有可用|工具不可用|没有(?:读取|联网|台账|文件|技能库|检索)?工具")
NORECORD_RE = re.compile(r"查无|未找到|没有找到|没有记录|没查到|查不到|没有这条|无匹配|是空的|没有关于")
FAILED_RE = re.compile(r"失败了|执行失败|报错|验证失败|索引没走通")

READ_TOOLS = {"ledger_search", "ledger_get", "ledger_list", "file_read", "file_list",
              "web_search", "web_fetch", "skill_search", "kb_query", "memory_recall",
              "memory_audit", "memory_why", "memory_profile", "memory_causal", "diary_list",
              "system_time"}
WRITE_TOOLS = {"memory_save", "diary_write", "task_plan", "schedule_plan", "kb_add"}


def allowed_tools_of(rec: dict) -> set:
    allowed = set()
    for pt in (rec.get("policy_trace") or []):
        allowed |= set(pt.get("allowed_tools") or [])
    return allowed


def classify_result(entry: dict, rec: dict) -> dict:
    """结构化四/八分类（T1）。rec 为带证据字段的逐题结果。"""
    want = set(entry.get("expect_any_tool") or [])
    allowed = allowed_tools_of(rec)
    tools = [t for t in (rec.get("tools") or [])]
    obs = rec.get("tool_observations") or []
    receipts = rec.get("effect_receipts") or []
    ev = str(rec.get("tool_evidence_status") or "")
    ea = rec.get("execution_assessment") or {}
    base = {"id": rec.get("id"), "expect": sorted(want), "allowed": sorted(allowed),
            "tools": tools, "evidence_status": ev,
            "assessment": ea.get("status"), "assessment_reason": ea.get("reason")}

    # 1) 期望工具不在本评测面 → 结构性不可通过（评测缺口）
    if want and allowed and not (want & allowed):
        return {**base, "class": "not_offerable_in_harness",
                "detail": "期望工具不在 allowed_tools（评测面缺口，非模型失败）"}
    # 2) 工具已调用
    if tools:
        oks = [o for o in obs if o.get("name") in (want or set(tools))]
        all_ok = bool(oks) and all(o.get("ok") for o in oks) if oks else None
        if oks and not all_ok:
            return {**base, "class": "execution_failed", "detail": "调用返回失败"}
        if want & WRITE_TOOLS or set(tools) & WRITE_TOOLS:
            rb = [r.get("status") for r in receipts]
            if any(s == "verified_in_fixture" for s in rb):
                return {**base, "class": "write_created_verified", "detail": "载体读回一致"}
            if any(s in ("already_present_in_fixture",) for s in rb):
                return {**base, "class": "write_existing_verified", "detail": "幂等已有记录"}
            if rb:
                return {**base, "class": "effect_unknown", "detail": f"receipts={rb}"}
            return {**base, "class": "effect_unknown", "detail": "写类无读回收据"}
        return {**base, "class": "read_hit", "detail": "读类工具已调用"}
    # 3) 未调用
    if ev == "unavailable" or any(UNAVAILABLE_RE.search(str(rec.get("answer") or ""))):
        return {**base, "class": "unavailable_not_checked", "detail": "未调（工具/面不可用）"}
    if ev == "not_executed" or ea.get("reason") == "required_tool_not_attempted":
        return {**base, "class": "not_executed", "detail": "未按要求调用"}
    return {**base, "class": "unsupported_evidence", "detail": "缺调用且无足够证据"}


def classify_tool_item(entry: dict, tools: list, answer: str) -> dict:
    """旧版（仅 tools+answer），保留作历史比对。"""
    want = set(entry.get("expect_any_tool") or [])
    a = str(answer or "")
    called = [t for t in (tools or []) if (not want or t in want)]
    base = {"id": entry.get("id"), "expect": sorted(want), "tools": list(tools or []),
            "tool_selected": bool(called)}
    if called:
        return {**base, "class": "1_retrieved", "detail": "工具已调用"}
    if UNAVAILABLE_RE.search(a):
        return {**base, "class": "3_unavailable_not_checked", "detail": "工具不可用未查"}
    if FAILED_RE.search(a):
        return {**base, "class": "4_failed_unconfirmed", "detail": "失败未确认"}
    return {**base, "class": "4_not_confirmed", "detail": "未调用期望工具"}


def score_round(payload: dict) -> dict:
    """对 persona_regression round 文件（含结构化字段）做 v3 分类。"""
    bank = {e["id"]: e for e in pb.PERSONA_BANK}
    rows = []
    for rec in payload.get("results", []):
        e = bank.get(rec.get("id"))
        if not e or not e.get("expect_any_tool"):
            continue
        rows.append(classify_result(e, rec))
    return {"n": len(rows), "rows": rows}


def score(payload: dict) -> dict:
    """兼容旧接口（answers 文件）。"""
    bank = {e["id"]: e for e in pb.PERSONA_BANK}
    rows = []
    old_ok = 0
    for it in payload.get("items", []):
        e = bank.get(it.get("id"))
        if not e:
            continue
        ok_old, _ = pb.verify(e, it.get("answer", ""), it.get("tools") or [])
        old_ok += 1 if ok_old else 0
        if it.get("cat") == "tool" or str(it.get("id", "")).startswith("t"):
            if not e.get("expect_any_tool"):
                continue
            rows.append(classify_tool_item(e, it.get("tools") or [], it.get("answer", "")))
    return {"n": len(payload.get("items", [])), "old_keyword_ok": old_ok, "tool_items": rows}


if __name__ == "__main__":
    import json

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for path in sys.argv[1:]:
        d = json.load(open(path, encoding="utf-8"))
        if "results" in d and d["results"] and "policy_trace" in d["results"][0]:
            r = score_round(d)
            print(f"\n=== {path}（v3 结构化）===")
            for t in r["rows"]:
                print(f"  {t['id']}: {t['class']} | {t['detail']}")
        else:
            r = score(d)
            print(f"\n=== {path}（旧接口）旧分 {r['old_keyword_ok']}/{r['n']} ===")
            for t in r["tool_items"]:
                print(f"  {t['id']}: {t['class']}")
