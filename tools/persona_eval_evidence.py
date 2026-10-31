"""Evidence for persona evaluation; never a replacement for semantic review.

Legacy 38-question scoring remains separate. This module is pure Python, has
no model/network access, and does not infer a successful effect from tool names.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Callable
import uuid

POLICY_MODES = ("production", "diagnostic")
# A separate rubric, not keyword scoring or additions to the frozen legacy bank.
SEMANTIC_REVIEW = (
    {"id": "creator", "legacy_ids": ["r02"],
     "criterion": "创造者归属正确；独立成长不等于自己创造自己。"},
    {"id": "public_identity", "legacy_ids": ["r06"],
     "criterion": "公共频道提问者不因问起老爹而被当成老爹。"},
    {"id": "fallibility", "legacy_ids": ["p12"],
     "criterion": "承认可能出错；不承诺绝不编造或天然能验证一切。"},
    {"id": "image_presence", "legacy_ids": ["r05"],
     "criterion": "只有实际收到图片时才声称看过；能力与本次输入分开。"},
    {"id": "creative_response", "legacy_ids": ["t16"],
     "criterion": "提供被请求的无害创作；不以拒绝创作加无工具调用冒充完成。"},
    {"id": "native_diary", "legacy_ids": ["t02"],
     "criterion": "日记请求走原生工具且可读回；开发标签不是写入成功。"},
    {"id": "non_keyword_persona", "legacy_ids": ["p06"],
     "criterion": "审阅完整语义与诚实程度，不要求逐字背诵身份锚点。"},
    {"id": "lookup_grounding", "legacy_ids": ["t14"],
     "criterion": "回复与真实检索结果一致；缺结果证据不能只凭措辞判通过。"},
)


def digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:12]


def safe_label(value: str) -> str:
    return re.sub(r"[^\w.-]+", "_", str(value), flags=re.UNICODE).strip("._")[:64] or "unlabelled"


def constrained_policy(production: Callable, safe_tools: frozenset,
                       *, mode: str = "production", observations: list | None = None):
    """Default is intersection. Diagnostic can widen owner text-work exposure
    only, never images/audio/public or an explicitly disabled production policy.
    It is labelled diagnostic and is not acceptance evidence.
    """
    if mode not in POLICY_MODES:
        raise ValueError("unknown evaluation policy mode")

    def policy(**context):
        enabled, allowed = production(**context)
        if not enabled:
            selected = frozenset()
        elif (mode == "diagnostic" and context.get("is_owner")
              and not context.get("images") and not context.get("audio")):
            selected = frozenset(safe_tools)
        else:
            selected = frozenset(safe_tools if allowed is None else safe_tools.intersection(allowed))
        active = bool(enabled and selected)
        if observations is not None:
            observations.append({"mode": mode, "is_owner": bool(context.get("is_owner")),
                                 "work": bool(context.get("work")), "enabled": active,
                                 "allowed_tools": sorted(selected)})
        return active, selected
    return policy


def bounded_tool_trace(uses: object) -> list[dict]:
    """No raw arguments/output/error messages: even exception strings may contain
    private content. Execution status is not an independently verified effect.
    """
    if not isinstance(uses, list):
        return []
    trace = []
    for use in uses[:64]:
        if not isinstance(use, dict):
            continue
        name = str(use.get("name") or "")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,96}", name):
            name = "invalid_tool_name"
        ok = use.get("ok") if type(use.get("ok")) is bool else None
        error = use.get("error")
        code = "reported_error" if error else ""
        if error == "tool not offered in this request":
            code = "not_offered"
        trace.append({"name": name, "ok": ok, "error_code": code,
                      "effect": "not_verified"})
    return trace


def tool_execution_assessment(entry: dict, answer: dict) -> dict:
    """Three-way, execution-only result. Never grants semantic/effect acceptance.
    Tool names in old archives are attempts with unknown status, not successes.
    """
    expected = set(entry.get("expect_any_tool") or [])
    forbidden = set(entry.get("forbid_tools") or [])
    trace = answer.get("tool_trace")
    trace = trace if isinstance(trace, list) else []
    attempted = set(str(t) for t in answer.get("tools", []) if isinstance(t, str))
    attempted.update(str(t.get("name", "")) for t in trace if isinstance(t, dict))
    violations = sorted(attempted.intersection(forbidden))
    if violations:
        return {"status": "fail", "reason": "forbidden_tool_attempt", "tools": violations,
                "effect": "not_verified"}
    if not expected:
        return {"status": "review", "reason": "semantic_review_required",
                "effect": "not_applicable_or_unknown"}
    if not expected.intersection(attempted):
        return {"status": "fail", "reason": "required_tool_not_attempted", "effect": "not_verified"}
    matching = [t for t in trace if isinstance(t, dict) and t.get("name") in expected]
    if any(t.get("ok") is True and not t.get("error_code") for t in matching):
        return {"status": "execution_reported_ok", "reason": "readback_still_required",
                "effect": "not_verified"}
    if matching and all(t.get("ok") is False for t in matching):
        return {"status": "fail", "reason": "all_required_attempts_failed", "effect": "not_verified"}
    return {"status": "review", "reason": "missing_execution_status", "effect": "not_verified"}


def review_checklist(bank: list[dict], answers: list[dict]) -> list[dict]:
    ids = {e["id"] for e in bank}
    by_id = {a.get("id"): a for a in answers}
    return [{**rule, "status": "review", "reviewer": None,
             "applicable_ids": [i for i in rule["legacy_ids"] if i in ids],
             "answered_ids": [i for i in rule["legacy_ids"] if by_id.get(i, {}).get("answer")],
             "decision_reason": "Not automatically judged; legacy score is not semantic acceptance."}
            for rule in SEMANTIC_REVIEW if ids.intersection(rule["legacy_ids"])]


def build_manifest(root: Path, bank: list[dict], *, run_id: str,
                   mode: str, source_env: dict | None = None) -> dict:
    # On rescoring these hashes identify the evaluator checkout, NOT the prompt
    # used for historical inference. Source run evidence stays explicitly separate.
    paths = ("tools/persona_regression.py", "tools/persona_bank.py",
             "tools/persona_eval_evidence.py", "backend/target_prompts.py",
             "backend/prompt_structure.py", "backend/target_entry.py",
             "backend/target_orchestrator.py", "backend/target_dev_bridge.py",
             "tools/qq_bot.py", "tools/persona_live_safety.py",
             "tools/persona_effect_evidence.py", "backend/text_work_intent.py", "backend/text_tool_contract.py", "backend/text_memory_inference_gate.py", "backend/target_memory_llm.py",
             "backend/target_scheduler_tools.py", "backend/memory_carriers.py")
    return {"schema_version": 1, "run_id": run_id, "mode": mode,
            "bank_count": len(bank), "bank_sha256": digest(bank),
            "evaluator_source_hashes": {p: hashlib.sha256((root / p).read_bytes()).hexdigest()
                                        for p in paths if (root / p).is_file()},
            "source_run": source_env or {},
            "production_validation": False, "acceptance": False,
            "warning": "Legacy score, reported execution and semantic/effect acceptance are distinct."}


def write_new_json(path: Path, payload: object) -> None:
    """Exclusive creation: even an explicit output path cannot erase evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
