"""成长日志 (P4a): append-only record of significant changes, so Yuanheng's
growth is traceable ("可回溯的成长"). 明文 Markdown（文件即记忆，透明可审计）。

Usage:
    from backend import growth_log
    growth_log.record("记忆", "用户喜欢靛蓝", source="老爹")
    growth_log.recent(20)
"""
from __future__ import annotations

import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
GROWTH_FILE = _ROOT / "docs" / "元亨的成长日志.md"
_HEADER = ("# 元亨的成长日志\n\n"
           "> 自动追加：记录记忆/认知/内在因/技能/快照等**重要变更**，供回溯成长。\n\n")


def record(kind: str, summary: str, detail: str = "", source: str = "") -> None:
    summary = str(summary or "").strip()
    if not summary:
        return
    line = (f"- [{time.strftime('%Y-%m-%d %H:%M')}] **{kind}** "
            f"{summary[:120]}" + (f"（{source}）" if source else ""))
    if detail:
        line += f" —— {str(detail)[:120]}"
    try:
        GROWTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not GROWTH_FILE.exists():
            GROWTH_FILE.write_text(_HEADER, encoding="utf-8")
        with GROWTH_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def recent(n: int = 20) -> list[str]:
    try:
        lines = [l for l in GROWTH_FILE.read_text(encoding="utf-8").splitlines()
                 if l.strip().startswith("- [")]
        return lines[-int(n):]
    except Exception:
        return []
