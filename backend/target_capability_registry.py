"""Capability Registry + gated execution (ADR-007, draft approved for dev).

Capabilities are WHAT the system can do; they are the only surface the LLM
can perceive (whitelist).  Control-plane policies (constitution / governance /
permission / verification) are registered separately as gates and are NEVER
exported as tool calls — the agent cannot decide whether to obey them.

Execution pipeline: can_execute (policies, fail-closed) -> execute (missing
input / timeout / rollback).  All metadata per ADR-007 §4.
"""

from __future__ import annotations

import inspect
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

Handler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    handler: Handler
    input: tuple[str, ...] = ()
    optional_input: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    side_effect: bool = False
    risk: str = "low"
    timeout_ms: int = 4000
    priority: int = 50
    rollback: Optional[Callable[[], Any]] = None
    verify: Optional[Callable[[Any], bool]] = None
    input_model: Any = None  # optional pydantic BaseModel: typed arg contract (R1)

    @property
    def all_inputs(self) -> tuple[str, ...]:
        return self.input + self.optional_input

    @property
    def openai_name(self) -> str:
        """OpenAI/DeepSeek tool name (no dots allowed): domain.verb -> domain_verb."""
        return self.name.replace(".", "_")

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.name or "." not in self.name:
            raise ValueError(f"capability name must be 'domain.verb': {self.name!r}")
        if self.risk not in ("low", "medium", "high"):
            raise ValueError(f"invalid risk: {self.risk}")
        if int(self.timeout_ms) <= 0:
            raise ValueError("timeout_ms must be > 0")
        overlap = set(self.input) & set(self.optional_input)
        if overlap:
            raise ValueError(f"input overlap: {sorted(overlap)}")
        if self.risk == "high" and not self.requires:
            raise ValueError("high-risk capability must declare an approval policy in requires")
        if self.input_model is not None:
            base = getattr(self.input_model, "__mro__", ())
            from pydantic import BaseModel

            if BaseModel not in base:
                raise ValueError("input_model must be a pydantic BaseModel subclass")

    def to_openai_tool(self) -> dict:
        self.validate()
        if self.input_model is not None:
            schema = self.input_model.model_json_schema()
            props = {k: v for k, v in schema.get("properties", {}).items()}
            required = list(schema.get("required", []) or [])
        else:
            props: dict[str, Any] = {}
            for arg in self.all_inputs:
                props[arg] = {"type": "string", "description": arg}
            required = list(self.input)
        return {
            "type": "function",
            "function": {
                "name": self.openai_name,
                "description": ("写入/有副作用的能力" if self.side_effect
                                else "只读能力"),
                "parameters": {"type": "object", "properties": props,
                               "required": required},
            },
        }


class CapabilityRegistry:
    """Thread-safe whitelist of capabilities + control-plane policy gates."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._caps: dict[str, Capability] = {}
        self._policies: dict[str, Callable[[], bool]] = {}
        self._grants: dict[str, int] = {}
        self._commit_hook: Optional[Callable[[dict[str, Any]], None]] = None

    def set_commit_hook(self, hook: Optional[Callable[[dict[str, Any]], None]]) -> None:
        """Called on every successful (verified) execution: Event-Bus commit."""
        self._commit_hook = hook

    def _emit_commit(self, record: dict[str, Any]) -> None:
        hook = self._commit_hook
        if hook is not None:
            try:
                hook(dict(record))
            except Exception:
                pass

    # ---------- registration ----------
    def register_capability(self, cap: Capability, *, override: bool = False) -> None:
        cap.validate()
        with self._lock:
            if cap.name in self._caps and not override:
                raise ValueError(f"capability already registered: {cap.name}")
            self._caps[cap.name] = cap

    def register_policy(self, name: str, check: Callable[[], bool]) -> None:
        """Control-plane gate; never exported as a tool."""
        with self._lock:
            self._policies[str(name)] = check

    def grant_policy_once(self, name: str) -> None:
        """One-shot approval grant (approver path); consumed at next check."""
        with self._lock:
            self._grants[str(name)] = self._grants.get(str(name), 0) + 1

    def unregister_capability(self, name: str) -> None:
        with self._lock:
            self._caps.pop(name, None)

    # ---------- query ----------
    def get(self, name: str) -> Optional[Capability]:
        with self._lock:
            return self._caps.get(name)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._caps)

    def get_policy(self, name: str) -> Optional[Callable[[], bool]]:
        with self._lock:
            return self._policies.get(name)

    def export_openai_tools(self) -> list[dict]:
        with self._lock:
            return [c.to_openai_tool() for c in self._caps.values()]

    def get_by_openai_name(self, openai_name: str) -> Optional[Capability]:
        """Reverse-map an exposed (underscored) tool name to its capability."""
        with self._lock:
            for cap in self._caps.values():
                if cap.openai_name == openai_name:
                    return cap
        return None

    def execute_openai(self, openai_name: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Execute via the exposed tool name (LLM-facing)."""
        cap = self.get_by_openai_name(str(openai_name))
        if cap is None:
            return {"ok": False, "error": "unknown capability", "name": openai_name}
        return self.execute(cap.name, params)

    # ---------- gated execution ----------
    def can_execute(self, name: str) -> tuple[bool, str]:
        """Read-only gate query (grants are NOT consumed here)."""
        cap = self.get(name)
        if cap is None:
            return False, "unknown capability"
        for req_id in cap.requires:
            if self._grants.get(req_id, 0) > 0:
                continue
            check = self._policies.get(req_id)
            if check is None:
                return False, f"policy not registered (fail-closed): {req_id}"
            try:
                if not check():
                    return False, f"policy denied: {req_id}"
            except Exception:
                return False, f"policy error: {req_id}"
        return True, ""

    def _check_for_execute(self, name: str) -> tuple[bool, str]:
        """Execution gate: consumes one-shot grants, then policy checks."""
        cap = self.get(name)
        if cap is None:
            return False, "unknown capability"
        for req_id in cap.requires:
            with self._lock:
                if self._grants.get(req_id, 0) > 0:
                    self._grants[req_id] -= 1
                    continue
            check = self._policies.get(req_id)
            if check is None:
                return False, f"policy not registered (fail-closed): {req_id}"
            try:
                if not check():
                    return False, f"policy denied: {req_id}"
            except Exception:
                return False, f"policy error: {req_id}"
        return True, ""

    async def execute_async(self, name: str,
                            params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Async execution path (await async handlers). Mirrors execute()."""
        import asyncio

        cap = self.get(name)
        if cap is None:
            return {"ok": False, "error": "unknown capability", "name": name}
        params = dict(params or {})
        if cap.input_model is not None:
            try:
                validated = cap.input_model(**params)
                params = validated.model_dump()
            except Exception as exc:
                detail = str(exc).replace("\n", " ")[:200]
                return {"ok": False, "error": f"invalid arguments: {detail}",
                        "name": name}
        else:
            missing = [p for p in cap.input if params.get(p) in (None, "")]
            if missing:
                return {"ok": False,
                        "error": "missing input: " + ",".join(missing), "name": name}
        ok, reason = self._check_for_execute(name)
        if not ok:
            return {"ok": False, "error": reason, "name": name}
        started = time.perf_counter()
        try:
            output = cap.handler(params)
            if inspect.isawaitable(output):
                output = await output
        except Exception as exc:
            self._safe_rollback(cap)
            return {"ok": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}"[:200],
                    "name": name}
        if cap.verify is not None:
            try:
                if not cap.verify(output):
                    self._safe_rollback(cap)
                    return {"ok": False, "error": "verify failed", "name": name}
            except Exception:
                self._safe_rollback(cap)
                return {"ok": False, "error": "verify error", "name": name}
        record = {"ok": True, "output": output, "name": name,
                  "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)}
        self._emit_commit(record)
        return record

    async def execute_openai_async(self, openai_name: str,
                                   params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        cap = self.get_by_openai_name(str(openai_name))
        if cap is None:
            return {"ok": False, "error": "unknown capability", "name": openai_name}
        return await self.execute_async(cap.name, params)

    def execute(self, name: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        cap = self.get(name)
        if cap is None:
            return {"ok": False, "error": "unknown capability", "name": name}
        params = dict(params or {})
        if cap.input_model is not None:
            try:
                validated = cap.input_model(**params)
                params = validated.model_dump()
            except Exception as exc:
                detail = str(exc).replace("\n", " ")[:200]
                return {"ok": False, "error": f"invalid arguments: {detail}",
                        "name": name}
        else:
            missing = [p for p in cap.input if params.get(p) in (None, "")]
            if missing:
                return {"ok": False, "error": "missing input: " + ",".join(missing),
                        "name": name}
        ok, reason = self._check_for_execute(name)
        if not ok:
            return {"ok": False, "error": reason, "name": name}
        started = time.perf_counter()
        try:
            output = cap.handler(params)
        except Exception as exc:
            self._safe_rollback(cap)
            return {"ok": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}"[:200],
                    "name": name}
        if cap.verify is not None:
            try:
                if not cap.verify(output):
                    self._safe_rollback(cap)
                    return {"ok": False, "error": "verify failed",
                            "name": name, "include_verify": True}
            except Exception:
                self._safe_rollback(cap)
                return {"ok": False, "error": "verify error", "name": name}
        record = {"ok": True, "output": output, "name": name,
                  "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)}
        self._emit_commit(record)
        return record

    @staticmethod
    def _safe_rollback(cap: Capability) -> None:
        if cap.rollback is not None:
            try:
                cap.rollback()
            except Exception:
                pass
