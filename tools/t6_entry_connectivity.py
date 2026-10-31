"""T6 真机连通（ledger 0617）：同入口 + 临时载体 + 现有 Gemma（本地 8081）。

流程：临时沙箱载体 → console 会话（同 daemon 工作台入口形态）→ 多轮真机 →
核对 工具/读回/效果字段 → **新会话（同库）复读**证明持久。
不改生产文件与真实载体。
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.env_loader import ensure_env_loaded

ensure_env_loaded()

from tools.persona_regression import _sandbox_writes, _restore_writes  # noqa: E402


async def main() -> int:
    from backend.target_entry import ConversationSession
    from backend.target_kw_index import KeywordIndex
    from backend.target_memory import TargetMemoryService

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t6_entry_"))
    saved = _sandbox_writes(tmp)

    def new_session():
        mem = TargetMemoryService(db_path=tmp / "memstore.db",
                                  kw_index=KeywordIndex(tmp / "kw.db"))
        mem._auto_adjudicate = lambda item: None  # type: ignore[method-assign]
        mem._auto_link_causal = lambda item: None  # type: ignore[method-assign]
        s = ConversationSession(memory=mem, channel="console")
        return s, mem

    turns = [
        "在吗？",
        "现在几点了？",
        "记住：我最喜欢的茶是普洱。",
        "把 main.py 里的同步循环改成异步。",
    ]
    rows = []
    s, mem = new_session()
    for q in turns:
        info = await s.run_turn(q)
        uses = info.get("tool_uses") or []
        rows.append({"q": q, "answer": str(info.get("answer"))[:80],
                     "tools": [u.get("name") for u in uses],
                     "readback": [u.get("effect", "") if isinstance(u, dict) else getattr(u, "readback", "") for u in uses]})
        print(f"Q: {q}")
        print(f"  A: {str(info.get('answer'))[:80]}")
        print(f"  tools={[u.get('name') for u in uses]} readback={[getattr(u,'readback','') for u in uses]}")

    # 新会话同库复读（持久性证明）
    s2, _ = new_session()
    info2 = await s2.run_turn("我最喜欢的茶是什么？")
    print("\n[新会话复读] A:", str(info2.get("answer"))[:100])
    print("  tools=", [u.get("name") for u in info2.get("tool_uses") or []])

    _restore_writes(saved)
    out = pathlib.Path("artifacts/nonvoice_next_stage/t6_entry_connectivity.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"turns": rows,
                               "fresh_recall": str(info2.get("answer"))[:120],
                               "fresh_tools": [u.get("name") for u in info2.get("tool_uses") or []]},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nwritten ->", out)
    return 0


raise SystemExit(asyncio.run(main()))
