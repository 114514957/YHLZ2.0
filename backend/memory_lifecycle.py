"""L2 lifecycle state (W4, ledger 1174) — borrowed from A_memorix.

What we already had: `belief` with exponential decay
(`belief_step`: ``b *= exp(-1/8 * days)``, half-life ≈ 5.5 days) and a recall
boost (`observe_hit`, +0.05, 30 s burst dedupe). So a second "strength" column
would duplicate the decay we already run.

What we did **not** have is A_memorix's hysteresis: freeze below 0.10, revive
only above 0.15. One threshold makes belief oscillate around it and flip frozen
state on every upkeep. This module adds just that — a persisted `lifecycle`
column ('', 'frozen') with two thresholds, plus a ranking factor so frozen items
sink in recall without ever becoming unreachable.

Env:
    YHLZ_L2_STRENGTH=0|off      disable lifecycle ranking (freeze/revive off too)
    YHLZ_L2_FREEZE=0.10         freeze threshold
    YHLZ_L2_REVIVE=0.15         revive threshold (must be > freeze)
"""
from __future__ import annotations

import os

FROZEN = "frozen"
ACTIVE = ""


def enabled() -> bool:
    return str(os.getenv("YHLZ_L2_STRENGTH", "on")).strip().lower() not in (
        "0", "off", "false", "no")


def freeze_threshold() -> float:
    try:
        return float(os.getenv("YHLZ_L2_FREEZE", "0.10"))
    except Exception:
        return 0.10


def revive_threshold() -> float:
    try:
        value = float(os.getenv("YHLZ_L2_REVIVE", "0.15"))
    except Exception:
        return 0.15
    return max(value, freeze_threshold() + 1e-6)


def next_state(state: str, belief: float) -> str:
    """Hysteresis: freeze under 0.10, revive only above 0.15."""
    current = str(state or ACTIVE)
    try:
        b = float(belief)
    except Exception:
        return current
    if current == FROZEN:
        return ACTIVE if b > revive_threshold() else FROZEN
    return FROZEN if b < freeze_threshold() else ACTIVE


def rank_factor(state: str) -> float:
    """Frozen items stay reachable but rank below live ones."""
    return 0.5 if str(state or "") == FROZEN else 1.0


def half_life_days() -> float:
    """Our belief decay expressed as a half-life (ln2 / λ, λ = 1/8)."""
    import math

    return math.log(2) * 8.0
