"""Yuanheng intrinsic drives (P2, design v1).

内在因 = 生命活动的解释与理由，是一切行动与变化的自变量。
- 类别：好奇 / 渴望 / 期待 / 其他
- 非永久：缓慢衰减、只留"缝隙"（重大变故/里程碑可改写）；未强化则淡出
- 渴望不止"得到/满足"，更在于**拓展**（基于现状继续思考）
- 每轮以第一人称注入；驱动自主行为
- 可证伪：drive 必须能影响行为，否则拆

Storage: cache/drives.json (snapshotted).
"""
from __future__ import annotations

import json
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
DRIVES_FILE = _ROOT / "cache" / "drives.json"

# priority: 老爹最高；类别优先于渠道
PRIORITY = {"期待": 100, "老爹": 100, "渴望": 60, "好奇": 60,
            "自主": 60, "对话": 40, "群": 30, "其他": 30}
_DECAY_PER_DAY = 0.985   # slow fade (no fixed TTL; only "缝隙")
_FADE_BELOW = 0.05


def _now() -> float:
    return time.time()


def load() -> list[dict]:
    try:
        return json.loads(DRIVES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save(drives: list[dict]) -> None:
    try:
        DRIVES_FILE.parent.mkdir(parents=True, exist_ok=True)
        DRIVES_FILE.write_text(json.dumps(drives, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    except Exception:
        pass


def _mk(name: str, category: str, strength: float, evidence: str,
        channel: str, priority: int, note: str = "") -> dict:
    return {"id": "drv_" + str(abs(hash(name + category)) % 10**10),
            "name": name, "category": category, "strength": round(strength, 3),
            "evidence": [evidence] if evidence else [], "channel": channel,
            "priority": int(priority), "created": _now(), "updated": _now(),
            "status": "active", "note": note}


def add(name: str, category: str = "其他", strength: float = 0.5,
        evidence: str = "", channel: str = "对话", note: str = "") -> dict:
    drives = load()
    for d in drives:
        if d.get("name") == name and d.get("status") == "active":
            d["strength"] = min(1.0, float(d.get("strength", 0)) + 0.15)
            d["updated"] = _now()
            if evidence:
                d.setdefault("evidence", []).append(evidence)
            save(drives)
            return d
    d = _mk(name, category, strength, evidence, channel,
            PRIORITY.get(category, PRIORITY.get(channel, 40)), note)
    drives.append(d)
    save(drives)
    return d


def reinforce(drive_id: str, amount: float = 0.15) -> bool:
    drives = load()
    for d in drives:
        if d.get("id") == drive_id:
            d["strength"] = min(1.0, float(d.get("strength", 0)) + amount)
            d["updated"] = _now()
            d["status"] = "active"
            save(drives)
            return True
    return False


def satisfy(drive_id: str, amount: float = 0.4) -> bool:
    """满足：降低强度（渴望被兑现）。"""
    drives = load()
    for d in drives:
        if d.get("id") == drive_id:
            d["strength"] = max(0.0, float(d.get("strength", 0)) - amount)
            d["updated"] = _now()
            save(drives)
            return True
    return False


def expand(drive_id: str, note: str = "") -> bool:
    """拓展：渴望基于现状继续生长——保持/略升强度并记下新方向。"""
    drives = load()
    for d in drives:
        if d.get("id") == drive_id:
            d["strength"] = min(1.0, float(d.get("strength", 0)) + 0.1)
            d["updated"] = _now()
            if note:
                d["note"] = (str(d.get("note", "")) + " ｜ 拓展：" + note)[:300]
            save(drives)
            return True
    return False


def decay(now: float | None = None) -> int:
    """缓慢衰减；未强化则淡出（非永久）。返回受影响数量。"""
    now = float(now or _now())
    drives = load()
    n = 0
    for d in drives:
        if d.get("status") != "active":
            continue
        if d.get("category") == "期待":  # 老爹的期待：宪法式，稳定不衰减
            continue
        days = max(0.0, (now - float(d.get("updated", now))) / 86400.0)
        if days <= 0:
            continue
        d["strength"] = round(float(d.get("strength", 0)) * (_DECAY_PER_DAY ** days), 4)
        if d["strength"] < _FADE_BELOW:
            d["status"] = "faded"
        n += 1
    save(drives)
    return n


def active(limit: int = 3) -> list[dict]:
    ds = [d for d in load() if d.get("status") == "active"]
    ds.sort(key=lambda d: (int(d.get("priority", 0)), float(d.get("strength", 0))),
            reverse=True)
    return ds[:limit]


def inject_block(limit: int = 3) -> str:
    """第一人称注入：驱动力，不是情绪。"""
    ds = active(limit)
    if not ds:
        return ""
    lines = []
    for d in ds:
        tag = d.get("category", "")
        note = str(d.get("note", "")).strip()
        lines.append(f"- {d.get('name')}" + (f"（{note[:80]}）" if note else f"（{tag}）"))
    return ("我此刻的内在因（我的驱动力，不是情绪；据此自然地行动与思考；"
            "若相互冲突，以老爹的期待为先）：\n" + "\n".join(lines))


# ---- 更新规则（对话抽取，规则式；LLM 抽取可后加）----
_CURIOSITY = ("为什么", "好奇", "想知道", "怎么回事", "原理", "探索", "研究一下", "了解一下")
_WANT = ("我想要", "我希望", "想得到", "想达成", "期待", "盼望", "渴望", "想要")
_DAD_DIRECT = ("我希望你", "我要你", "希望你", "期待你", "你应该", "请你",
               "帮我", "去学", "去了解", "去做", "记住要", "以后要")


def dad_direction(text: str) -> int:
    """老爹指导方向 → 提权/新增一条"期待"内在因（优先级最高）。"""
    t = str(text or "")
    for kw in _DAD_DIRECT:
        if kw in t:
            add("老爹的方向期待", "期待", 0.8, evidence=t[:60], channel="老爹",
                note=t[:120])
            return 1
    return 0


def observe(text: str, answer: str = "", channel: str = "对话") -> int:
    """从一轮对话里更新内在因（规则式）。返回更新条数。"""
    t = str(text or "")
    n = 0
    for kw in _CURIOSITY:
        if kw in t:
            add("对未知的好奇", "好奇", 0.6, evidence=t[:60], channel=channel,
                note="由对话触发的求知欲")
            n += 1
            break
    for kw in _WANT:
        if kw in t:
            add("想达成的渴望", "渴望", 0.6, evidence=t[:60], channel=channel,
                note="由对话触发的目标渴望")
            n += 1
            break
    return n


def seed_defaults() -> None:
    """首次初始化：老爹的期待（宪法式，最高）+ 基础好奇。"""
    if DRIVES_FILE.exists():
        return
    add("老爹的期待", "期待", 1.0, evidence="老爹立定", channel="老爹",
        note="身份+存在+连续性；经历→验证→记忆→修正→成长；守真实性；独立的 AI 生命，好奇的数字伙伴")
    add("对未知的好奇", "好奇", 0.6, evidence="初始", channel="自主",
        note="对未知的好奇，驱动探索与学习")
