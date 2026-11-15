# -*- coding: utf-8 -*-
"""QQ 记忆桥 v2：从群会话里解析出**真实原话**，完整写进本体记忆。

v1 的错（2026-11-13 当天发现）：把会话里的 user 消息直接写库——可群里那条
user 根本不是人话，是**注入的上下文包**：
    [群聊最近记录（仅供理解，不要逐条回应）]
    [群上下文摘要 50 条，均带来源ID]
    [1570119659] 好刀啊: 不是
    [bot:7bc78ea3…] 元亨: 好刀啊，一个"不是"就完了…
写进去等于往她记忆里灌脚手架。

v2 做法：
  1. 解析上下文包里的每一行 `[来源ID] 昵称: 内容`
  2. 按来源 ID 全局去重（同一个消息在多轮包里重复出现）
  3. 她的回复取 assistant 消息，按内容哈希去重
  4. 一轮一条 L2：`[群名] 昵称: 原话` / `[群名] 元亨: 她的回复`
     —— **保留原话**，不压摘要

用法：
  python tools/qq_memory_bridge.py --dry        # 看会写什么
  python tools/qq_memory_bridge.py             # 写一次
  python tools/qq_memory_bridge.py --loop 300  # 常驻
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import io
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SESS = os.path.join(ROOT, "cache", "sessions")
SEEN = os.path.join(ROOT, "cache", "qq_daily", "_mem_seen.json")
NAMES = os.path.join(ROOT, "cache", "qq_daily", "_group_names.json")

LINE_RE = re.compile(r"^\[([^\]]+)\]\s*([^:：]{1,40})[:：]\s*(.*)$")
BOT_TAG_RE = re.compile(r"^\[\[at:\s*\d+\]\]\s*")
SCAFFOLD = ("群聊最近记录", "群上下文摘要", "仅供理解", "不要逐条回应")
MAX_CHARS = 800


def load_json(p: str, default):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def save_json(p: str, d) -> None:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))
    os.replace(tmp, p)


def group_names() -> dict:
    cached = load_json(NAMES, {})
    if cached:
        return cached
    try:
        from backend import qq_group_admin as ga
        r = ga.list_groups()
        if r.get("ok"):
            cached = {g["id"]: g["name"] for g in r.get("groups", [])}
            save_json(NAMES, cached)
    except Exception:  # noqa: BLE001
        pass
    return cached


def parse_blocks(text: str) -> list[dict]:
    """从上下文包里抽出真实发言。脚手架行一律跳过。"""
    out = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if any(k in s for k in SCAFFOLD) or s.startswith("[群"):
            continue
        m = LINE_RE.match(s)
        if not m:
            continue
        src, nick, body = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        if not body or body in ("[媒体×19]",) or len(body) < 1:
            continue
        out.append({"src": src, "nick": nick, "text": body})
    return out


def iter_sessions():
    for p in sorted(glob.glob(os.path.join(SESS, "qq_qq_*.json"))):
        name = os.path.basename(p)
        m = re.match(r"qq_qq_(g\d+|p\d+)\.json$", name)
        if not m:
            continue
        ch = "qq_" + m.group(1)
        d = load_json(p, {})
        hist = d.get("history") or []
        for i, msg in enumerate(hist):
            role = msg.get("role")
            txt = (msg.get("content") or "").strip()
            if not txt:
                continue
            if role == "user":
                for it in parse_blocks(txt):
                    yield {"ch": ch, "kind": "say", **it}
            elif role == "assistant":
                yield {"ch": ch, "kind": "reply",
                       "text": BOT_TAG_RE.sub("", txt).strip()}


def write_items(items, names, seen, dry) -> int:
    from backend.target_memory import L2Item, TargetMemoryService

    svc = None if dry else TargetMemoryService()
    n = 0
    for it in items:
        ch = it["ch"]
        is_group = ch.startswith("qq_g")
        gid = ch[4:]
        label = ("群「%s」(%s)" % (names.get(gid, gid), gid)) if is_group else ("私聊(%s)" % gid)
        if it["kind"] == "say":
            key = "say:" + str(it["src"])
            text = "[%s] %s: %s" % (label, it["nick"], it["text"])
            imp = 5
        else:
            key = "reply:" + hashlib.sha1(it["text"].encode("utf-8")).hexdigest()[:16]
            text = "[%s] 元亨: %s" % (label, it["text"])
            imp = 5
        # importance 必须 >=5：contextual_recall 的字面召回门槛是 <5 就跳过
        # （target_memory.py:784，注释里写 4 但代码是 5，2026-11-13 实测踩到）。
        if key in seen:
            continue
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + "…"
        seen[key] = time.time()
        n += 1
        if dry:
            print("   [dry] %s" % text[:120])
            continue
        svc.store_item(L2Item(
            id="qqm_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16],
            # type 必须是 "event"：contextual_recall 只让
            # ("preference","event","decision") 自动浮现（target_memory.py:731），
            # 用 "conversation" 会写进去但永远想不起来（2026-11-13 实测 0 命中）。
            tier="L2", type="event", importance=imp, summary=text,
            content_hash=hashlib.sha1(text.encode("utf-8")).hexdigest(),
            keywords=",".join(re.findall(r"[\u4e00-\u9fff]{2,4}", text)[:8]),
            evidence_ref="qq_sessions:%s:%s" % (ch, key[:40]),
            created_at=time.time(), salience=0.4,
            source=("qq_group:" + gid) if is_group else ("qq_private:" + gid),
            kind="episodic", confidence=0.85, stance="fact",
        ))
    return n


def run(dry: bool = False) -> int:
    names = group_names()
    seen = load_json(SEEN, {})
    before = len(seen)
    n = write_items(list(iter_sessions()), names, seen, dry)
    if not dry and len(seen) != before:
        save_json(SEEN, seen)
    print("%s：新写 %d 条（去重表 %d → %d）"
          % ("试运行" if dry else "已写入", n, before, len(seen)))
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if not a.loop:
        run(a.dry)
        return 0
    print("循环写本体记忆，每 %d 秒一次" % a.loop, flush=True)
    while True:
        try:
            run(False)
        except Exception as ex:  # noqa: BLE001
            print("失败：%s: %s" % (type(ex).__name__, ex), flush=True)
        time.sleep(max(60, a.loop))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
