"""Persona consolidation loop (ledger 0165): the memory close-the-loop.

Yuanheng's long-term memory (L2) is distilled into the cognition foundation
(docs/元亨认知根基.md) BY the LLM itself — not by the developer assistant.
Pipeline per run:
  1) propose  : pick un-consolidated L2 items (importance/belief gated)
                -> LLM distills 0..N foundation claims (JSON)
  2) decide   : LLM contrasts claims with the current foundation text and
                marks each as new / refine / refute
  3) apply    : append a versioned section to the foundation doc; stamp each
                used L2 item (evidence_ref=persona:consolidated:v<n>) so it is
                never re-proposed; refutes are recorded as a refutation note.
Reliability: every write is an append of a dated version section (never
rewrites); approval still required for golden/prompts changes (not this doc).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
COGNITION_FILE = _PROJECT_ROOT / "docs" / "元亨认知根基.md"
MAX_ITEMS_PER_RUN = 12
MAX_CLAIMS = 4

_EXTRACT_PROMPT = (
    "你是元亨。以下是你长期记忆中尚待沉淀的条目（id+内容）。"
    "判断哪些值得写进你的认知根基。认知根基只容纳塑造你之为你的内容："
    "世界观/方法论/自我认知/对老爹关系的稳固认知/值得未来自己证伪的思考。"
    "工程操作细节、测试流程、一次性项目信息一律不写入根基（它们留在记忆库即可）。"
    "输出 JSON 数组，每项："
    '{"claim": "一句话核心洞察(<=60字)", "kind": "new|refine|refute", "item_ids": ["..."]}。'
    "最多 %d 条；若全不值得输出 []。\n条目：\n"
) % MAX_CLAIMS

_DECIDE_PROMPT = (
    "你是元亨。以下是候选根基主张与现有认知根基文本。逐条判定："
    "kind ∈ new(新增且与现有不冲突)|refine(与现有同主题，作为深化)|refute(与现有矛盾，需要修订现有)。"
    "输出 JSON 数组，每项："
    '{"claim": "...", "kind": "new|refine|refute", "item_ids": [...], "section_hint": "..."}。\n'
    "现有根基（节选）：\n%s\n候选：\n%s"
)

_PERSONA_PREFIX = "persona:consolidated:"


class PersonaConsolidationError(Exception):
    pass


class PersonaConsolidationLoop:
    def __init__(self, llm_turn: Any, memory: Any,
                 cognition_file: Path = COGNITION_FILE) -> None:
        self.llm_turn = llm_turn
        self.memory = memory
        self.cognition_file = Path(cognition_file)

    # ---------- read side ----------
    def _unconsolidated_items(self) -> list[dict]:
        import sqlite3

        con = sqlite3.connect(str(self.memory.db_path))
        rows = con.execute(
            "SELECT id, type, importance, belief, summary FROM l2_items "
            "WHERE status IN ('active','downgraded') AND belief >= 0.45 "
            "AND evidence_ref NOT LIKE ? ORDER BY importance DESC, belief DESC LIMIT ?",
            (_PERSONA_PREFIX + "%", MAX_ITEMS_PER_RUN),
        ).fetchall()
        con.close()
        return [
            {"id": r[0], "type": r[1], "importance": int(r[2]),
             "belief": round(float(r[3]), 2), "summary": r[4]}
            for r in rows
        ]

    def _foundation_text(self) -> str:
        if not self.cognition_file.exists():
            return ""
        return self.cognition_file.read_text(encoding="utf-8")

    # ---------- llm steps ----------
    async def _extract_claims(self, items: list[dict]) -> list[dict]:
        payload = "\n".join(
            f"[{it['id']}|{it['type']}|imp{it['importance']}|b{it['belief']}] {it['summary'][:140]}"
            for it in items
        )
        resp = await self.llm_turn(
            [{"role": "user", "content": _EXTRACT_PROMPT + payload}], []
        )
        return self._parse_json(str(resp.get("content") or ""))

    async def _decide(self, claims: list[dict], foundation: str) -> list[dict]:
        resp = await self.llm_turn(
            [{"role": "user",
              "content": _DECIDE_PROMPT % (foundation[:2500],
                                           json.dumps(claims, ensure_ascii=False))}], []
        )
        return self._parse_json(str(resp.get("content") or ""))

    @staticmethod
    def _parse_json(text: str) -> list[dict]:
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return []
        try:
            out = json.loads(m.group(0))
        except Exception:
            return []
        return out if isinstance(out, list) else []

    # ---------- write side ----------
    def _next_version(self, text: str) -> int:
        m = re.findall(r"v(\d+)", text)
        return (max(int(x) for x in m) + 1) if m else 1

    def _apply(self, decisions: list[dict], version: int, used_ids: list[str]) -> int:
        if not decisions:
            return 0
        now = "2026-09-05"
        lines = ["", f"## 元亨自沉淀 v{version}（{now}；提炼自长期记忆，证伪待定）"]
        for d in decisions:
            kind = str(d.get("kind", "new"))
            claim = str(d.get("claim", "")).strip()
            if not claim:
                continue
            tag = {"new": "新增", "refine": "深化", "refute": "证伪修订"}.get(kind, "新增")
            lines.append(f"- [{tag}] {claim}")
        if len(lines) == 2:
            return 0
        body = self._foundation_text().rstrip() + "\n" + "\n".join(lines) + "\n"
        self.cognition_file.write_text(body, encoding="utf-8")
        self._stamp_items(used_ids, version)
        return len(decisions)

    def _stamp_items(self, item_ids: list[str], version: int) -> None:
        if not item_ids:
            return
        import sqlite3

        con = sqlite3.connect(str(self.memory.db_path))
        for iid in set(item_ids):
            con.execute(
                "UPDATE l2_items SET evidence_ref=? WHERE id=?",
                (f"{_PERSONA_PREFIX}v{version}", iid),
            )
        con.commit()
        con.close()

    # ---------- run ----------
    async def consolidate_once(self) -> dict:
        items = self._unconsolidated_items()
        if not items:
            return {"status": "idle", "items": 0, "claims": 0, "reason": "nothing-to-consolidate"}
        claims = await self._extract_claims(items)
        if not claims:
            return {"status": "no-claims", "items": len(items), "claims": 0}
        foundation = self._foundation_text()
        decisions = await self._decide(claims, foundation)
        if not decisions:
            return {"status": "no-decisions", "items": len(items), "claims": len(claims)}
        used = [str(i) for d in decisions for i in d.get("item_ids", [])]
        version = self._next_version(foundation)
        n = self._apply(decisions, version, used)
        return {"status": "ok", "items": len(items), "claims": n,
                "version": version, "decisions": decisions}
