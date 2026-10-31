"""base（PT）全量素材装配（ledger 0841）。

老爹 2026-10-18：「做 base 全量素材」——把**当前手上全部可用文本**装配成续训（PT）语料：
不抽样、不挑池，按 PT 方案的四池（self_core / speaking_general / tools_concept / context）
归属，逐篇带 来源/许可/组 ID/内容指纹，做四道门可接受的过滤，最后 98/2 成组切分。

数据源（全部本地已有，不联网）：
  1) self_core        docs/素材/*.md（主素材块，2025 块 keep）→ 自有
  2) speaking_general cache/.../qq_curated/qq_corpus_anon.jsonl（18505 条匿名化）→ cleared(D-1)
  3) tools_concept    data/finetune/tool_use_v{6,8,...}.jsonl（生成轨迹 1006 条）→ own
  4) context          data/v9_real_dialogue/*.jsonl（510 段，cleared）
                      + data/v9_open_pull/*.json（A 类拉样，逐库许可）
过滤：空/超短（<40 字）/超长（>20000 字截断）；剔除模板 system 提示；否定池（lizhen）不入。
去重：规范化后 sha256 精确去重 + 64 字前缀近重粗筛。
token：用本地 Gemma-4-E4B tokenizer 实测（缺失时退化为 chars/1.5 估算并标注）。

用法：python tools/v9_pt_corpus.py [--out data/pt] [--val-ratio 0.02]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
from collections import Counter
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAT = ROOT / "docs" / "素材"
QQ_ANON = ROOT / "cache" / "v9_materials_preparation" / "20261013" / "qq_curated" / "qq_corpus_anon.jsonl"
TOOL_FILES = []   # 2026-10-20（ledger 0886）：生成轨迹不进训练；工具必须真实
ALLOW_GENERATED_TOOLS = os.environ.get("YHLZ_ALLOW_GENERATED_TOOLS") == "1"
if ALLOW_GENERATED_TOOLS:
    TOOL_FILES = ["tool_use_v8.jsonl"]   # v6 全是假名，任何情况都不进
REAL_DIR = ROOT / "data" / "v9_real_dialogue"
OPEN_DIR = ROOT / "data" / "v9_open_pull"
TOKENIZER = ROOT / "models" / "gemma4-hf" / "gemma-4-e4b-it" / "tokenizer.json"

BLOCK_RE = re.compile(r"^##\s+(?P<id>[^｜|]+?)\s*[｜|]\s*(?P<label>.+)$")
FIELD_RE = re.compile(r"^-\s*([a-z_]+)\s*:\s*(.+?)\s*$")
SYS_PREFIX = "你是元亨——"

# PT 方案四池预算（V9_PT素材准备清单）
POOL_BUDGET = {"self_core": 4000, "speaking_general": 36000,
               "tools_concept": 24000, "context": 16000}
TOTAL_TARGET = 80000


def norm(text: str) -> str:
    t = re.sub(r"[ \t]+", " ", str(text or ""))
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def tok_counter():
    try:
        from tokenizers import Tokenizer
        tk = Tokenizer.from_file(str(TOKENIZER))
        return lambda s: len(tk.encode(s).ids), "gemma-4-e4b"
    except Exception:
        return (lambda s: max(1, int(len(s) / 1.5))), "est(chars/1.5)"


def load_self_core() -> list[dict]:
    out = []
    for p in sorted(MAT.rglob("*.md")):
        parts = p.relative_to(MAT).parts[:-1]
        if any(x.startswith("_") for x in parts):
            continue
        cur = None
        buf: list[str] = []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = BLOCK_RE.match(line)
            if m:
                if cur is not None:
                    out.append({**cur, "text": "\n".join(buf)})
                cur = {"source_id": f"mat#{m.group('id').strip()}",
                       "label": m.group("label").strip()[:40], "file": str(p.relative_to(ROOT))}
                buf = []
                continue
            if cur is None:
                continue
            f = FIELD_RE.match(line)
            if f:
                continue
            buf.append(line)
        if cur is not None:
            out.append({**cur, "text": "\n".join(buf)})
    return [{"pool": "self_core", "license": "own", "source": "self_core:素材块",
             **r} for r in out]


def load_speaking() -> list[dict]:
    if not QQ_ANON.exists():
        return []
    out = []
    win: list[dict] = []
    cur_group = None
    for line in QQ_ANON.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        g = str(d.get("group") or d.get("group_id") or "?")
        if g != cur_group and win:
            out.append(_qq_doc(cur_group, win))
            win = []
        cur_group = g
        win.append(d)
        if len(win) >= 12:
            out.append(_qq_doc(cur_group, win))
            win = []
    if win:
        out.append(_qq_doc(cur_group, win))
    return out


def load_speaking_raw() -> list[dict]:
    """扩容：corpus_qq_raw（31.5k 条，现场匿名化）+ group_history.db。

    2026-10-20（ledger 0904）：窗口大小可调（YHLZ_QQ_WINDOW，默认 12）。
    speaking 池按"篇"计目标，窗口 4 可把 31.5k 条消息切成 ~7.9k 篇。
    """
    import hashlib as _h
    import os as _os
    import sqlite3
    WIN = max(2, int(_os.environ.get("YHLZ_QQ_WINDOW", "12")))
    out, win, cur = [], [], None
    p = ROOT / "data" / "finetune" / "corpus_qq_raw_all.jsonl"
    if not p.exists():
        p = ROOT / "data" / "finetune" / "corpus_qq_raw.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            g = str(d.get("group") or "?")
            if g != cur and win:
                out.append(_qq_doc(cur, win))
                win = []
            cur = g
            uid = str(d.get("user") or "")
            win.append({"text": d.get("text"), "nick": "群友",
                        "user": _h.sha256(("yhlz-qq-anon-v1" + uid).encode()).hexdigest()[:10]})
            if len(win) >= WIN:
                out.append(_qq_doc(cur, win))
                win = []
    if win:
        out.append(_qq_doc(cur, win))
    gh = ROOT / "cache" / "qq_bridge" / "lite" / "group_history.db"
    if gh.exists():
        con = sqlite3.connect(gh)
        con.row_factory = sqlite3.Row
        for gid in [r[0] for r in con.execute("select distinct group_id from group_messages")]:
            rows = con.execute("select sender_id, text, is_bot from group_messages "
                               "where group_id=? order by seq", (gid,)).fetchall()
            win = []
            for m in rows:
                who = "元亨" if m["is_bot"] else _h.sha256(("yhlz-qq-anon-v1" + str(m["sender_id"])).encode()).hexdigest()[:10]
                win.append({"text": m["text"], "nick": who, "user": who})
                if len(win) >= WIN:
                    out.append(_qq_doc(f"gh_{gid}", win))
                    win = []
            if win:
                out.append(_qq_doc(f"gh_{gid}", win))
        con.close()
    return out


def _qq_doc(group: str | None, win: list[dict]) -> dict:
    lines = []
    for m in win:
        who = str(m.get("nick") or m.get("user") or "群友")
        txt = norm(m.get("text"))
        if txt:
            lines.append(f"{who}: {txt}")
    return {"pool": "speaking_general", "license": "cleared",
            "source": "qq:anon", "source_id": f"qq#{group}",
            "group": group, "text": "\n".join(lines)}


def load_tools() -> list[dict]:
    out = []
    for name in TOOL_FILES:
        p = ROOT / "data" / "finetune" / name
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            d = json.loads(line)
            msgs = d.get("messages") or []
            parts = []
            for m in msgs:
                role = m.get("role")
                content = m.get("content")
                if role == "system":
                    continue
                if content:
                    parts.append(f"[{role}] {content}")
                for call in (m.get("tool_calls") or []):
                    fn = call.get("function") or {}
                    parts.append(f"[tool_call] {fn.get('name')}({fn.get('arguments')})")
            out.append({"pool": "tools_concept", "license": "own",
                        "source": f"tools:{name}", "source_id": f"tools#{p.stem}#{i}",
                        "text": "\n".join(parts)})
    return out


def load_public_domain() -> list[dict]:
    """公版古籍/诗词（data/pd/v9_pd.jsonl，逐篇 6–13k 字长文）。"""
    p = ROOT / "data" / "pd" / "v9_pd.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append({"pool": "context", "license": d.get("license") or "public_domain",
                    "source": d.get("source") or "pd",
                    "source_id": d.get("source_id") or "pd#?",
                    "group_id": d.get("group_id"), "text": d.get("text") or ""})
    return out


def load_extra_pd() -> list[dict]:
    """散文公版 + 美德主题段（数据/pd 下两个补充集）。"""
    out = []
    for rel, theme in (("data/pd/v9_ws_prose.jsonl", None),
                       ("data/pd/v9_virtue.jsonl", "virtue"),
                       ("data/pd/v9_virtue_novel.jsonl", "virtue_novel")):
        p = ROOT / rel
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            rec = {"pool": "context", "license": d.get("license") or "public_domain",
                   "source": d.get("source") or "pd",
                   "source_id": d.get("source_id") or "pd#?",
                   "group_id": d.get("group_id"),
                   "text": d.get("text") or ""}
            if theme or d.get("theme"):
                rec["theme"] = theme or d.get("theme")
            out.append(rec)
    return out


def load_game_and_modern() -> list[dict]:
    """游戏台词（老爹裁定可用，短句）+ 现代公版白话。"""
    out = []
    for gname in ("v9_game_quotes_clean.jsonl",):
      g = ROOT / "data" / "pd" / gname
      if g.exists():
        for line in g.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            out.append({"pool": "context", "license": "owner_waiver",
                        "source": f"game:{d.get('game')}",
                        "source_id": d.get("source_id"),
                        "group_id": f"game:{d.get('game')}",
                        "theme": "game_quote", "text": d.get("text") or ""})
    m = ROOT / "data" / "pd" / "v9_modern_prose.jsonl"
    if m.exists():
        for line in m.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            out.append({"pool": "context", "license": "public_domain",
                        "source": d.get("source") or "modern",
                        "source_id": d.get("source_id"),
                        "group_id": d.get("group_id"),
                        "theme": "modern_literature",
                        "text": d.get("text") or ""})
    return out


def load_novels() -> list[dict]:
    """小说正文（老爹 D-3：个人非商用；短句/段落切块，owner_waiver）。"""
    p = ROOT / "data" / "pd" / "v9_novels.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append({"pool": "context", "license": "owner_waiver",
                    "source": d.get("source"), "source_id": d.get("source_id"),
                    "group_id": d.get("group_id"), "theme": "novel",
                    "text": d.get("text") or ""})
    return out


def load_tool_traces_real() -> list[dict]:
    """真实工具轨迹（运行时留痕 → 汇编），与生成轨迹并存但可区分。"""
    p = ROOT / "data" / "pd" / "v9_tool_traces_real.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append({"pool": "tools_concept", "license": "own",
                    "source": "tooltrace:real", "source_id": d.get("source_id"),
                    "group_id": d.get("group_id"), "theme": "tool_trace_real",
                    "text": d.get("text") or ""})
    return out


def load_harness_traces() -> list[dict]:
    """agent harness 多轮轨迹（模拟，已标 simulation；工具名来自 harness 注册表）。"""
    p = ROOT / "data" / "finetune" / "tool_harness_v1.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        parts = []
        for m in d.get("messages") or []:
            if m.get("content"):
                parts.append(f"[{m.get('role')}] {m['content']}")
            for c in (m.get("tool_calls") or []):
                fn = c.get("function") or {}
                parts.append(f"[tool_call] {fn.get('name')}({fn.get('arguments')})")
        out.append({"pool": "tools_concept", "license": "own",
                    "source": "harness:" + str(d.get("source", "")).split(":")[-1],
                    "source_id": d.get("source_id"), "group_id": d.get("group_id"),
                    "theme": "tool_harness", "text": "\n".join(parts)})
    return out


def load_dsh_traces() -> list[dict]:
    """DSH 风格多轮轨迹（工具名/参数与 DeepSeek Harness 契约一致）。"""
    p = ROOT / "data" / "finetune" / "tool_dsh_v1.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        parts = []
        for m in d.get("messages") or []:
            if m.get("content"):
                parts.append(f"[{m.get('role')}] {m['content']}")
            for c in (m.get("tool_calls") or []):
                fn = c.get("function") or {}
                parts.append(f"[tool_call] {fn.get('name')}({fn.get('arguments')})")
        out.append({"pool": "tools_concept", "license": "own",
                    "source": "dsh:" + str(d.get("source", "")).split(":")[-1],
                    "source_id": d.get("source_id"), "group_id": d.get("group_id"),
                    "theme": "tool_dsh", "text": "\n".join(parts)})
    return out


def load_tool_synth() -> list[dict]:
    """schema 忠实的合成工具轨迹（simulation=true，已过防过拟合控制）。"""
    p = ROOT / "data" / "finetune" / "tool_use_v9_synth.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        parts = []
        for m in d.get("messages") or []:
            if m.get("content"):
                parts.append(f"[{m.get('role')}] {m['content']}")
            for c in (m.get("tool_calls") or []):
                fn = (c.get("function") or {})
                parts.append(f"[tool_call] {fn.get('name')}({fn.get('arguments')})")
        out.append({"pool": "tools_concept", "license": "own",
                    "source": "toolsynth:" + str(d.get("scenario")),
                    "source_id": d.get("source_id"),
                    "group_id": d.get("group_id"),
                    "theme": "tool_synth", "text": "\n".join(parts)})
    return out


def load_tool_discipline() -> list[dict]:
    """按真实调用纪律生成的工具轨迹（2026-10-21 老爹「tool 类不够，你来加，
    你怎么调用的就教它怎么调用」）。

    与 `load_tool_synth` 的区别：那边只覆盖正常/缺参/查无/报错 4 种情形；
    这边补到 12 种——**参数类型错、超时、权限、重试、两工具接龙、结果过长、
    写操作先确认、工具不存在**，全部按工具动作类型（读/写/删/发）分派，
    所以"删一条日记"不会出现"返回零条"这种荒谬结果。

    工具名全部来自真实注册表快照；逐条带 `simulation/generated` 标记。
    """
    p = ROOT / "data" / "finetune" / "tool_discipline_v9.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        parts = []
        for m in d.get("messages") or []:
            if m.get("content"):
                parts.append(f"[{m.get('role')}] {m['content']}")
            for c in (m.get("tool_calls") or []):
                fn = (c.get("function") or {})
                parts.append(f"[tool_call] {fn.get('name')}({fn.get('arguments')})")
        out.append({"pool": "tools_concept", "license": "own",
                    "source": "tooldisc:" + str(d.get("scenario")),
                    "source_id": "tooldisc#%s#%s" % (d.get("tool"), d.get("scenario")),
                    "group_id": "tooldisc:%s" % d.get("kind"),
                    "theme": "tool_discipline", "text": "\n".join(parts)})
    return out


def load_novel_dialogue() -> list[dict]:
    """小说对白组（ledger 0905）：4 本书抽出的连续对白，补说话类素材。"""
    p = ROOT / "data" / "pd" / "v9_novel_dialogue.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append({"pool": "speaking_general", "license": "owner_waiver",
                    "source": d.get("source"), "source_id": d.get("source_id"),
                    "group_id": d.get("group_id"), "theme": "novel_dialogue",
                    "text": d.get("text") or ""})
    return out


def load_refbooks() -> list[dict]:
    """教材/工具书（ledger 0905）：维基教科书/词典/百科，CC BY-SA 4.0。"""
    p = ROOT / "data" / "pd" / "v9_refbooks.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append({"pool": "context", "license": "cc-by-sa-4.0",
                    "source": d.get("source"), "source_id": d.get("content_hash"),
                    "group_id": d.get("source") + ":" + str(d.get("title")),
                    "theme": "refbook", "text": d.get("text") or ""})
    return out


def load_novel_desc() -> list[dict]:
    """小说场景描写段（ledger 0906）：非对白的描写/心理/动作段。"""
    p = ROOT / "data" / "pd" / "v9_novel_desc.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append({"pool": "context", "license": "owner_waiver",
                    "source": d.get("source"), "source_id": d.get("source_id"),
                    "group_id": d.get("group_id"), "theme": "novel_desc",
                    "text": d.get("text") or ""})
    return out


def load_knowledge() -> list[dict]:
    """逻辑/科普（ledger 0907）：按主题搜出来的教材/百科正文（CC BY-SA 4.0）。"""
    p = ROOT / "data" / "pd" / "v9_knowledge.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append({"pool": "context", "license": "cc-by-sa-4.0",
                    "source": d.get("source"), "source_id": d.get("content_hash"),
                    "group_id": str(d.get("source")) + ":" + str(d.get("title")),
                    "theme": "knowledge", "text": d.get("text") or ""})
    return out


def load_similes() -> list[dict]:
    """比喻句（ledger 0907）：讲道理会打比方。"""
    p = ROOT / "data" / "pd" / "v9_similes.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append({"pool": "speaking_general", "license": d.get("license") or "owner_waiver",
                    "source": d.get("source"), "source_id": d.get("content_hash"),
                    "group_id": "simile:" + str(d.get("source")),
                    "theme": "simile", "text": d.get("text") or ""})
    return out


def load_open_dialogue() -> list[dict]:
    """开放对话数据集（ledger 0908）：emotion-intel/adorable-eq/roleplay-novel/companion-sft。"""
    p = ROOT / "data" / "pd" / "v9_open_dialogue.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append({"pool": "speaking_general", "license": d.get("license") or "unknown",
                    "source": d.get("source"), "source_id": d.get("source_id"),
                    "group_id": d.get("group_id"), "theme": "open_dialogue",
                    "text": d.get("text") or ""})
    return out


def load_ws_topics() -> list[dict]:
    """Wikisource 指定篇目（ledger 0909）：茶馆/骆驼祥子/评书底本，公版。"""
    p = ROOT / "data" / "pd" / "v9_ws_topics.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        src = str(d.get("source") or "")
        pool = "speaking_general" if "茶馆" in src else "context"
        out.append({"pool": pool, "license": "public_domain",
                    "source": src, "source_id": d.get("content_hash"),
                    "group_id": src + ":" + str(d.get("title")),
                    "theme": "ws_topic", "text": d.get("text") or ""})
    return out


def load_podcast_ai() -> list[dict]:
    """中文 AI 技术播客对白（ledger 0910，模拟生成）。"""
    p = ROOT / "data" / "finetune" / "podcast_ai.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        parts = [f"[{m.get('role')}] {m.get('content')}"
                 for m in d.get("messages") or [] if m.get("content")]
        out.append({"pool": "speaking_general", "license": "own",
                    "source": d.get("source"), "source_id": d.get("source_id"),
                    "group_id": d.get("group_id"), "theme": "podcast_ai",
                    "text": "\n".join(parts)})
    return out


def load_podcast_asr() -> list[dict]:
    """中文播客 ASR 转写（ledger 0918）：RSS→音频→faster-whisper，reference_only。"""
    p = ROOT / "data" / "pd" / "v9_podcast_asr.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append({"pool": "context", "license": "reference_only",
                    "source": d.get("source"), "source_id": d.get("content_hash"),
                    "group_id": str(d.get("source")) + ":" + str(d.get("title"))[:40],
                    "theme": "podcast_asr", "text": d.get("text") or ""})
    return out


def load_context() -> list[dict]:
    out = []
    for p in sorted(REAL_DIR.glob("*.jsonl")):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            d = json.loads(line)
            parts = []
            for m in d.get("messages") or []:
                c = norm(m.get("content"))
                if c:
                    parts.append(f"[{m.get('role')}] {c}")
            out.append({"pool": "context", "license": "cleared",
                        "source": "real:qq", "source_id": d.get("source_id") or f"real#{p.stem}#{i}",
                        "text": "\n".join(parts)})
    for p in sorted(OPEN_DIR.glob("*.json")):
        if p.name == "manifest.json":
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = d.get("data") or []
        lic = str(d.get("license") or "unknown")
        for i, r in enumerate(rows):
            row = r.get("row") if isinstance(r, dict) else r
            if not isinstance(row, dict):
                continue
            txt = norm(" ".join(str(v) for v in row.values() if isinstance(v, str)))
            out.append({"pool": "context", "license": lic,
                        "source": f"open:{p.stem}", "source_id": f"open#{p.stem}#{i}",
                        "text": txt})
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/pt")
    ap.add_argument("--val-ratio", type=float, default=0.02)
    args = ap.parse_args()
    count, tokname = tok_counter()

    rows = []
    for loader in (load_self_core, load_speaking, load_speaking_raw, load_tools, load_tool_traces_real, load_tool_discipline, load_novel_dialogue, load_novel_desc, load_refbooks, load_knowledge, load_similes, load_open_dialogue, load_ws_topics, load_podcast_ai, load_podcast_asr, load_public_domain, load_extra_pd, load_game_and_modern, load_novels, load_context):
        got = loader()
        print(f"[load] {loader.__name__}: {len(got)}")
        rows.extend(got)

    # 过滤 + 去重
    seen: set[str] = set()
    prefixes: set[str] = set()
    kept, dropped = [], Counter()
    # 2026-10-21 审核发现（审核器 D2）：
    #   · reference_only 3 篇（podcastasr:硅谷101 / 十字路口）——数据卡明确"只供参考、
    #     不进训练"，**必须剔**；
    #   · nc_only 6 篇（open:companion-sft，zhcompanion/cc-by-nc-4.0）——繁体 + 别人人设
    #     （小柔，护士），既踩许可限制又违角色一致性，一并剔。
    BANNED_LICENSE = {"reference_only", "nc_only"}
    for r in rows:
        if str(r.get("license") or "") in BANNED_LICENSE:
            dropped["license-ban"] += 1
            continue
        t = norm(r.get("text"))
        if not t:
            dropped["empty"] += 1
            continue
        if t.startswith(SYS_PREFIX):
            dropped["system-prompt"] += 1
            continue
        if len(t) < 40:
            dropped["too-short"] += 1
            continue
        if len(t) > 20000:
            t = t[:20000]
            dropped["truncated"] += 1
        h = hashlib.sha256(t.encode()).hexdigest()[:16]
        if h in seen:
            dropped["dup-exact"] += 1
            continue
        # 前缀近重只对长文生效（工具/对话类短样本前 64 字常相同，误杀严重）
        pre = (t[:96] + "|" + t[-96:]) if len(t) >= 400 else None
        if pre and pre in prefixes:
            dropped["dup-prefix"] += 1
            continue
        seen.add(h)
        if pre:
            prefixes.add(pre)
        tokens = count(t)
        r.update({"text": t, "content_hash": h, "chars": len(t), "tokens": tokens})
        kept.append(r)

    # 成组切分（group_id 默认 source_id）
    for r in kept:
        r.setdefault("group_id", r.get("source_id") or r.get("source") or "g")
    groups = sorted({r["group_id"] for r in kept})
    n_val = max(1, int(len(groups) * args.val_ratio))
    val_groups = set(groups[-n_val:])
    train = [r for r in kept if r["group_id"] not in val_groups]
    val = [r for r in kept if r["group_id"] in val_groups]

    outdir = ROOT / args.out
    outdir.mkdir(parents=True, exist_ok=True)
    for name, recs in (("train", train), ("val", val)):
        p = outdir / f"v9_base_{name}.jsonl"
        with p.open("w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    pool_stats: dict[str, dict] = {}
    for r in kept:
        s = pool_stats.setdefault(r["pool"], {"docs": 0, "chars": 0, "tokens": 0})
        s["docs"] += 1
        s["chars"] += r["chars"]
        s["tokens"] += r["tokens"]
    lic = Counter(r["license"] for r in kept)
    src = Counter(r["source"] for r in kept)
    manifest = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "tokenizer": tokname,
        "total_docs": len(kept),
        "train_docs": len(train), "val_docs": len(val),
        "total_chars": sum(r["chars"] for r in kept),
        "total_tokens": sum(r["tokens"] for r in kept),
        "pools": pool_stats,
        "pool_budget": POOL_BUDGET,
        "total_target": TOTAL_TARGET,
        "coverage_vs_target": round(len(kept) / TOTAL_TARGET, 4),
        "licenses": dict(lic),
        "top_sources": dict(src.most_common(12)),
        "dropped": dict(dropped),
        "files": {name: str((outdir / f"v9_base_{name}.jsonl").relative_to(ROOT))
                  for name in ("train", "val")},
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in
                      ("total_docs", "total_chars", "total_tokens", "pools",
                       "coverage_vs_target", "dropped")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
