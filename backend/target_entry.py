"""Conversation entry (M1 ledger 0152): CLI REPL + testable session.

Session = persona-dynamic system (base + persona_draft + tools) + multi-turn
history (bounded) + L1 memory window (auto) + orchestrator (tool loop) +
CLI approver for side-effect capabilities (memory.save etc).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

from backend.target_kw_index import KeywordIndex  # noqa: F401  (ensure module)
from backend.target_memory import TargetMemoryService
from backend.target_orchestrator import (
    Approver,
    TurnOrchestrator,
    build_openai_compatible_llm_turn,
)
from backend.target_prompts import render_system_prompt
from backend.target_scheduler_tools import (
    bind_memory_save_service,
    setup_scheduler_capabilities,
)

HISTORY_LIMIT = 20
SAVE_APPROVAL_POLICY = "memory.save.approval"
SESSIONS_DIR = _PROJECT_ROOT / "cache" / "sessions"


def _cli_approver_factory(prompt_fun: Any = None) -> Approver:
    async def _approve(info: dict[str, Any]) -> bool:
        name = info.get("name", "?")
        args = info.get("args", {})
        content = str(args.get("content", ""))[:80]
        if prompt_fun is not None:
            return bool(prompt_fun(f"批准写入记忆？内容: {content} (y/n): "))
        while True:
            try:
                line = input(f"元亨想写入记忆: {content}\n允许吗？(y/n): ").strip().lower()
            except EOFError:
                return False
            if line in ("y", "yes", "是"):
                return True
            if line in ("n", "no", "否", ""):
                return False
            print("请输入 y/n")

    return _approve


class ConversationSession:
    """One agent conversation: memory service + registry + orchestrator + llm."""

    def __init__(
        self,
        *,
        memory: Optional[TargetMemoryService] = None,
        registry: Any = None,
        llm_turn: Any = None,
        approver: Optional[Approver] = None,
        max_tool_rounds: int = 2,
        history_limit: int = HISTORY_LIMIT,
    ) -> None:
        self.memory = memory or TargetMemoryService()
        self.registry = registry if registry is not None else setup_scheduler_capabilities()
        bind_memory_save_service(self.registry, self.memory)
        self.llm_turn = llm_turn or build_openai_compatible_llm_turn()
        if approver is not None:
            user_approver = approver

            async def _wrap(info: dict) -> bool:
                granted = await user_approver(info)
                if granted:
                    self.registry.grant_policy_once(SAVE_APPROVAL_POLICY)
                return granted

            approver = _wrap
        self.orchestrator = TurnOrchestrator(
            self.registry, max_tool_rounds=max_tool_rounds, approver=approver
        )
        self.history_limit = int(history_limit)
        self.history: list[dict[str, Any]] = []
        self._summary_tasks: list[Any] = []
        self._persona = ""

    # ---------- system / persona ----------
    def render_system(self) -> str:
        tools = self.registry.export_openai_tools()
        try:
            draft = self.memory.persona_draft()
        except Exception:
            draft = ""
        self._persona = draft or ""
        persona_arg = None
        if draft and draft.strip():
            from backend.target_prompts import ANCHOR

            persona_arg = None if draft == ANCHOR else draft
        return render_system_prompt(persona=persona_arg, tools=tools)

    # ---------- contradiction trigger (M3: old-kernel contradiction -> belief) ----------
    _NEGATION = ("其实我不", "我不喜欢", "不喜欢", "不是", "不要再", "我改主意", "错了", "相反", "其实不是")

    def _maybe_contradiction(self, text: str) -> int:
        """If the user utterance negates a stored memory topic, lower its belief."""
        if not any(m in text for m in self._NEGATION):
            return 0
        try:
            hits = self.memory.recall(text, limit=2)
        except Exception:
            return 0
        n = 0
        for h in hits:
            try:
                self.memory.observe_contradiction(h["id"])
                n += 1
            except Exception:
                pass
        return n

    # ---------- turn ----------
    async def run_turn(self, text: str) -> dict[str, Any]:
        self.memory.append_turn(role="user", text=text)
        contradictions = self._maybe_contradiction(text)
        system = self.render_system()
        result = await self.orchestrator.run(
            turn_text=text,
            system_prompt=system,
            llm_turn=self.llm_turn,
            history=self.history,
        )
        self.memory.append_turn(role="assistant", text=result.answer)
        if self.memory._summary_pending:
            self._summary_tasks.append(asyncio.ensure_future(self.memory.process_summary()))
        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant", "content": result.answer})
        if len(self.history) > self.history_limit:
            self.history = self.history[-self.history_limit:]
        return {
            "answer": result.answer,
            "tool_uses": [
                {"name": u.name, "ok": u.ok, "error": u.error} for u in result.tool_uses
            ],
            "iterations": result.iterations,
            "persona_draft": bool(self._persona),
            "contradictions": contradictions,
        }

    # ---------- reflection (post-session insight -> memory candidates) ----------
    async def reflect(self, llm_turn: Any = None) -> dict:
        """Review this session's turns and persist durable insights as L2 items
        (type=reflection). Uses the real LLM; failure degrades silently."""
        if len(self.history) < 4:
            return {"insights": 0, "reason": "too-few-turns"}
        turns = "\n".join(
            f"{'用户' if m.get('role') == 'user' else '元亨'}: {m.get('content', '')[:200]}"
            for m in self.history[-10:]
        )
        prompt = (
            "从下面的对话中提炼 0-2 条值得长期记住的洞察（用户偏好/项目决策/"
            "协作习惯），每条≤40字；无值得记的输出空。只输出 JSON 数组："
            '[{"text": "..."}]\n对话：\n' + turns
        )
        turn_fn = llm_turn or self.llm_turn
        try:
            resp = await turn_fn(
                [{"role": "user", "content": prompt}], []
            )
        except Exception:
            return {"insights": 0, "reason": "llm-error"}
        text = str(resp.get("content") or "").strip()
        import re as _re

        m = _re.search(r"\[.*\]", text, _re.S)
        if not m:
            return {"insights": 0, "reason": "no-json"}
        try:
            items = json.loads(m.group(0))
        except Exception:
            return {"insights": 0, "reason": "bad-json"}
        n = 0
        for it in items or []:
            t = str(it.get("text", "")).strip()
            if 6 <= len(t) <= 60:
                from backend.target_scheduler_tools import memory_save

                try:
                    memory_save(t, kind="preference", service=self.memory)
                    n += 1
                except Exception:
                    pass
        return {"insights": n, "reason": "ok"}

    # ---------- persistence (message-level, cache/sessions) ----------
    def save_session(self, name: str = "default") -> Path:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = SESSIONS_DIR / f"{name}.json"
        data = {
            "saved_at": time.time(),
            "history": self.history[-self.history_limit:],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return path

    @classmethod
    def list_sessions(cls) -> list[str]:
        if not SESSIONS_DIR.exists():
            return []
        return sorted(p.stem for p in SESSIONS_DIR.glob("*.json"))

    def load_session(self, name: str = "default") -> int:
        path = SESSIONS_DIR / f"{name}.json"
        if not path.exists():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        history = list(data.get("history", []))[-self.history_limit:]
        self.history = history
        # rebuild L1 window from restored history
        self.memory._turns = []
        for msg in history:
            role = "user" if msg.get("role") == "user" else "assistant"
            self.memory.append_turn(role=role, text=str(msg.get("content", ""))[:2000])
        return len(history)

    def status(self) -> dict:
        return {
            "history_turns": len(self.history) // 2,
            "l1_window": len(self.memory._turns),
            "l2_items": self.memory.health()["l2_items"],
            "persona_draft": bool(self._persona),
        }

    # ---------- proactive (autonomous action seed, ledger 0152) ----------
    async def proactive_tick(self, question: str = "根据最近积累的记忆，有什么值得主动整理或提醒的？") -> dict[str, Any]:
        """Self-initiated turn (no user prompt): model reviews memory and may
        use tools; nothing is executed without gated approval."""
        self.memory.append_turn(role="user", text=f"[自主] {question}")
        result = await self.orchestrator.run(
            turn_text=question,
            system_prompt=self.render_system(),
            llm_turn=self.llm_turn,
            history=self.history[-4:],
        )
        self.memory.append_turn(role="assistant", text=result.answer)
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": result.answer})
        return {
            "answer": result.answer,
            "tool_uses": [
                {"name": u.name, "ok": u.ok, "error": u.error} for u in result.tool_uses
            ],
        }


BANNER = """元亨 · 数字生命对话入口 (target-entry v1, ledger 0160)
可用命令: /help /status /think /exit
提示: 问项目历史/决策请让我查台账；要保存偏好会征求你同意。"""

_HELP = """命令列表:
  /help            本帮助
  /status          会话与记忆状态
  /think           自主回顾（我主动整理记忆）
  /exit            退出
直接输入即对话。写类操作（保存记忆）会先征求你 y/n 同意。"""


def cli_main() -> int:
    """Interactive REPL: python -m backend.target_entry"""
    import sys
    import traceback

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    session = ConversationSession(approver=_cli_approver_factory())
    print(BANNER)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    turns = 0
    try:
        while True:
            try:
                line = input("你> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line in ("/exit", "/quit", "exit", "quit"):
                print("退出。已保存记忆，回见。")
                break
            if line in ("/help", "help", "帮助"):
                print(_HELP)
                continue
            if line == "/status":
                print(session.status())
                continue
            if line.startswith("/load"):
                name = line.split(maxsplit=1)[1].strip() if " " in line else "default"
                n = session.load_session(name)
                print(f"已恢复会话 {name}（{n} 条消息）")
                continue
            if line.startswith("/save"):
                name = line.split(maxsplit=1)[1].strip() if " " in line else "default"
                p = session.save_session(name)
                print(f"已保存会话 {name} → {p}")
                continue
            if line == "/sessions":
                print("会话: " + ", ".join(session.list_sessions() or ["(无)"]))
                continue
            if line in ("/reflect",):
                info = loop.run_until_complete(session.reflect())
                print(f"反思完成: {info}")
                continue
            if line in ("/consolidate",):
                from backend.target_persona_loop import PersonaConsolidationLoop

                pc = PersonaConsolidationLoop(session.llm_turn, session.memory)
                info = loop.run_until_complete(pc.consolidate_once())
                print(f"沉淀闭环: {info}")
                continue
            if line in ("/think", "/proactive"):
                try:
                    info = loop.run_until_complete(session.proactive_tick())
                    print("元亨(自主)> " + info["answer"][:300])
                except Exception as exc:
                    print(f"(自主回顾失败: {type(exc).__name__})")
                continue
            try:
                info = loop.run_until_complete(session.run_turn(line))
            except Exception as exc:
                traceback.print_exc()
                print(f"(本轮处理失败: {type(exc).__name__}；可重试)")
                continue
            turns += 1
            print("元亨> " + info["answer"])
            for u in info["tool_uses"]:
                if not u["ok"]:
                    print(f"  [工具失败] {u['name']}: {u['error']}")
    finally:
        try:
            session.save_session()
        except Exception:
            pass
        loop.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
