"""Unified evidence-based conflict adjudicator — FACT domain (M2, ledger 0318).

Pure, deterministic, auditable: given a new item and an existing item, decide
one of four actions from EVIDENCE rules (no LLM call in the default path).
It replaces the old keyword-triggered ``memory_judge`` as the primary
decision-maker; an LLM judgement may still be attached later as one signal.

Out of scope: profile/identity conflicts -> owner approval.

Actions:
  - supersede            : soft-invalidate the old item (reversible)
  - supersede_candidate  : record the direction only; do NOT invalidate
  - merge                : same fact, different wording
  - uncertain            : keep both; may ask the owner
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ACTION_SUPERSEDE = "supersede"
ACTION_CANDIDATE = "supersede_candidate"
ACTION_MERGE = "merge"
ACTION_UNCERTAIN = "uncertain"

# source-trust by substring match (老爹/owner highest; web lowest)
SOURCE_TRUST = (
    ("老爹", 1.0), ("owner", 1.0), ("user-approved", 1.0), ("memory.save", 0.85),
    ("自主", 0.6), ("agent", 0.6), ("对话", 0.5),
    ("群聊", 0.3), ("群", 0.3), ("qq", 0.3),
    ("web", 0.2),
)
_NEG = ("不", "没", "别", "不再", "改", "更正", "现在", "其实", "已经")
_SIM_MERGE = 0.95      # near-identical after normalization (short zh strings: 1-char diff would score ~0.83)
_SIM_OVERLAP = 0.30
_TRUST_GAP = 0.35


@dataclass
class Verdict:
    action: str
    reason: str
    evidence: dict = field(default_factory=dict)


def _trust(item) -> float:
    src = str(getattr(item, "source", "") or "").lower()
    for k, v in SOURCE_TRUST:
        if k and k.lower() in src:
            return v
    return 0.5


def _neg(text) -> bool:
    t = str(text or "")
    return any(x in t for x in _NEG)


def _norm(s) -> str:
    return re.sub(r"[\s\u3000,，。.!！?？:：;；、]+", "", str(s or ""))


def _sim(a, b) -> float:
    from difflib import SequenceMatcher

    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def resolve(new, old) -> Verdict:
    """Decide how `new` relates to `old`. Items need: summary, source,
    confidence, protected, created_at, evidence_count, belief (getattr-safe)."""
    if int(getattr(old, "protected", 0) or 0) == 1:
        return Verdict(ACTION_UNCERTAIN, "old-protected", {"protected": 1})
    sim = _sim(getattr(new, "summary", ""), getattr(old, "summary", ""))
    nt, ot = _trust(new), _trust(old)
    newer = float(getattr(new, "created_at", 0) or 0) >= \
        float(getattr(old, "created_at", 0) or 0)
    if sim >= _SIM_MERGE:
        return Verdict(ACTION_MERGE, f"sim={sim:.2f}", {"sim": round(sim, 3)})
    # explicit negation + trusted source + newer -> auto soft-invalidate
    if (_neg(getattr(new, "summary", "")) and nt >= 0.95 and newer
            and sim >= _SIM_OVERLAP):
        return Verdict(ACTION_SUPERSEDE, "negation+trusted+newer",
                       {"ntrust": nt, "sim": round(sim, 3)})
    # clearly higher trust + newer -> supersede
    if newer and (nt - ot) >= _TRUST_GAP and sim >= _SIM_OVERLAP:
        return Verdict(ACTION_SUPERSEDE, "trust-gap",
                       {"ntrust": nt, "otrust": ot, "sim": round(sim, 3)})
    # plausible direction but thin evidence -> record only
    if sim >= _SIM_OVERLAP:
        return Verdict(ACTION_CANDIDATE, "thin-evidence",
                       {"ntrust": nt, "otrust": ot, "sim": round(sim, 3)})
    return Verdict(ACTION_UNCERTAIN, "no-overlap", {"sim": round(sim, 3)})


def scan(new, candidates: list) -> list[tuple[object, Verdict]]:
    """Resolve `new` against candidate old items; return [(old, verdict)]."""
    out = []
    for old in candidates:
        v = resolve(new, old)
        if v.action != ACTION_UNCERTAIN:
            out.append((old, v))
    return out
