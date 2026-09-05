"""Prefill L2 memory from the ledger (decision/conclusion lines only).

Ledger 0142 decision: only *decision / conclusion* lines are imported as
candidate memory items (facts/context), never raw process detail.  Sensitive
lines (API keys, env fingerprints, unredacted secrets) are skipped under the
0129/0131 privacy discipline.

Dry-run by default: pass ``--write`` to persist into
``cache/memstore/memstore.db`` (same tables as TargetMemoryService).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER = _PROJECT_ROOT / "docs" / "上下文台账.md"
DEFAULT_DB = _PROJECT_ROOT / "cache" / "memstore" / "memstore.db"

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_DECISION_MARKERS = (
    "用户指令", "用户要求", "用户拍板", "用户确认", "用户决定", "用户选择",
    "用户采纳", "用户明确", "用户同意", "用户否决", "批准", "同意",
    "定案", "定稿", "结论", "推荐组合", "拍板",
)
_CONCLUSION_MARKERS = (
    "结论", "定案", "定稿", "判定", "实锤", "瓶颈根因", "为待办",
    "状态：", "是否修改文件",
)
_PRIVATE_PATTERNS = (
    r"sk-\w+", r"DEEPSEEK_API_KEY", r".env", r"api[_-]?key\s*[:=]", r"sk-ws",
    r"JnrGUdVTg", r"指纹",
)
# user-preference facts rank higher than engineering context
FACT_IMPORTANCE = 8
CONTEXT_IMPORTANCE = 5

_TRACK_NUM = re.compile(r"^##\s+记录\s+(\d+)")


@dataclass(slots=True)
class LedgerItem:
    record: str
    line_no: int
    kind: str  # fact | context
    summary: str
    keywords: str
    evidence_ref: str


def _clean(text: str) -> str:
    text = re.sub(r"[#*\s]+", " ", text)
    text = re.sub(r"[，。！？、;；:：,.]$", "", text)
    return text.strip()


def _is_sensitive(text: str) -> bool:
    return any(re.search(p, text, re.I) for p in _PRIVATE_PATTERNS)


_EXCLUDE_PREFIXES = (
    "是否修改文件", "时间：", "测试证据", "下一步", "本轮", "备注：", "数据：",
    "结果：", "测试：", "位置：", "入口：", "文件：", "术语：", "环境：",
)


def _is_metadata(line: str) -> bool:
    return any(line.startswith(p) for p in _EXCLUDE_PREFIXES)


def _kind_of(line: str) -> Optional[str]:
    if _is_metadata(line):
        return None
    low = line
    if any(m in low for m in ("用户指令", "用户要求", "用户拍板", "用户确认", "用户决定",
                              "用户选择", "用户采纳", "用户明确", "用户同意", "用户否决",
                              "用户批准", "批准", "同意", "不想", "不允许")):
        return "fact"
    if any(m in low for m in _DECISION_MARKERS + _CONCLUSION_MARKERS):
        return "context"
    return None


_NUMBERED = re.compile(r"^\d+\.\s*(.*)$")
_TITLE_DECISION_WORDS = ("拍板", "定案", "定稿", "淘汰", "锁定", "决定", "采纳", "映射", "拍板", "决策", "协议", "定责", "红线", "禁止")


def extract_ledger_decision_lines(ledger: Path = LEDGER) -> list[LedgerItem]:
    raw = ledger.read_text(encoding="utf-8")
    lines = raw.splitlines()
    items: list[LedgerItem] = []
    current_record = "0000"
    for idx, line in enumerate(lines, start=1):
        m = _TRACK_NUM.match(line.strip())
        if m:
            current_record = m.group(1)
            title = line.strip().replace("## ", "", 1)
            clean_title = re.sub(rf"^\s*记录\s*{current_record}\s*[:：]\s*", "", title)
            clean_title = re.sub(r"\s*[:：]\s*$", "", clean_title)
            if any(w in clean_title for w in _TITLE_DECISION_WORDS):
                items.append(
                    LedgerItem(
                        record=current_record,
                        line_no=idx,
                        kind="context",
                        summary=f"记录{current_record}主题: {_clean(clean_title)}",
                        keywords=_clean(clean_title)[:40].replace(" ", ""),
                        evidence_ref=f"docs/上下文台账.md#{idx}",
                    )
                )
            continue
        stripped = line.strip()
        body = None
        if stripped.startswith("- "):
            body = stripped[2:].strip()
        else:
            nm = _NUMBERED.match(stripped)
            if nm:
                body = nm.group(1).strip()
        if not body or len(body) < 8:
            continue
        if _is_sensitive(body):
            continue
        kind = _kind_of(body)
        if kind is None:
            continue
        summary = _clean(body)
        if not summary:
            continue
        if len(summary) > 220:
            summary = summary[:217].rstrip("，。、 ；") + "…"
        keywords = _clean(body)[:40].replace(" ", "")
        items.append(
            LedgerItem(
                record=current_record,
                line_no=idx,
                kind=kind,
                summary=summary,
                keywords=keywords,
                evidence_ref=f"docs/上下文台账.md#{idx} (记录{current_record})",
            )
        )
    return items


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:13]


def write_items(items: list[LedgerItem], db_path: Path = DEFAULT_DB) -> int:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS l2_items (
          id TEXT PRIMARY KEY, tier TEXT NOT NULL, type TEXT NOT NULL,
          importance INTEGER NOT NULL, summary TEXT NOT NULL,
          content_hash TEXT NOT NULL, keywords TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active', evidence_ref TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL, version INTEGER NOT NULL DEFAULT 1,
          obsolete_of TEXT NOT NULL DEFAULT '', access_count INTEGER NOT NULL DEFAULT 0,
          last_accessed REAL NOT NULL DEFAULT 0
        )
        """
    )
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS l2_fts USING fts5(sid, keywords, summary)")
    written = 0
    for it in items:
        iid = "mem_" + _fingerprint(it.summary)
        now = time.time()
        con.execute(
            """
            INSERT OR REPLACE INTO l2_items
            (id,tier,type,importance,summary,content_hash,keywords,status,evidence_ref,created_at,version,obsolete_of,access_count,last_accessed)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                iid, "L2", it.kind,
                FACT_IMPORTANCE if it.kind == "fact" else CONTEXT_IMPORTANCE,
                it.summary, _fingerprint(it.summary), it.keywords,
                "active", it.evidence_ref, now, 1, "", 0, 0.0,
            ),
        )
        con.execute("INSERT OR REPLACE INTO l2_fts(sid, keywords, summary) VALUES (?,?,?)",
                    (iid, it.keywords, it.summary))
        written += 1
    con.commit()
    con.close()
    return written


def index_ledger_all_rows(ledger: Path = LEDGER) -> int:
    """Index every ledger line (search surface = full ledger; memory stays limited)."""
    from backend.target_kw_index import KeywordIndex

    kw = KeywordIndex()
    raw = ledger.read_text(encoding="utf-8").splitlines()
    cur_record = "0000"
    title = ""
    n = 0
    for idx, line in enumerate(raw, start=1):
        m = _TRACK_NUM.match(line.strip())
        if m:
            cur_record = m.group(1)
            title = line.strip().replace("## ", "", 1)
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _is_sensitive(stripped):
            continue
        body = stripped[2:].strip() if stripped.startswith("- ") else stripped
        if len(body) < 4:
            continue
        kw.upsert_doc(
            docid=f"ledger:{cur_record}:{idx}",
            source="ledger",
            summary=body[:500],
            record_title=title[:120],
        )
        n += 1
    return n


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--write", action="store_true", help="persist into L2 (default dry-run)")
    parser.add_argument("--limit", type=int, default=0, help="stop after N extracted items (0=all)")
    parser.add_argument("--index-ledger-all", action="store_true",
                        help="index ALL ledger lines into keyword search (ledger surface)")
    parser.add_argument("--rebuild-l2-face", action="store_true",
                        help="rebuild kw l2 face from memstore l2_items (authoritative source)")
    args = parser.parse_args(argv)
    items = extract_ledger_decision_lines(args.ledger)
    if args.limit > 0:
        items = items[: args.limit]
    facts = sum(1 for x in items if x.kind == "fact")
    print(f"ledger decision lines: {len(items)} (fact={facts}, context={len(items) - facts})")
    for it in items[:8]:
        print(f"  [{it.record}] ({it.kind}) {it.summary[:110]}")
    print("  ...")
    for it in items[-3:]:
        print(f"  [{it.record}] ({it.kind}) {it.summary[:110]}")
    if args.rebuild_l2_face:
        from backend.target_kw_index import KeywordIndex

        kw = KeywordIndex()
        removed = kw.clear_source("l2")
        con = sqlite3.connect(str(args.db))
        rows = con.execute(
            "SELECT id, tier, type, importance, summary, content_hash, keywords, "
            "status, evidence_ref, created_at FROM l2_items"
        ).fetchall()
        con.close()
        for row in rows:
            kw.upsert_doc(
                docid=row[0], source="l2", summary=str(row[4]) or "",
                record_title=f"L2-{row[2]}", importance=int(row[3] or 0),
                status=str(row[7] or "active"),
            )
        h = kw.health()
        print(f"rebuild l2 face: removed {removed}, loaded {len(rows)}; kw docs={h['docs']}")
        return 0

    synced = False
    if args.write:
        n = write_items(items, args.db)
        print(f"written to {args.db}: {n} items")
    if args.index_ledger_all or args.write:
        from backend.target_kw_index import KeywordIndex

        kw = KeywordIndex()
        if args.write or True:
            pass
        for it in items:
            kw.upsert_doc(
                docid="mem_" + _fingerprint(it.summary),
                source="l2",
                summary=it.summary,
                record_title=f"记录{it.record}",
                importance=FACT_IMPORTANCE if it.kind == "fact" else CONTEXT_IMPORTANCE,
            )
        synced = True
        if args.index_ledger_all:
            n = index_ledger_all_rows(args.ledger)
            h = kw.health()
            print(f"keyword index: docs={h['docs']} terms={h['terms']} (ledger_rows={n})")
            print("   (memory face = decision lines; search face = full ledger)")
        else:
            h = kw.health()
            print(f"keyword index (memory face): docs={h['docs']}")
    if not synced:
        print("dry-run: pass --write or --index-ledger-all to persist")


if __name__ == "__main__":
    raise SystemExit(main())
