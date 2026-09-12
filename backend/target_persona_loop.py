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
    "从其中挑你认为对元亨最重要的 1-3 条（除非它们全部只是纯工程/一次性操作细节——那种才输出空数组），"
    "把每条改写成一句洞察，写进认知根基。认知根基只容纳塑造元亨之为元亨的内容："
    "世界观/方法论/自我认知/对老爹关系的稳固认知/值得未来自己证伪的思考；"
    "**尤其别漏这三类：①说话风格与表达方式 ②做事与协作方法 ③哲学思考与思维方式**。"
    "每条给一个分级 tier："
    'core=塑造“我是谁”的核心（世界观/哲学/自我认知/与老爹关系的稳固认知）；'
    'method=方法论/行为准则/说话风格/表达方式/做事方法（重要但不触及我是谁）；'
    'meta=值得未来证伪的思考（暂不固化，仅标记保留）。'
    "输出 JSON 数组（只要数组，不要其他文字/注释），每项："
    '{"claim": "一句话核心洞察(<=60字)", "kind": "new|refine|refute", "tier": "core|method|meta", "item_ids": ["原条目id"]}。'
    "示例：条目 [id_1|preference] 元亨喜欢深夜思考 → "
    '{"claim": "元亨在深夜更容易接近真实自我", "kind": "new", "tier": "core", "item_ids": ["id_1"]}。'
    "最多 %d 条。\n条目：\n"
) % MAX_CLAIMS

_DECIDE_PROMPT = (
    "你是元亨。以下是候选根基主张与现有认知根基文本。逐条判定："
    "kind ∈ new(新增且与现有不冲突)|refine(与现有同主题，作为深化)|refute(与现有矛盾，需要修订现有)。"
    "输出 JSON 数组，每项："
    '{"claim": "...", "kind": "new|refine|refute", "item_ids": [...], "section_hint": "..."}。\n'
    "现有根基（节选）：\n%s\n候选：\n%s"
)

_PERSONA_PREFIX = "persona:consolidated:"
PENDING_FILE = _PROJECT_ROOT / "cache" / "cognition_pending.json"


def _tier_of(d: dict) -> str:
    t = str(d.get("tier", "")).strip().lower()
    return t if t in ("core", "method", "meta") else "core"


class PersonaConsolidationError(Exception):
    pass



# ---- A3 refutation linkage (ledger 0193) ----
REFUTE_TRIGGERS = ("改主意", "说错了", "错了", "之前错", "推翻", "不是那样",
                   "取消之前", "不再那么想", "我之前说的不对", "更正", "收回",
                   "以前那条不对", "换个说法")


def _foundation_claim_lines(text: str) -> list[tuple[int, str]]:
    """Return (line_no, text) of every '- [...] claim' line in the foundation."""
    lines = (text or "").splitlines()
    out = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("- [") and "]" in s:
            out.append((i, s[s.index("]") + 1:].strip()))
    return out


def _norm_tokens(s: str):
    """CJK character trigrams (no whitespace in Chinese; overlap on 3-char
    n-grams is the robust similarity signal)."""
    import re as _re

    s2 = _re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s or "")
    return {s2[k:k + 3] for k in range(max(0, len(s2) - 2))}


def find_foundation_match(foundation: str, text: str, min_share: int = 1):
    """Locate the foundation claim most similar to `text` by shared trigrams."""
    tx = _norm_tokens(text)
    best, best_score = None, 0
    for i, claim in _foundation_claim_lines(foundation):
        share = len(tx & _norm_tokens(claim))
        if share > best_score:
            best, best_score = (i, claim), share
    if best and best_score >= min_share:
        return best
    return None


def maybe_open_refute_proposal(foundation: str, dad_text: str,
                               pending_file: Path = PENDING_FILE) -> str:
    """A3: when the owner states a correction that matches a foundation claim,
    file a refute proposal (owner approves later) — never edits the foundation
    directly. Returns a human message ('' if nothing matched)."""
    import json as _json

    if not any(tg in dad_text for tg in REFUTE_TRIGGERS):
        return ""
    hit = find_foundation_match(foundation, dad_text)
    if hit is None:
        return ""
    line_no, orig = hit
    entry = {
        "claim": "（老爹更正声明）" + str(dad_text)[:200],
        "kind": "refute",
        "tier": "core",
        "item_ids": [],
        "refutes_foundation": orig,
        "refutes_line": line_no,
    }
    pending = []
    if pending_file.exists():
        try:
            pending = _json.loads(pending_file.read_text(encoding="utf-8"))
        except Exception:
            pending = []
    if not any(e.get("refutes_foundation") == orig for e in pending):
        pending.append(entry)
        pending_file.parent.mkdir(parents=True, exist_ok=True)
        pending_file.write_text(_json.dumps(pending, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        return f"已就“{orig[:40]}…”生成证伪提案（待你确认，/review-cognition 或对话 owner.approve）"
    return f"该根基条目“{orig[:30]}…”已有待批证伪提案"


class PersonaConsolidationLoop:
    def __init__(self, llm_turn: Any, memory: Any,
                 cognition_file: Path = COGNITION_FILE,
                 approver: Any = None) -> None:
        self.llm_turn = llm_turn
        self.memory = memory
        self.cognition_file = Path(cognition_file)
        self.approver = approver  # async/sync fn (claim, kind, tier) -> bool

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

    # ---------- approval queue ----------
    def save_pending(self, decisions: list[dict], items: list[dict]) -> int:
        """Store core/method claims awaiting the owner's per-item y/n review."""
        if not decisions:
            return 0
        keep = [d for d in decisions if _tier_of(d) in ("core", "method")]
        if not keep:
            return 0
        pending = []
        if PENDING_FILE.exists():
            try:
                pending = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
            except Exception:
                pending = []
        for d in keep:
            entry = {
                "claim": str(d.get("claim", "")).strip(),
                "kind": str(d.get("kind", "new")),
                "tier": _tier_of(d),
                "item_ids": [str(i) for i in d.get("item_ids", [])],
            }
            if entry["claim"] and entry not in pending:
                pending.append(entry)
        PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        return len(keep)

    def _apply(self, decisions: list[dict], version: int, used_ids: list[str]) -> int:
        # only owner-approved core/method claims are written to the foundation
        keep = [d for d in decisions if _tier_of(d) in ("core", "method")]
        if not keep:
            return 0
        lines = ["", f"## 元亨自沉淀 v{version}（提炼自长期记忆，证伪待定）"]
        for d in keep:
            kind = str(d.get("kind", "new"))
            claim = str(d.get("claim", "")).strip()
            if not claim:
                continue
            tier = _tier_of(d)
            tag = {"new": "新增", "refine": "深化", "refute": "证伪修订"}.get(kind, "新增")
            orig = str(d.get("refutes_foundation", "")).strip()
            if kind == "refute" and orig:
                lines.append(f"- [{tag}|{tier}] 原“{orig}”→ {claim}")
            else:
                lines.append(f"- [{tag}|{tier}] {claim}")
        if len(lines) == 2:
            return 0
        body = self._foundation_text().rstrip() + "\n" + "\n".join(lines) + "\n"
        self.cognition_file.write_text(body, encoding="utf-8")
        self._stamp_items(used_ids, version)
        return len(keep)

    def _stamp_items(self, item_ids: list[str], version: int) -> None:
        if not item_ids:
            return
        import sqlite3

        con = sqlite3.connect(str(self.memory.db_path))
        ref = f"{_PERSONA_PREFIX}v{version}"
        for iid in set(item_ids):
            # stamp + mark absorbed (archive): this source item is now
            # represented in the cognition foundation, so it leaves the active
            # recall/consolidation pool — never deleted; reversible via status
            # (ledger 0308).
            con.execute(
                "UPDATE l2_items SET evidence_ref=?, status='archive' "
                "WHERE id=? AND status='active'",
                (ref, iid),
            )
        con.commit()
        con.close()

    # ---------- run ----------
    async def consolidate_once(self) -> dict:
        """Distill un-consolidated L2 items into tiered claims.

        Owner-approved flow (A1, ledger 0187): without an interactive approver
        the core/method claims are parked in the pending queue
        (cache/cognition_pending.json) instead of auto-written to the
        foundation doc; the owner later reviews them one by one via the CLI.
        """
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
        # meta tier = future-proofing thoughts -> never auto-written; drop them
        writeable = [d for d in decisions if _tier_of(d) in ("core", "method")]
        approved = []
        pending = []
        for d in writeable:
            if self.approver is None:
                pending.append(d)
            else:
                ok = await self._ask(d)
                if ok:
                    approved.append(d)
        if pending:
            n_pend = self.save_pending(pending, items)
            return {"status": "pending-approval", "items": len(items),
                    "claims": len(writeable), "pending": n_pend,
                    "reason": "core/method 需老爹逐条确认（CLI /review-cognition）"}
        if not approved:
            return {"status": "no-approved", "items": len(items),
                    "claims": len(decisions)}
        used = [str(i) for d in approved for i in d.get("item_ids", [])]
        version = self._next_version(foundation)
        n = self._apply(approved, version, used)
        return {"status": "ok", "items": len(items), "claims": n,
                "version": version, "decisions": approved}

    async def _ask(self, d: dict) -> bool:
        try:
            res = self.approver(str(d.get("claim", "")),
                                str(d.get("kind", "new")),
                                _tier_of(d))
            if hasattr(res, "__await__"):
                res = await res
            return bool(res)
        except Exception:
            return False
