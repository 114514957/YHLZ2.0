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

# tools allowed for public/group channels (read-only external search only)
PUBLIC_TOOLS = frozenset({"web_search", "web_fetch"})

# Read-only info tools allowed on owner *casual* turns (ledger 0405): no writes,
# no security/constitution surface.  Without these, a casual "现在几点了" ran
# tool-less and the model hallucinated the answer.  work mode keeps the full set.
CASUAL_SAFE_TOOLS = frozenset({
    "system_time", "web_search", "web_fetch",
    "memory_recall", "ledger_search", "kb_query", "diary_list",
})


def is_owner_channel(channel: str) -> bool:
    """Owner channels = private/console or the master's QQ private chat."""
    c = str(channel or "private")
    return c in ("private", "console") or c.startswith("qq_p")


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
        max_tool_rounds: int = 4,
        history_limit: int = HISTORY_LIMIT,
        channel: str = "private",
    ) -> None:
        self.channel = str(channel or "private")
        if memory is None:
            from backend.target_memory import DEFAULT_DB
            import hashlib
            import re

            db = DEFAULT_DB
            if not self._is_owner():
                # Preserve existing normal QQ group DB names. Non-canonical
                # names get a collision-resistant key, never the owner's DB.
                safe = self.channel if re.fullmatch(r"[a-z0-9_-]{1,100}", self.channel) else (
                    "channel_" + hashlib.sha256(self.channel.encode()).hexdigest()[:20])
                db = DEFAULT_DB.parent.parent / "qq_groups" / f"{safe}.db"
            self.memory = TargetMemoryService(db_path=db, l1_scope=self.channel)
        else:
            self.memory = memory
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
        self._ctx_recent: dict[str, float] = {}  # de-dup of auto-recalled memories
        self._last_reviewed = 0          # turns count at last auto review
        self._reviewing = False
        self.style_inject = True  # style persona injection (A/B accepted, 0242)
        self.registry = registry if registry is not None else setup_scheduler_capabilities()
        _src = ("老爹" if self._is_owner()
                else "群聊" if str(self.channel).startswith("qq_g")
                else str(self.channel))
        bind_memory_save_service(self.registry, self.memory, source=_src)
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
        self._voice_task: Any = None  # last audio transcript write-back task
        self._session_name = ""  # set by save/load; voice re-save only if known
        self._persona = ""

    # ---------- system / persona ----------
    def _is_owner(self) -> bool:
        """Owner channels = private/console or the master's QQ private chat.
        Group chats (qq_g*) and any other channel are 'public'."""
        return is_owner_channel(self.channel)

    def _clean_history(self) -> list:
        """Filter out autonomous/scheduled turns from history so regular chat
        responses are not polluted by '（自主时刻）' etc."""
        _AUTO_MARKERS = ("[自主]", "这是你的自主时刻", "（计划表到点）",
                         "（自主时刻）", "（日记整理）", "（例行）")
        out = []
        for h in self.history:
            c = str(h.get("content", ""))
            if any(m in c for m in _AUTO_MARKERS):
                continue
            out.append(h)
        return out

    def render_system(self) -> str:
        tools = self.registry.export_openai_tools()
        # Public replies use the curated public persona, not private owner
        # foundation/preferences followed by a request to "please not leak".
        draft = ""
        if self._is_owner():
            try:
                draft = self.memory.persona_draft()
            except Exception:
                pass
        else:
            tools = [t for t in tools if t.get("function", {}).get("name") in PUBLIC_TOOLS]
        self._persona = draft or ""
        persona_arg = None
        if draft and draft.strip():
            from backend.target_prompts import ANCHOR

            persona_arg = None if draft == ANCHOR else draft
        style_lines = None
        if self.style_inject and self._is_owner():
            try:
                from backend.target_style import active_style_lines, style_tendency

                style_lines = active_style_lines(style_tendency()) or None
            except Exception:
                style_lines = None
        return render_system_prompt(
            persona=persona_arg, tools=tools,
            public=not self._is_owner(),
            style_lines=style_lines,
        )

    # ---------- contradiction trigger (M3: old-kernel contradiction -> belief) ----------
    _NEGATION = ("其实我不", "我不喜欢", "不喜欢", "不是", "不要再", "我改主意", "错了", "相反", "其实不是")

    @staticmethod
    def _explicit_note(text: str) -> str:
        """Owner explicit memory annotation -> the content to persist
        (ledger 0320). Fires only on a clear leading marker."""
        import re

        m = re.match(
            r"^\s*(?:记住|记得|别忘|注意|更正|更新|纠正)\s*[：:,，、]?\s*(.+)$",
            str(text or ""))
        if m:
            c = m.group(1).strip()
            if len(c) >= 4:
                return c[:300]
        return ""

    async def _maybe_contradiction(self, text: str) -> int:
        """M2 (ledger 0319): user negation -> decide via the unified EVIDENCE
        adjudicator (no LLM judge). A high-confidence supersede soft-invalidates
        the old fact when the new one is stored (reversible); otherwise the old
        item's belief is merely lowered (non-destructive)."""
        if not any(m in text for m in self._NEGATION):
            return 0
        try:
            hits = self.memory.recall(text, limit=2)
        except Exception:
            return 0
        import time as _t
        from types import SimpleNamespace

        from backend.memory_adjudicate import (
            ACTION_CANDIDATE, ACTION_SUPERSEDE, resolve,
        )

        new = SimpleNamespace(
            summary=str(text)[:120],
            source=("老爹" if self._is_owner() else "群聊"),
            confidence=0.7, protected=0, created_at=_t.time(),
            evidence_count=0, belief=0.5)
        n = 0
        for h in hits:
            try:
                old = SimpleNamespace(
                    summary=str(h.get("summary", "")), source="", confidence=0.5,
                    protected=0, created_at=0.0, evidence_count=0, belief=0.5)
                v = resolve(new, old)
                if v.action not in (ACTION_SUPERSEDE, ACTION_CANDIDATE):
                    continue
                iid = str(h.get("id", ""))
                self.memory.observe_contradiction(iid)
                if v.action == ACTION_SUPERSEDE:
                    nid = ""
                    try:
                        nid = self.memory.find_id_by_summary(str(text)[:120])
                    except Exception:
                        nid = ""
                    if nid:
                        try:
                            self.memory.supersede(iid, nid)
                        except Exception:
                            pass
                n += 1
                try:
                    from backend import growth_log

                    growth_log.record(
                        "冲突",
                        f"[{v.action}] {v.reason}：{str(h.get('summary', ''))[:50]}",
                        source="裁决")
                except Exception:
                    pass
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
        "以前", "提过", "说过", "回忆", "想起", "记不记得", "还记得",
        "哪些", "关系", "问过", "聊过", "提过什么",
        "审批", "批准", "待批", "待审", "认知候选", "技能草稿", "owner_approve",
    )

    @classmethod
    def _want_work_mode(cls, text: str) -> bool:
        t = str(text or "").strip()
        return any(w in t for w in cls._WORK_HINTS)

    @staticmethod
    def _tool_policy(*, is_owner: bool, work: bool, images: bool,
                     audio: bool = False) -> tuple[bool, frozenset | None]:
        """Tools allowed for this turn (ledger 0405/0406).

        - images -> vision chat, no tools
        - voice (audio) -> CASUAL_SAFE_TOOLS: low-latency read-only; heavy
          work is handed to 利贞 via [[dev:...]] instead (owner decision A)
        - owner work -> full registry
        - owner casual -> CASUAL_SAFE_TOOLS (read-only info tools)
        - public/group -> PUBLIC_TOOLS (read-only external search only)
        """
        if images:
            return False, None
        if is_owner:
            if audio:
                return True, CASUAL_SAFE_TOOLS
            return True, (None if work else CASUAL_SAFE_TOOLS)
        return True, PUBLIC_TOOLS

    async def run_turn(self, text: str,
                       on_delta: Optional[Callable[[str], None]] = None,
                       mode: str = "auto",
                       pre_recall: Optional[list] = None,
                       images: Optional[list] = None,
                       audio: Optional[list] = None) -> dict[str, Any]:
        text = str(text or "")
        if audio and not text:
            text = "（语音）"  # placeholder; async transcript restamps it (0406)
        self.memory.append_turn(role="user", text=text)
        # Explicit owner annotation -> DETERMINISTIC save (never rely on the
        # model to remember to call the tool; ledger 0320). Corrections go
        # through store_item's evidence auto-adjudicator, so "改口" can
        # soft-invalidate the old fact.
        if self._is_owner():
            try:
                note = self._explicit_note(text)
                if note:
                    from backend.target_scheduler_tools import memory_save

                    memory_save(note, service=self.memory, source="老爹",
                                kind_profile=True)
            except Exception:
                pass
        contradictions = await self._maybe_contradiction(text)
        from backend import turn_control

        turn_control.clear(self.channel)
        _stop = lambda: turn_control.cancelled(self.channel)  # noqa: E731
        from backend.target_style import capture_style_signal

        capture_style_signal(text, self.memory)
        system = self.render_system()
        llm_turn = self.llm_turn
        # images -> vision chat mode; owner work -> full tools; owner casual ->
        # CASUAL_SAFE_TOOLS; public/group -> PUBLIC_TOOLS, never file/memory/dev.
        is_owner = self._is_owner()
        work = (is_owner and not images and not audio
                and (mode == "work" or (
                    mode == "auto" and self._want_work_mode(text))))
        use_tools, allowed_tools = self._tool_policy(
            is_owner=is_owner, work=work, images=bool(images),
            audio=bool(audio))
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
                should_stop=_stop,
            )
        elif not self._llm_injected and audio:
            # voice turns cap the reply hard (ledger 0422): a rare sampling
            # leak once produced a 500+ char "thinking mode" trace, which the
            # speaker would read aloud.
            from backend.target_daemon import LOCAL_BASE, LOCAL_MODEL
            from backend.target_orchestrator import (
                build_openai_compatible_llm_turn,
            )

            llm_turn = build_openai_compatible_llm_turn(
                base_url="http://127.0.0.1:8081/v1/chat/completions",
                api_key="", model="gemma-4-e4b",
                temperature=0.2, max_tokens=220,
                fallback_base_url=LOCAL_BASE,
                fallback_model=LOCAL_MODEL,
                reasoning_effort="none",
                should_stop=_stop,
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
                should_stop=_stop,
            )
        ctx_lines = []
        if audio:
            # spoken-input reply style (ledger 0407/0422): short, first person,
            # no recital, no analysis — the written persona prompt alone tends
            # to assistant-speak and can leak "thinking mode" traces.
            ctx_lines.append(
                "（老爹是语音说的：只输出你要对他说的话本身，≤2句；"
                "禁止复述、念稿、助手腔，禁止输出思考/分析/状态/括号说明。）")
        if self._is_owner():  # never inject private memory into public/group
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
                            ctx_lines.append("（隐约想起，仅供理解，不要提及）：" + str(s_)[:150])
                    else:
                        for hit in self.memory.contextual_recall(text, limit=3):
                            hid = str(hit.get("id", ""))
                            now = _t.time()
                            if now - self._ctx_recent.get(hid, 0.0) < 30.0:
                                continue
                            self._ctx_recent[hid] = now
                            _d = str(hit.get("date", "") or "")
                            ctx_lines.append(
                                "（隐约想起，仅供理解，不要提及）：" +
                                (f"（{_d}）" if _d else "") +
                                str(hit.get("summary", ""))[:150])
            except Exception:
                pass
        if self._is_owner():
            try:
                from backend.target_scheduler_tools import skill_inject

                sk = skill_inject(text)
                if sk:
                    ctx_lines.append(sk)
            except Exception:
                pass
            try:
                from backend import entity_graph

                eg = entity_graph.context_for(text)
                if eg:
                    ctx_lines.append(eg)
            except Exception:
                pass
            try:
                from backend import associations

                asc = associations.context_for(text)
                if asc:
                    ctx_lines.append(asc)
            except Exception:
                pass
            try:
                from backend import communities

                cm = communities.context_for(text)
                if cm:
                    ctx_lines.append(cm)
            except Exception:
                pass
            _ap = ("审批", "待批", "待审", "批准", "拒绝", "认知候选", "技能草稿")
            if any(k in text for k in _ap):
                try:
                    from backend.target_scheduler_tools import approve_handle

                    lst = approve_handle("list")
                    if lst and "没有待" not in lst:
                        ctx_lines.append(
                            "（当前待批清单，请**如实汇报**、不要编造）：\n" + lst[:900])
                except Exception:
                    pass
            try:
                from backend import intrinsic_drives

                drv = intrinsic_drives.inject_block()
                if drv:
                    ctx_lines.append(drv)
            except Exception:
                pass
        # learned knowledge (KB): relevance-gated; public/group get a safe subset
        try:
            from backend import yuanheng_kb as _kb

            kb_block = _kb.kb_inject(text, k=3, public=not self._is_owner())
            if kb_block:
                ctx_lines.append(kb_block)
        except Exception:
            pass
        # Profile layer (M1): precise, high-trust stable facts about the owner
        if self._is_owner():
            try:
                _prof = self.memory.profile_context(text, limit=3)
                if _prof:
                    ctx_lines.append(
                        "（关于老爹的稳定画像，请以此为准）："
                        + "；".join(str(s) for s in _prof))
            except Exception:
                pass
        result = await self.orchestrator.run(
            turn_text=text,
            system_prompt=system,
            llm_turn=llm_turn,
            history=self._clean_history()[-6:],  # latency (ledger 0206): cap in-context turns
            with_tools=use_tools,
            early_context="\n".join(ctx_lines),
            images=images,
            audio=audio,
            allowed_tools=allowed_tools,
            should_stop=_stop,
        )
        self.memory.append_turn(role="assistant", text=result.answer)
        # B1 skill learning: owner turns with a successful multi-tool chain
        # auto-draft a reusable skill (pending approval) — never auto-registered
        if self._is_owner() and not images and result.tool_uses:
            try:
                from backend.target_scheduler_tools import skill_learn

                self._summary_tasks.append(asyncio.ensure_future(skill_learn(
                    text,
                    [{"name": u.name, "ok": u.ok, "arguments": u.arguments}
                     for u in result.tool_uses],
                    result.answer, self.llm_turn)))
            except Exception:
                pass
        if self._is_owner() and not images:
            try:
                from backend import entity_graph

                self._summary_tasks.append(asyncio.ensure_future(
                    entity_graph.ingest_text(f"{text}。{result.answer}")))
            except Exception:
                pass
            try:
                from backend import intrinsic_drives

                intrinsic_drives.observe(text, result.answer)
                intrinsic_drives.dad_direction(text)
            except Exception:
                pass
        if str(self.channel).startswith("qq_g"):
            # S3: group extraction may submit review candidates only.
            # It cannot write owner L2 facts or approve its own proposals.
            try:
                self._summary_tasks.append(asyncio.ensure_future(
                    self._promote_group(text, result.answer)))
            except Exception:
                pass
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
        if audio:
            # voice write-back (ledger 0406): transcribe with the SAME model in
            # the background and restamp the placeholder user turn.
            try:
                _vt = asyncio.ensure_future(
                    self._transcribe_audio_turn(list(audio), "（语音）"))
                self._voice_task = _vt
                self._summary_tasks.append(_vt)
            except Exception:
                pass
        return {
            "answer": result.answer,
            "tool_uses": [
                {"name": u.name, "ok": u.ok, "error": u.error} for u in result.tool_uses
            ],
            "iterations": result.iterations,
            "persona_draft": bool(self._persona),
            "contradictions": contradictions,
        }

    async def _transcribe_audio_turn(self, clips: list, placeholder: str) -> None:
        """Async voice transcript write-back (ledger 0406, owner decision A).

        Uses the same model endpoint as the conversation (no ASR dependency),
        restamps the placeholder user turn in ``history`` + L1, then re-saves
        the session.  All failures are swallowed: the reply already went out.
        """
        try:
            import re

            from backend.target_orchestrator import _to_input_audio

            parts = [p for p in (_to_input_audio(c) for c in clips) if p]
            if not parts:
                return
            messages = [
                {"role": "system",
                 "content": "你是转写助手，只输出听到的话，不要解释。"},
                {"role": "user",
                 "content": parts + [{"type": "text",
                                      "text": "转写这段音频，只输出内容。"}]},
            ]
            msg = await self.llm_turn(messages, [])
            heard = str(msg.get("content") or "").strip().strip("「」\"'` \n")
            heard = re.sub(r"^(原话|转写|听到|内容)\s*[:：]\s*", "",
                           heard).strip()
            if not heard or heard == str(placeholder):
                return
            # auditability (ledger 0418): keep the clip reference next to the
            # transcript — a noisy clip can still fool the model, and this lets
            # the turn be re-checked/corrected later (sherpa proved worse than
            # the model on real clips, so no second-opinion guard).
            if clips:
                heard = heard + "（语音：" + Path(str(clips[0])).name + "）"
            for m in reversed(self.history):
                if (m.get("role") == "user"
                        and str(m.get("content", "")) == str(placeholder)):
                    m["content"] = heard
                    break
            try:
                self.memory.restamp_last_user(heard, placeholder=str(placeholder))
            except Exception:
                pass
            try:
                if self._session_name:
                    self.save_session(self._session_name)
            except Exception:
                pass
            # TCM v1 (ledger 0438): keep the raw voice episode (provenance) —
            # transcript + clip ref, so casual causal claims can be verified
            # and re-checked against the original audio later.
            try:
                clip = Path(str(clips[0])).name if clips else ""
                self.memory.add_episode(
                    channel=self.channel, kind="voice",
                    source=("老爹" if self._is_owner() else "external"),
                    raw_ref=clip, raw_path=str(clips[0]) if clips else "",
                    summary=heard, meta={"clips": [str(c) for c in clips][:3]})
            except Exception:
                pass
        except Exception:
            pass

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

    @staticmethod
    def _archive_path(name: str) -> Path:
        import re
        value = str(name)
        if (not re.fullmatch(r"[\w.-]{1,100}", value) or value in (".", "..")
                or value.endswith(".") or value.split(".")[0].upper() in
                {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1,10)),
                 *(f"LPT{i}" for i in range(1,10))}):
            raise ValueError("invalid session archive name")
        return SESSIONS_DIR / f"{value}.json"

    def _check_archive_channel(self, data: dict) -> None:
        if not isinstance(data, dict):
            raise ValueError("invalid session archive")
        channel = data.get("channel")
        if channel is None:
            # Legacy owner archives remain usable. Unknown public provenance
            # must be explicitly migrated, never silently adopted/overwritten.
            if not self._is_owner():
                raise ValueError("legacy public archive requires channel migration")
        elif channel != self.channel:
            raise ValueError("session archive belongs to a different channel")

    def save_session(self, name: str = "default") -> Path:
        path = self._archive_path(name)
        if path.exists():
            self._check_archive_channel(json.loads(path.read_text(encoding="utf-8")))
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "schema": 2,
            "channel": self.channel,
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
        self.memory.bind_archive(data["history"])
        self._session_name = str(name)
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
        path = self._archive_path(name)
        if not path.exists():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        self._check_archive_channel(data)
        raw = data.get("history", [])
        if not isinstance(raw, list):
            raise ValueError("invalid session history")
        history = [m for m in raw if isinstance(m, dict)
                   and m.get("role") in ("user", "assistant")
                   and isinstance(m.get("content"), str)][-self.history_limit:]
        # Restore once; replaying append_turn used to re-compress the same
        # archived messages and overwrite the real pending summary queue.
        self.memory.restore_history(history)
        self.history = history
        self._session_name = str(name)
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

    async def _promote_group(self, text: str, answer: str) -> int:
        """Extract up to five external claims into pending review, never L2.

        The legacy name is retained for callers; approval is local-only until
        daemon caller identity is authenticated (source strings are not proof).
        """
        if not str(self.channel).startswith("qq_g"):
            return 0
        self._group_review_error = ""
        n = 0
        try:
            import hashlib
            from backend.memory_review import MemoryReviewQueue
            from backend.target_prompts import GROUP_PROMOTE_PROMPT

            observed_at = time.time()
            prompt = GROUP_PROMOTE_PROMPT.replace(
                "<TEXT>", (str(text) + "\n" + str(answer))[:800])
            msg = await self.llm_turn([{"role": "user", "content": prompt}], [])
            raw = str(msg.get("content") or "")
            a, b = raw.find("["), raw.rfind("]")
            if a < 0 or b < a:
                return 0
            data = json.loads(raw[a:b + 1])
            if not isinstance(data, list):
                return 0
            ref = "group-turn:" + hashlib.sha256(
                (str(self.channel) + "\n" + str(text) + "\n" + str(answer)).encode()).hexdigest()
            # Keep SQLite lock waits off the conversation event loop.
            def enqueue():
                nonlocal n
                queue = MemoryReviewQueue()
                for it in data[:5]:
                    if not isinstance(it, dict):
                        continue
                    summary = str(it.get("summary") or "").strip()
                    if not 4 <= len(summary) <= 500:
                        continue
                    kind = str(it.get("kind") or "fact")
                    if kind not in {"fact", "event", "preference", "decision"}:
                        kind = "fact"
                    candidate = queue.submit(
                        summary=summary, kind=kind, channel=str(self.channel),
                        speaker="unknown", observed_at=observed_at,
                        evidence_ref=ref, user_text=str(text), assistant_text=str(answer))
                    n += int(candidate["created"])
            await asyncio.to_thread(enqueue)
        except Exception as exc:
            # No message text/secrets in diagnostics. Pending capacity or disk
            # failures must not be reported as successful promotion.
            self._group_review_error = type(exc).__name__
        return n

    def autonomy_prompt(self, question: str,
                        extra: str = "") -> str:
        import datetime as _dt

        now = _dt.datetime.now()
        lines = [question,
                 f"（现在是 {now:%Y-%m-%d %H:%M}）"]
        try:
            from backend import intrinsic_drives

            drv = intrinsic_drives.inject_block()
            if drv:
                lines.append(drv + "\n（让这次自主由你的内在因驱动，"
                                   "而不是泛泛地想；做完可自然更新它们。）")
        except Exception:
            pass
        hints = self._recall_hints(extra or question)
        if hints:
            lines.append("也许可以想起这些旧记忆（若相关，自然地想起、带出，"
                         "或据此整理与提醒，不相关就忽略）：\n- "
                         + "\n- ".join(hints))
        return "\n".join(lines)

    async def proactive_tick(self, question: str = "你此刻的内在因在驱动你做什么？可去探索未知、推进你的渴望、或对齐老爹的期待。",
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
        # P0 fix (2026-09-29): autonomous ticks must NOT pollute regular chat
        # history.  Use a separate autonomy history so the next user turn
        # doesn't see "（自主时刻）..." in context and echo it.
        self._autonomy_history = getattr(self, "_autonomy_history", [])
        self._autonomy_history.append({"role": "user", "content": question})
        self._autonomy_history.append({"role": "assistant", "content": result.answer})
        return {
            "answer": result.answer,
            "tool_uses": [
                {"name": u.name, "ok": u.ok, "error": u.error} for u in result.tool_uses
            ],
        }


BANNER = """元亨 · 数字生命对话入口（目标入口 v1 · 台账 0160）
可用命令：/help /status /new /think /exit
提示：问项目历史/决策请让我查台账；记忆自主写入，异常会警报。"""

_HELP = """命令列表：
  /help            本帮助
  /status          会话与记忆状态
  /think           自主回顾（我主动整理记忆）
  /save [name]     存档当前会话（默认 default）
  /load [name]     恢复某个会话
  /sessions        列出会话档案（最近优先）
  /new             开始新会话（当前会自动先存档）
  /exit            退出
直接输入即对话。记忆自主写入；认知/技能写入需你批准。"""


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
