"""Yuanheng's own recurring schedule (ledger 0209) — the driver of its autonomy.

Yuanheng designs its own time plans (daily / weekly / monthly recurring, e.g.
"每周末做一次知识整合"). The daemon reads this table every tick and, when an
entry is due, injects a gentle autonomous reminder (owner-approved model:
remind -> Yuanheng decides to act or not).

Machine-authoritative store: data/yuanheng_schedule.json
Human mirror (readable by Yuanheng & owner): docs/元亨的计划表.md

Entry schema:
  {"id","name","cadence":{"type":"daily"|"weekly"|"monthly",
                          "time":"HH:MM",
                          "weekday":0-6 (weekly), "day":1-31 (monthly)},
   "steps":["..."],        # owner-approved model: Yuanheng writes the steps
   "enabled":true, "last_run":"", "created":ts}
"""
from __future__ import annotations

import json
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHED_FILE = _ROOT / "data" / "yuanheng_schedule.json"
MIRROR_FILE = _ROOT / "docs" / "元亨的计划表.md"

# defaults = the old hardcoded 13:00 / 23:00 autonomous moments, now entries
DEFAULT_PLANS = [
    {"id": "plan_midday", "name": "午间自主回顾",
     "cadence": {"type": "daily", "time": "13:00"},
     "steps": ["看看上午有什么值得梳理的：可 task.plan 整理规划、kb.add 存一条新知识、或 diary.write 记一句。想做什么才做，简短收尾。"],
     "enabled": True},
    {"id": "plan_night", "name": "夜晚收尾",
     "cadence": {"type": "daily", "time": "23:00"},
     "steps": ["今天值得沉淀的（学到/发生/想通的）：可 task.plan 更新明天、kb.add 存知识、diary.write 写日记。做真正想做的，然后简单告诉我今天你的状态。"],
     "enabled": True},
]


def _load() -> list[dict]:
    if not SCHED_FILE.exists():
        return [json.loads(json.dumps(d)) for d in DEFAULT_PLANS]
    try:
        return json.loads(SCHED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return [json.loads(json.dumps(d)) for d in DEFAULT_PLANS]


def _save(plans: list[dict]) -> None:
    SCHED_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHED_FILE.write_text(json.dumps(plans, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    _write_mirror(plans)


def _write_mirror(plans: list[dict]) -> None:
    lines = ["# 元亨的计划表", "",
             "> 周期例行计划（统一驱动自主时刻）。由元亨自己设计；老爹可随时查看/删除。",
             "> 到点提醒元亨自主执行，不强制。", ""]
    if not plans:
        lines.append("（暂无计划）")
    for p in plans:
        cd = p.get("cadence", {})
        freq = {"daily": "每日", "weekly": f"每周{cd.get('weekday','?')}",
                "monthly": f"每月{cd.get('day','?')}日"}.get(cd.get("type"), cd.get("type", "?"))
        state = "" if p.get("enabled", True) else "（已停用）"
        lines.append(f"- **{p.get('name')}** {state}：{freq} {cd.get('time','')}")
        for s in p.get("steps", []):
            lines.append(f"    · {s}")
        lines.append(f"    （上次执行：{p.get('last_run') or '从未'}）")
    MIRROR_FILE.parent.mkdir(parents=True, exist_ok=True)
    MIRROR_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def list_plans() -> str:
    plans = _load()
    if not plans:
        return "计划表是空的"
    _write_mirror(plans)
    return MIRROR_FILE.read_text(encoding="utf-8")


def add_plan(name: str, cadence_type: str, time_: str, steps: list[str],
             weekday: int | None = None, day: int | None = None) -> str:
    name = str(name or "").strip()
    if not name or not steps or not str(steps[0]).strip():
        return "需要：name（计划名）、time（HH:MM）、steps（至少一步做什么）"
    t = str(time_ or "").strip()
    if len(t) != 5 or t[2] != ":":
        return "time 需为 HH:MM（如 09:30）"
    cd = {"type": str(cadence_type or "daily")[:10], "time": t}
    if cd["type"] not in ("daily", "weekly", "monthly"):
        cd["type"] = "daily"
    if cd["type"] == "weekly":
        cd["weekday"] = int(weekday or 0) % 7
    if cd["type"] == "monthly":
        cd["day"] = max(1, min(31, int(day or 1)))
    plans = _load()
    iid = "plan_" + str(int(time.time() * 1000))
    plans.append({"id": iid, "name": name, "cadence": cd,
                  "steps": [str(s).strip()[:300] for s in steps if str(s).strip()][:6],
                  "enabled": True, "last_run": "", "created": time.time()})
    _save(plans)
    return f"已加入计划表：{name}（{cd['type']} {t}）→ docs/元亨的计划表.md"


def delete_plan(plan_id: str) -> str:
    plans = _load()
    for p in plans:
        if p.get("id") == str(plan_id).strip():
            plans.remove(p)
            _save(plans)
            return f"已删除计划：{p.get('name')}"
    return f"未找到计划：{plan_id}"


def toggle_plan(plan_id: str, enabled: bool) -> str:
    plans = _load()
    for p in plans:
        if p.get("id") == str(plan_id).strip():
            p["enabled"] = bool(enabled)
            _save(plans)
            return f"计划 {p.get('name')} {'已启用' if enabled else '已停用'}"
    return f"未找到计划：{plan_id}"


# ---- cadence / due logic (pure, unit-testable) ----
def is_due(plan: dict, now: time.struct_time, last_run: str = "") -> bool:
    """Weekly/monthly via weekday/day match; daily always matches its day.
    A run is due when its time-of-day has passed today AND it was not already
    run this cycle (compare last_run date against the cycle's anchor)."""
    cd = plan.get("cadence", {})
    typ = cd.get("type")
    hhmm = str(cd.get("time", "")).strip()
    if len(hhmm) != 5:
        return False
    cur = now.tm_hour * 60 + now.tm_min
    target = int(hhmm[:2]) * 60 + int(hhmm[3:5])
    if cur < target:
        return False
    if typ == "weekly" and now.tm_wday != int(cd.get("weekday", 0) or 0) % 7:
        return False
    if typ == "monthly" and now.tm_mday != int(cd.get("day", 1) or 1):
        return False
    from datetime import date

    today_d = date.fromtimestamp(time.mktime(now))
    last = str(last_run or "")
    if not last or len(last) < 10:
        return True
    try:
        last_d = date.fromisoformat(last[:10])
    except Exception:
        return True
    if typ == "weekly":
        return last_d.isocalendar()[:2] != today_d.isocalendar()[:2]
    if typ == "monthly":
        return (last_d.year, last_d.month) != (today_d.year, today_d.month)
    # daily
    return last_d != today_d


def mark_run(plan_id: str, now: time.struct_time) -> None:
    plans = _load()
    for p in plans:
        if p.get("id") == plan_id:
            p["last_run"] = time.strftime("%Y-%m-%d %H:%M", now)
            _save(plans)
            return
