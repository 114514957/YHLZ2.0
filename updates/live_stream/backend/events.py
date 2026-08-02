from __future__ import annotations
import base64
from typing import Any, Dict, List, Optional, Type
from .models import LiveSettings

def _pick(d: dict, candidates: List[str]):
    for k in candidates:
        cur = d
        ok = True
        for part in k.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, "", []):
            return cur
    return None

class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"

def _fmt(tpl: str, ctx: dict) -> str:
    try:
        return tpl.format_map(SafeDict(**ctx))
    except Exception:
        return tpl

class LiveEvent:
    def __init__(self, raw: Dict[str, Any]) -> None:
        self._full = raw
        self.raw = raw.get("data") or raw
        self.event_type = (raw.get("type") or raw.get("cmd") or "").strip() or "UNKNOWN"

    def is_allowed(self, s: LiveSettings) -> bool:
        return False

    def normalize(self) -> Dict[str, Any]:
        return {}

    def format(self, s: LiveSettings) -> str:
        return ""

    def to_payload(self, s: LiveSettings) -> Optional[Dict[str, Any]]:
        if not self.is_allowed(s):
            return None
        text = self.format(s)
        if not isinstance(text, str) or not text:
            return None
        return {"type": self.event_type, "text": text, "raw": self._full}

class DanmakuEvent(LiveEvent):
    def is_allowed(self, s: LiveSettings) -> bool:
        return bool(s.enable_danmaku)

    def normalize(self) -> Dict[str, Any]:
        data = self.raw
        info = data["info"]
        content = info[1]
        uname = info[2][1]
        is_emoticon = bool(isinstance(info[0][13], Dict) and info[0][13].get("emoticon_unique", ""))
        if is_emoticon and content.startswith("[") and content.endswith("]"):
            content = content[1:-1]
            content = content.split("_")[-1]
        return {"uname": uname, "content": content, "is_emoticon": is_emoticon}

    def format(self, s: LiveSettings) -> str:
        return _fmt(s.template_danmaku, self.normalize())

class SuperChatEvent(LiveEvent):
    def is_allowed(self, s: LiveSettings) -> bool:
        if not s.enable_super_chat:
            return False
        price = self.raw.get("price", 0)
        return price >= s.min_price_yuan

    def normalize(self) -> Dict[str, Any]:
        data = self.raw
        uname = _pick(data, ["uname", "username", "user_info.uname", "user_info.username"])
        content = data.get("message", "")
        price = data.get("price", 0)
        return {"uname": uname, "content": content, "price": price}

    def format(self, s: LiveSettings) -> str:
        return _fmt(s.template_super_chat, self.normalize())

class SendGiftEvent(LiveEvent):
    def is_allowed(self, s: LiveSettings) -> bool:
        if not s.enable_gift:
            return False
        price = self.raw.get("total_coin", 0) / 1000
        if not self.raw.get("is_first", True):
            return False
        return price >= s.min_price_yuan

    def normalize(self) -> Dict[str, Any]:
        data = self.raw
        uname = _pick(data, ["uname", "username", "user_info.uname", "user_info.username"])
        gift_name = _pick(data, ["gift_name", "giftName"])
        num = data.get("num", 1)
        price = data.get("total_coin", 0) / 1000
        return {"uname": uname, "gift_name": gift_name, "num": num, "price": price}

    def format(self, s: LiveSettings) -> str:
        n = self.normalize()
        tpl = s.template_gift
        return _fmt(tpl, n)

class ComboSendEvent(SendGiftEvent):
    def is_allowed(self, s: LiveSettings) -> bool:
        if not s.enable_gift:
            return False
        price = self.raw.get("combo_total_coin", 0) / 1000
        return price >= s.min_price_yuan

    def normalize(self) -> Dict[str, Any]:
        data = self.raw
        uname = _pick(data, ["uname", "username", "user_info.uname", "user_info.username"])
        gift_name = _pick(data, ["gift_name", "giftName"])
        num = data.get("total_num", 1)
        price = data.get("combo_total_coin", 0) / 1000
        return {"uname": uname, "gift_name": gift_name, "num": num, "price": price}

class GuardBuyEvent(LiveEvent):
    def is_allowed(self, s: LiveSettings) -> bool:
        return bool(s.enable_guard)

    def normalize(self) -> Dict[str, Any]:
        data = self.raw
        uname = _pick(data, ["uname", "username", "user_info.uname", "user_info.username"])
        num = data.get("num", 1)
        guard_level = data.get("guard_level", 3)
        guard_name = {1: "总督", 2: "提督", 3: "舰长"}[guard_level]
        return {"uname": uname, "num": num, "guard_name": guard_name}

    def format(self, s: LiveSettings) -> str:
        n = self.normalize()
        if n["guard_name"] == "舰长":
            return _fmt(s.template_captain, n)
        elif n["guard_name"] == "提督":
            return _fmt(s.template_admiral, n)
        elif n["guard_name"] == "总督":
            return _fmt(s.template_commander, n)
        return ""

class InteractWordEvent(LiveEvent):
    def _parse_pb(self):
        data = self.raw
        pb_base64 = data.get("pb", "")
        if not pb_base64:
            return None
        try:
            from protos import interact_word_v2_pb2
            buf = base64.b64decode(pb_base64)
            msg = interact_word_v2_pb2.InteractWord()
            msg.ParseFromString(buf)
            return msg
        except ImportError:
            return None

    def is_allowed(self, s: LiveSettings) -> bool:
        msg = self._parse_pb()
        if msg is None:
            return False
        msg_type = msg.msg_type
        if msg_type == 1:
            return bool(s.enable_entry)
        elif msg_type == 2:
            return bool(s.enable_follow)
        elif msg_type == 3:
            return bool(s.enable_share)
        return False

    def normalize(self) -> Dict[str, Any]:
        msg = self._parse_pb()
        if msg is None:
            return {}
        return {"uname": msg.uname, "msg_type": msg.msg_type}

    def format(self, s: LiveSettings) -> str:
        n = self.normalize()
        if n.get("msg_type") == 1:
            return _fmt(s.template_entry, n)
        elif n.get("msg_type") == 2:
            return _fmt(s.template_follow, n)
        elif n.get("msg_type") == 3:
            return _fmt(s.template_share, n)
        return ""

class LikeClickEvent(LiveEvent):
    def is_allowed(self, s: LiveSettings) -> bool:
        return bool(s.enable_like_click)

    def normalize(self) -> Dict[str, Any]:
        data = self.raw
        uname = _pick(data, ["uname", "username", "user_info.uname", "user_info.username"])
        return {"uname": uname}

    def format(self, s: LiveSettings) -> str:
        n = self.normalize()
        return _fmt(s.template_like_click, n)

_EVENT_MAP: Dict[str, Type[LiveEvent]] = {
    "DANMU_MSG": DanmakuEvent,
    "SUPER_CHAT_MESSAGE": SuperChatEvent,
    "SEND_GIFT": SendGiftEvent,
    "COMBO_SEND": ComboSendEvent,
    "GUARD_BUY": GuardBuyEvent,
    "INTERACT_WORD_V2": InteractWordEvent,
    "LIKE_INFO_V3_CLICK": LikeClickEvent,
}

def create_event(raw: Dict[str, Any]) -> LiveEvent:
    et = (raw.get("type") or raw.get("cmd") or "").strip().upper()
    cls = _EVENT_MAP.get(et)
    if cls is None:
        return LiveEvent(raw)
    return cls(raw)