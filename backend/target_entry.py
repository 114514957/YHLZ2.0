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
        channel: str = "private",
    ) -> None:
        self.memory = memory or TargetMemoryService()
        if memory is None:
            # Wire the L1 rolling-summary / adjudication hooks (ledger 0217):
            # they were never connected in production, so long-conversation
            # early turns were silently dropped instead of being compressed.
            try:
                from backend.llm_vllm_provider import LlmVllmProvider
                from backend.target_memory_llm import MemoryLLMService

                _q = LlmVllmProvider(
                    base_url="http://127.0.0.1:11434",
                    model="qwen2.5:3b",
                )
                self.memory.set_llm_hooks(MemoryLLMService(_q, local=_q),
                                          MemoryLLMService(_q, local=_q))
            except Exception:
                pass
        self.channel = str(channel or "private")
        self._ctx_recent: dict[str, float] = {}  # de-dup of auto-recalled memories
        self._last_reviewed = 0          # turns count at last auto review
        self._reviewing = False
        self.style_inject = False  # style persona injection (off until A/B accepted)
        self.registry = registry if registry is not None else setup_scheduler_capabilities()
        bind_memory_save_service(self.registry, self.memory)
        from backend.target_orchestrator import build_openai_compatible_llm_turn
        from backend.env_loader import ensure_env_loaded
        from backend.target_daemon import LOCAL_BASE, LOCAL_MODEL

        ensure_env_loaded()
        self._llm_injected = llm_turn is not None
        self.llm_turn = llm_turn or build_openai_compatible_llm_turn(
            base_url="http://127.0.0.1:8081/v1/chat/completions",
            api_key="", model="gemma-4-e4b",
            temperature=0.2, max_tokens=800,
            fallback_base_url=LOCAL_BASE,
            fallback_model=LOCAL_MODEL,
            reasoning_effort="none",
        )
        if approver is not None:
            user_approver = approver

            async def _wrap(info: dict) -> bool:
                granted = await user_approver(info)
                if granted:
                    cap = self.registry.get(str(info.get("name", "")))
                    if cap is not None:
                        for req in cap.requires:
                            if req.endswith(".approval"):
                                self.registry.grant_policy_once(req)
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
        style_lines = None
        if self.style_inject and self.channel == "private":
            try:
                from backend.target_style import active_style_lines, style_ema

                items = self.memory.recall("风格偏好", limit=30)
                style_lines = active_style_lines(style_ema(items)) or None
            except Exception:
                style_lines = None
        return render_system_prompt(
            persona=persona_arg, tools=tools,
            public=(self.channel not in ("private", "console")
                    and not str(self.channel).startswith("qq_")),
            style_lines=style_lines,
        )

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
    _WORK_HINTS = (
        "查", "检索", "搜索", "查找", "找一下", "分析", "对比", "比较", "总结",
        "评估", "写", "生成", "做", "处理", "修复", "修", "检查", "测试", "启动",
        "部署",         "配置", "计划", "规划", "怎么", "如何", "为什么", "解释", "看下",
        "读取", "列出", "整理", "计算", "判断", "建议", "方案", "记得", "记忆",
        "记住", "保存", "写入", "之前", "上次", "昨天", "记录", "待办", "日程",
        "日记", "安排",
    )

    @classmethod
    def _want_work_mode(cls, text: str) -> bool:
        t = str(text or "").strip()
        return any(w in t for w in cls._WORK_HINTS)

    async def run_turn(self, text: str,
                       on_delta: Optional[Callable[[str], None]] = None,
                       mode: str = "auto",
                       pre_recall: Optional[list] = None,
                       images: Optional[list] = None) -> dict[str, Any]:
        self.memory.append_turn(role="user", text=text)
        contradictions = self._maybe_contradiction(text)
        from backend.target_style import capture_style_signal

        capture_style_signal(text, self.memory)
        system = self.render_system()
        llm_turn = self.llm_turn
        # images -> vision chat mode (no tool schema, no work reasoning)
        work = (not images) and (mode == "work" or (
            mode == "auto" and self._want_work_mode(text)))
        effort = "medium" if work else "none"
        if not self._llm_injected and work:
            from backend.target_daemon import LOCAL_BASE, LOCAL_MODEL
            from backend.target_orchestrator import (
                build_openai_compatible_llm_turn,
            )

            llm_turn = build_openai_compatible_llm_turn(
                base_url="http://127.0.0.1:8081/v1/chat/completions",
                api_key="", model="gemma-4-e4b",
                temperature=0.2,
                max_tokens=3000,
                fallback_base_url=LOCAL_BASE,
                fallback_model=LOCAL_MODEL,
                on_delta=on_delta,
                reasoning_effort="medium",
            )
        elif not self._llm_injected and on_delta is not None:
            from backend.target_daemon import LOCAL_BASE, LOCAL_MODEL
            from backend.target_orchestrator import (
                build_openai_compatible_llm_turn,
            )

            llm_turn = build_openai_compatible_llm_turn(
                base_url="http://127.0.0.1:8081/v1/chat/completions",
                api_key="", model="gemma-4-e4b",
                temperature=0.2, max_tokens=800,
                fallback_base_url=LOCAL_BASE,
                fallback_model=LOCAL_MODEL,
                on_delta=on_delta,
                reasoning_effort="none",
            )
        ctx_lines = []
        try:
            sl = self.memory.summary_line()
            if sl:
                ctx_lines.append(sl)
            if not work:
                import time as _t

                if pre_recall is not None:
                    # speculative prefetch (ledger 0226): recall already ran
                    # while the user was still speaking — reuse it, no re-query
                    for s_ in pre_recall[:3]:
                        ctx_lines.append("[此刻自然想起] 你以前提过：" + str(s_)[:150])
                else:
                    for hit in self.memory.contextual_recall(text, limit=3):
                        hid = str(hit.get("id", ""))
                        now = _t.time()
                        if now - self._ctx_recent.get(hid, 0.0) < 30.0:
                            continue
                        self._ctx_recent[hid] = now
                        ctx_lines.append(
                            "[此刻自然想起] 你以前提过：" +
                            str(hit.get("summary", ""))[:150])
        except Exception:
            pass
        result = await self.orchestrator.run(
            turn_text=text,
            system_prompt=system,
            llm_turn=llm_turn,
            history=self.history[-6:],  # latency (ledger 0206): cap in-context turns
            with_tools=work,
            early_context="\n".join(ctx_lines),
            images=images,
        )
        self.memory.append_turn(role="assistant", text=result.answer)
        if self.memory._summary_pending:
            self._summary_tasks.append(asyncio.ensure_future(self.memory.process_summary()))
        if (not self._reviewing and
                (len(self.history) // 2 - self._last_reviewed) >= 6):
            try:
                self._summary_tasks.append(
                    asyncio.ensure_future(self.review_once("auto")))
            except Exception:
                pass
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

    # ---------- review pipeline (ledger 0226): long-session -> durable memory
    async def review_once(self, reason: str = "manual") -> dict:
        """收口复盘：滚动摘要 → L2 候选提取 → 本地裁决入库 → 洞察提炼。
        可自动(每6轮)或 /review 手动；失败各自降级不抛。"""
        if self._reviewing:
            return {"reason": "busy"}
        self._reviewing = True
        out = {"reason": reason}
        try:
            await self.memory.process_summary()
        except Exception:
            pass
        try:
            recent = self.history[-16:]
            transcript = "\n".join(
                f"{'用户' if m.get('role') == 'user' else '元亨'}: "
                f"{str(m.get('content', ''))[:300]}"
                for m in recent)
            last_user = ""
            for m in reversed(recent):
                if m.get("role") == "user":
                    last_user = str(m.get("content", ""))[:600]
                    break
            if transcript.strip():
                items = await self.memory.submit_candidates(
                    text=last_user, transcript=transcript,
                    evidence_ref=f"review:{int(time.time())}", source="review")
                if items:
                    kept = await self.memory.adjudicate_async(
                        items, local_only=True)
                    out["candidates"] = len(items)
                    out["kept"] = len(kept or [])
        except Exception:
            pass
        try:
            out["reflect"] = await self.reflect()
        except Exception:
            pass
        self._last_reviewed = len(self.history) // 2
        self._reviewing = False
        return out


    # ---------- persistence (message-level, cache/sessions) ----------
    def _session_title(self) -> str:
        for m in self.history:
            if m.get("role") == "user":
                return str(m.get("content", "")).strip().replace("\n", " ")[:40]
        return "(空会话)"

    def save_session(self, name: str = "default") -> Path:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = SESSIONS_DIR / f"{name}.json"
        data = {
            "saved_at": time.time(),
            "title": self._session_title(),
            "turns": len(self.history) // 2,
            "history": self.history[-self.history_limit:],
        }
        # atomic write: never leave a half-written session file
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(path)
        return path

    @classmethod
    def list_sessions(cls) -> list[str]:
        if not SESSIONS_DIR.exists():
            return []
        return sorted(p.stem for p in SESSIONS_DIR.glob("*.json"))

    @classmethod
    def recent_sessions(cls, limit: int = 8) -> list[dict]:
        """Session archive metadata, newest first: [{name,title,turns,saved_at}]."""
        if not SESSIONS_DIR.exists():
            return []
        out = []
        for p in SESSIONS_DIR.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({
                "name": p.stem,
                "title": str(d.get("title") or "(未命名)")[:40],
                "turns": int(d.get("turns", len(d.get("history", [])) // 2)),
                "saved_at": float(d.get("saved_at", 0)),
            })
        return sorted(out, key=lambda x: x["saved_at"], reverse=True)[:limit]

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

    def style_tendencies(self) -> dict:
        from backend.target_style import style_ema

        items = self.memory.recall("风格偏好", limit=30)
        return style_ema(items)

    def status(self) -> dict:
        return {
            "history_turns": len(self.history) // 2,
            "l1_window": len(self.memory._turns),
            "l2_items": self.memory.health()["l2_items"],
            "persona_draft": bool(self._persona),
        }

    # ---------- proactive (autonomous action seed, ledger 0152) ----------
    def _recall_hints(self, extra: str = "", top: int = 3) -> list[str]:
        """Semantic 'self recall' material for autonomous moments (ledger 0226):
        surface related old memories so Yuanheng can bring them up herself."""
        try:
            from backend.vector_memory import semantic_any, semantic_l2

            recent = " ".join(
                str(m.get("content", ""))[:80] for m in self.history[-6:]
                if m.get("role") == "user")
            q = (str(extra) + " " + recent).strip()
            if not q:
                return []
            out = [str(h.get("summary", ""))[:70] for h in
                   semantic_l2(q, top=top, min_score=0.42)
                   if h.get("summary")]
            for d in semantic_any(q, ["diary"], top=2, min_score=0.45):
                t = str(d.get("text", ""))[:70]
                if t:
                    out.append("（日记）" + t)
            return out
        except Exception:
            return []

    def autonomy_prompt(self, question: str,
                        extra: str = "") -> str:
        import datetime as _dt

        now = _dt.datetime.now()
        lines = [question,
                 f"（现在是 {now:%Y-%m-%d %H:%M}）"]
        hints = self._recall_hints(extra or question)
        if hints:
            lines.append("也许可以想起这些旧记忆（若相关，自然地想起、带出，"
                         "或据此整理与提醒，不相关就忽略）：\n- "
                         + "\n- ".join(hints))
        return "\n".join(lines)

    async def proactive_tick(self, question: str = "根据最近积累的记忆，有什么值得主动整理或提醒的？",
                             extra: str = "") -> dict[str, Any]:
        """Self-initiated turn (no user prompt): model reviews memory and may
        use tools; nothing is executed without gated approval.
        Now includes semantic self-recall material (0226)."""
        prompt = self.autonomy_prompt(question, extra=extra)
        self.memory.append_turn(role="user", text=f"[自主] {question}")
        result = await self.orchestrator.run(
            turn_text=prompt,
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
可用命令: /help /status /new /think /exit
提示: 问项目历史/决策请让我查台账；要保存偏好会征求你同意。"""

_HELP = """命令列表:
  /help            本帮助
  /status          会话与记忆状态
  /think           自主回顾（我主动整理记忆）
  /save [name]     存档当前会话（默认 default）
  /load [name]     恢复某个会话
  /sessions        列出会话档案（最近优先）
  /new             开始新会话（当前会自动先存档）
  /exit            退出
直接输入即对话。写类操作（保存记忆）会先征求你 y/n 同意。"""


def _print_pending_dynamic(seen_file, shown: int) -> int:
    """Show Yuanheng's background activity (daemon notifications) before prompt."""
    import json
    import time as _t

    import pathlib as _p

    f = _p.Path(__file__).resolve().parent.parent / "cache" / "qqwatch" / "notifications.json"
    count = 0
    if f.exists():
        try:
            entries = json.loads(f.read_text(encoding="utf-8"))
            for e in entries:
                if _t.time() - float(e.get("ts", 0)) > 30:
                    continue
                count += 1
                print(f"[后台动态] {e.get('text', '')[:180]}")
        except Exception:
            pass
    return count


def cli_main() -> int:
    """Interactive REPL: python -m backend.target_entry"""
    import sys
    import traceback

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    session = ConversationSession(approver=_cli_approver_factory())
    _resumed = 0
    try:
        _resumed = session.load_session("default")
    except Exception:
        _resumed = 0
    print(BANNER)
    if _resumed:
        print(f"（已续聊上次会话，共 {_resumed} 条消息在档；/new 开新会话）")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    turns = 0
    try:
        while True:
            try:
                _print_pending_dynamic(None, 0)
                line = input("你> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line in ("/exit", "/quit", "exit", "quit"):
                try:
                    session.save_session("default")
                except Exception:
                    pass
                print("退出。会话已存档，回见。")
                break
            if line in ("/help", "help", "帮助"):
                print(_HELP)
                continue
            if line == "/status":
                print(session.status())
                continue
            if line in ("/new",):
                try:
                    session.save_session("default")
                except Exception:
                    pass
                session.history = []
                try:
                    session.memory._turns = []
                except Exception:
                    pass
                print("已开新会话（上一段已存入 default 档；/sessions 查看）")
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
                rows = ConversationSession.recent_sessions(10)
                if not rows:
                    print("还没有会话档案。")
                else:
                    import datetime as _dt
                    for i, r in enumerate(rows, 1):
                        ts = _dt.datetime.fromtimestamp(r["saved_at"]).strftime("%m-%d %H:%M")
                        print(f"  {i}. [{r['name']}] {r['turns']}轮 · {ts} · {r['title']}")
                continue
            if line in ("/reflect",):
                info = loop.run_until_complete(session.reflect())
                print(f"反思完成: {info}")
                continue
            if line == "/style":
                t = session.style_tendencies()
                from backend.target_style import active_style_lines

                print(f"风格倾向: {t}")
                print(f"注入句: {active_style_lines(t) or '(未达阈值)'} | 注入开关: {session.style_inject}")
                continue
            if line == "/style on":
                session.style_inject = True
                print("风格注入已开启（A/B 试听用）")
                continue
            if line == "/style off":
                session.style_inject = False
                print("风格注入已关闭")
                continue
            if line.startswith("/diary"):
                from backend.target_scheduler_tools import diary_list

                arg = line[6:].strip()
                n = int(arg) if arg.isdigit() else 3
                print(diary_list(limit=n))
                continue
            if line in ("/consolidate",):
                from backend.target_persona_loop import PersonaConsolidationLoop

                def _review(claim, kind, tier):
                    while True:
                        try:
                            ans = input(f"[{tier}|{kind}] 写入认知根基？\n  “{claim}”\n允许吗？(y/n): ").strip().lower()
                        except EOFError:
                            return False
                        if ans in ("y", "yes", "是"):
                            return True
                        if ans in ("n", "no", "否", ""):
                            return False
                        print("请输入 y/n")

                pc = PersonaConsolidationLoop(session.llm_turn, session.memory,
                                              approver=_review)
                info = loop.run_until_complete(pc.consolidate_once())
                print(f"沉淀闭环: {info}")
                continue
            if line == "/memory-upkeep":
                from backend.target_memory import TargetMemoryService

                svc = TargetMemoryService()
                rf = svc.review_reinforce()
                dec = svc.apply_belief_decay()
                dg = svc.apply_belief_downgrades()
                print(f"记忆风化（每周日 12:00 自动；手动触发）：巩固 {rf} 条，衰减 {dec} 条，降权 {dg} 条（不删除）")
                continue
            if line == "/stabilize":
                from backend.target_stabilization import cli_print as _stab

                _stab(session.memory)
                continue
            if line == "/suggest":
                from backend.target_signals import suggest as _sugg
                from backend.env_loader import ensure_env_loaded
                from backend.target_orchestrator import build_openai_compatible_llm_turn
                import os, json as _j

                ensure_env_loaded()
                llm = build_openai_compatible_llm_turn(
                    api_key=os.getenv("DEEPSEEK_API_KEY", ""), model="deepseek-chat",
                    temperature=0.2, max_tokens=900,
                    fallback_base_url="http://127.0.0.1:11434/v1/chat/completions",
                    fallback_model="qwen2.5:3b")
                out = loop.run_until_complete(_sugg(llm))
                print(_j.dumps(out, ensure_ascii=False, indent=1))
                continue
            if line == "/review-cognition":
                from backend.target_persona_loop import PENDING_FILE

                if not PENDING_FILE.exists():
                    print("没有待确认的认知条目")
                    continue
                import json

                pending = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
                if not pending:
                    print("没有待确认的认知条目")
                    continue
                approved = []
                rest = []
                for d in pending:
                    while True:
                        try:
                            ans = input(f"[{d.get('tier')}|{d.get('kind')}] 写入认知根基？\n  “{d.get('claim')}”\n允许吗？(y/n): ").strip().lower()
                        except EOFError:
                            ans = "n"
                        if ans in ("y", "yes", "是"):
                            approved.append(d)
                            break
                        if ans in ("n", "no", "否", ""):
                            rest.append(d)
                            break
                        print("请输入 y/n")
                if approved:
                    from backend.target_persona_loop import PersonaConsolidationLoop

                    pc = PersonaConsolidationLoop(session.llm_turn, session.memory)
                    version = pc._next_version(pc._foundation_text())
                    used = [str(i) for d in approved for i in d.get("item_ids", [])]
                    n = pc._apply(approved, version, used)
                    print(f"已批准写入 {n} 条 → 认知根基 v{version}")
                PENDING_FILE.write_text(json.dumps(rest, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
                print(f"待确认剩余 {len(rest)} 条")
                continue
            if line in ("/think", "/proactive"):
                try:
                    info = loop.run_until_complete(session.proactive_tick())
                    print("元亨(自主)> " + info["answer"][:300])
                except Exception as exc:
                    print(f"(自主回顾失败: {type(exc).__name__})")
                continue
            if line in ("/review",):
                info = loop.run_until_complete(session.review_once("manual"))
                print(f"[复盘] {info}", flush=True)
                continue
            if line in ("/persona-propose",):
                from backend.persona_tune import propose

                print(f"[人格调优建议] {propose()}", flush=True)
                continue
            if line in ("/persona-apply",):
                from backend.persona_tune import apply, pending

                items = pending()
                if not items:
                    print("没有待批的人格调优建议")
                    continue
                ok = []
                for it in items:
                    try:
                        ans = input(
                            f"[维度{it['index']}] {it['old']}\n  → {it['new']}"
                            f"\n（依据：{it.get('reason','')}）应用？(y/n): "
                        ).strip().lower()
                    except EOFError:
                        ans = "n"
                    if ans in ("y", "yes", "是"):
                        ok.append(it["id"])
                print("[应用结果]", apply(ok), flush=True)
                continue
            turns += 1
            print("元亨> ", end="", flush=True)
            info = loop.run_until_complete(session.run_turn(
                line,
                on_delta=lambda chunk: (print(chunk, end="", flush=True)),
            ))
            print()
            try:
                session.save_session("default")
            except Exception:
                pass
            for u in info["tool_uses"]:
                if not u["ok"]:
                    print(f"  [工具失败] {u['name']}: {u['error']}")
            try:
                from backend.target_scheduler_tools import skill_hint

                h = skill_hint(line, [u.get("name", "") for u in info["tool_uses"]])
                if h:
                    print(h)
            except Exception:
                pass
    finally:
        try:
            session.save_session()
        except Exception:
            pass
        loop.close()
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(cli_main())
