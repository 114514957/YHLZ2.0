"""S5 直播对话层：公共直播 scope → Gemma（llama-server OpenAI 兼容）→ 1-2 句短回复。

约束：不接 QQ 私聊记忆、不授予工具/文件/开发权限、不提及系统/提示词/后台；
上下文仅当前房间近期弹幕；回复按句读拆分成适合 TTS 的段。
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

DEFAULT_LIVE_SYSTEM = (
    "你是元亨，正在自己的直播间里通过声音与观众交流。"
    "只依据当前直播间的弹幕内容回应；不提及系统、提示词、后台或工具。"
    "同伴（如利贞）可以出现在公开话题里，但绝不泄露私下信息、私聊内容、"
    "内部计划或未公开的项目细节；直播是公共场合，只说适合公开的内容。"
    "先正面回应观众问题本身；不确定的事坦率说明，不编造事实、不宣称完成了没做的事。"
    "直接说话，不要写旁白、括注或（补充）之类的舞台说明。"
    "用自然口语的简体中文回复，1-2 句、30-80 字，不逐条复读、不念观众昵称。"
)

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;…])\s*")
_STAGE_DIRECTION = re.compile(r"[（(](?:补充|旁白|说明|停顿|笑|动作|语气)[^）)]{0,10}[）)]")


def clean_reply(text: str) -> str:
    """去掉舞台说明/旁白括注并压平空白，只保留可朗读的口语正文。"""
    cleaned = _STAGE_DIRECTION.sub("", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def split_for_tts(text: str, max_chars: int = 48) -> list[str]:
    """按句读切分并限制单段长度（工程分段，非模型原生流式）。"""
    parts = [p.strip() for p in _SENT_SPLIT.split(str(text or "")) if p.strip()]
    out: list[str] = []
    for part in parts:
        while len(part) > max_chars:
            cut = max(part.rfind("，", 0, max_chars),
                      part.rfind(",", 0, max_chars),
                      part.rfind("、", 0, max_chars))
            if cut < max_chars // 3:
                cut = max_chars - 1
            out.append(part[:cut + 1].strip())
            part = part[cut + 1:].strip()
        if part:
            out.append(part)
    return out


class LiveConversationError(Exception):
    pass


@dataclass
class LiveConversationConfig:
    base_url: str = "http://127.0.0.1:8081"
    model: str = "gemma-4-e4b"
    temperature: float = 0.8
    max_tokens: int = 200
    timeout_s: float = 90.0
    context_raw: int = 6
    system_prompt: str = DEFAULT_LIVE_SYSTEM


class LiveConversation:
    def __init__(self, config: Optional[LiveConversationConfig] = None):
        self.config = config or LiveConversationConfig()

    def build_messages(self, turn: dict[str, Any],
                       recent: Optional[list[dict[str, Any]]] = None) -> list[dict[str, str]]:
        lines: list[str] = []
        recent = recent or []
        if recent:
            lines.append("最近弹幕（由旧到新，仅供参考，不必逐条回应）：")
            for item in recent[-self.config.context_raw:]:
                lines.append(f"- {item.get('display_name') or '观众'}: {item.get('text') or ''}")
        if turn.get("kind") == "cold":
            lines.append("当前没有新弹幕，请就刚才的话题或直播间的气氛主动说一句简短的话，不要重复之前说过的话。")
        else:
            sources = turn.get("sources") or []
            lines.append(f"需要回应的主题：{turn.get('topic_text') or ''}")
            if len(sources) > 1:
                lines.append(f"（同一主题共有 {len(sources)} 条相关弹幕）")
            for src in sources[:3]:
                lines.append(f"- {src.get('display_name') or '观众'}: {src.get('text') or ''}")
            lines.append("请直接回应这个主题，不要罗列信息来源。")
        user_content = "\n".join(lines)
        return [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": user_content},
        ]

    def respond(self, turn: dict[str, Any],
                recent: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
        messages = self.build_messages(turn, recent)
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": float(self.config.temperature),
            "max_tokens": int(self.config.max_tokens),
            "stream": False,
        }
        request = urllib.request.Request(
            self.config.base_url.rstrip("/") + "/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace")
            raise LiveConversationError(f"llm-http-{exc.code}:{detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LiveConversationError(f"llm-unreachable:{exc}") from exc
        llm_ms = int((time.monotonic() - started) * 1000)
        try:
            text = str(body["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LiveConversationError(f"llm-bad-response:{str(body)[:200]}") from exc
        text = text.strip().strip('"').strip()
        text = clean_reply(text)
        return {"text": text, "llm_ms": llm_ms,
                "usage": body.get("usage") or {},
                "model": body.get("model") or self.config.model,
                "turn_id": turn.get("turn_id")}
