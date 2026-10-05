"""段5（R5, ledger 0635）：回合结果按 request_id 留存——断连后可**取结果**而非重跑。

- 只存**最终结果摘要**（answer/工具数/发布状态/时间），不存副作用重放入口。
- 路径可重定向（评测/测试用临时目录）；bounded（只保留最近若干条）。
"""
from __future__ import annotations

import json
import pathlib
import time

DIR = pathlib.Path(__file__).resolve().parent.parent / "cache" / "tmp" / "talk_results"
MAX_KEEP = 200


def _path(request_id: str) -> pathlib.Path:
    safe = "".join(c for c in str(request_id) if c.isalnum() or c in "-_")[:64]
    return DIR / f"{safe}.json"


def store(request_id: str, payload: dict) -> None:
    if not request_id:
        return
    DIR.mkdir(parents=True, exist_ok=True)
    data = dict(payload)
    data.setdefault("finished_at", time.time())
    tmp = _path(request_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_path(request_id))
    try:  # bounded：清理最旧
        files = sorted(DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for p in files[:-MAX_KEEP]:
            p.unlink(missing_ok=True)
    except Exception:
        pass


def load(request_id: str) -> dict | None:
    p = _path(request_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
