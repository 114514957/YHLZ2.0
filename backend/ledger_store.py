"""Ledger CRUD store — the single programmatic interface to the project ledger.

`docs/上下文台账.md` is the project's single source of truth.  Every agent
(opencode, the daemon, the QQ bot, DeepSeek desktop, cron scripts) should mutate
it through this module so that writes are:

* **atomic**  — temp file + ``os.replace`` (a crash never truncates the ledger);
* **locked**  — a cross-process file lock serialises concurrent writers;
* **backed up** — the previous revision is copied to ``cache/ledger_backup/``;
* **guarded** — secret-looking lines are refused (ledger 0129/0131 privacy rule);
* **index-synced** — the keyword search face is refreshed after a write.

The public surface is deliberately tiny and stable (all return plain dicts so
they can be serialised by the CLI, MCP or an HTTP route)::

    parse_records(text)          -> list[LedgerRecord]
    next_record_no()             -> int
    get_record(no)               -> dict | None
    list_records(limit, offset)  -> list[dict]
    search(query, limit)         -> list[dict]
    add_record(title, body, ...) -> dict
    update_record(no, ...)       -> dict
    delete_record(no)            -> dict
    stats()                      -> dict

Standard library only.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER = _PROJECT_ROOT / "docs" / "上下文台账.md"
BACKUP_DIR = _PROJECT_ROOT / "cache" / "ledger_backup"
LOCK_FILE = _PROJECT_ROOT / "cache" / "tmp" / "ledger.lock"
_INDEX_SCRIPT = _PROJECT_ROOT / "tools" / "ledger_cli.py"

_HEADER_RE = re.compile(r"^##\s+记录\s+(\d+)\s*[:：]\s*(.*)$")
_SECRET_PATTERNS = (
    r"sk-\w{8,}", r"sk-ws", r"DEEPSEEK_API_KEY", r"api[_-]?key\s*[:=]",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
)
_BACKUP_KEEP = 20

_thread_lock = threading.RLock()


class LedgerError(Exception):
    """Raised for invalid CRUD operations (not for IO failures)."""


@dataclass(slots=True)
class LedgerRecord:
    no: int
    title: str
    header: str
    body_lines: list[str] = field(default_factory=list)
    start: int = 0  # 1-based line of the header
    end: int = 0    # 1-based line of the last body line

    def body_text(self) -> str:
        return "\n".join(self.body_lines).strip("\n")

    def text(self) -> str:
        body = self.body_text()
        return f"{self.header}\n\n{body}" if body else self.header

    def to_dict(self, *, with_text: bool = False) -> dict:
        d = {"no": self.no, "title": self.title, "start": self.start,
             "end": self.end, "body_lines": len(self.body_lines)}
        if with_text:
            d["text"] = self.text()
        return d


@dataclass(slots=True)
class _Doc:
    preamble: list[str]
    records: list[LedgerRecord]

    def render(self) -> str:
        chunks: list[str] = []
        if self.preamble:
            chunks.append("\n".join(self.preamble).rstrip("\n"))
        for rec in self.records:
            chunks.append(rec.text())
        text = "\n\n".join(chunks).rstrip("\n") + "\n"
        return text


# ---------------------------------------------------------------- parsing
def parse_records(text: Optional[str] = None, path: Path = LEDGER) -> list[LedgerRecord]:
    return _parse_doc(text, path).records


def _parse_doc(text: Optional[str] = None, path: Path = LEDGER) -> _Doc:
    if text is None:
        text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    preamble: list[str] = []
    records: list[LedgerRecord] = []
    cur: Optional[LedgerRecord] = None
    for i, line in enumerate(lines, 1):
        m = _HEADER_RE.match(line)
        if m:
            cur = LedgerRecord(no=int(m.group(1)), title=m.group(2).strip(),
                               header=line, start=i, end=i)
            records.append(cur)
            continue
        if cur is None:
            preamble.append(line)
        else:
            cur.body_lines.append(line)
            cur.end = i
    return _Doc(preamble=preamble, records=records)


# ---------------------------------------------------------------- read
def next_record_no(path: Path = LEDGER) -> int:
    recs = parse_records(path=path)
    return (max((r.no for r in recs), default=0) + 1)


def get_record(no: int, path: Path = LEDGER) -> Optional[dict]:
    for rec in parse_records(path=path):
        if rec.no == int(no):
            return rec.to_dict(with_text=True)
    return None


def list_records(limit: int = 20, offset: int = 0, keyword: str = "",
                 path: Path = LEDGER) -> list[dict]:
    recs = parse_records(path=path)
    if keyword:
        kw = str(keyword).lower()
        recs = [r for r in recs if kw in r.title.lower()
                or kw in r.body_text().lower()]
    recs = list(reversed(recs))  # newest first
    offset = max(0, int(offset))
    limit = max(1, int(limit))
    out: list[dict] = []
    for rec in recs[offset:offset + limit]:
        d = rec.to_dict()
        d["preview"] = _first_meaningful(rec)
        out.append(d)
    return out


def _first_meaningful(rec: LedgerRecord, width: int = 90) -> str:
    for line in rec.body_lines:
        s = line.strip().lstrip("-•").strip()
        if len(s) >= 6:
            return s[:width]
    return ""


def search(query: str, limit: int = 10, path: Path = LEDGER) -> list[dict]:
    """Record-level substring search (AND across keywords, title boosted)."""
    kws = [k.lower() for k in str(query or "").split() if k.strip()]
    if not kws:
        return []
    out: list[dict] = []
    for rec in parse_records(path=path):
        blob = (f"{rec.no:04d}\n{rec.title}\n{rec.body_text()}").lower()
        if not all(k in blob for k in kws):
            continue
        score = 1 + sum(3 for k in kws if k in rec.title.lower())
        out.append({"no": rec.no, "title": rec.title, "score": score,
                    "start": rec.start, "end": rec.end,
                    "snippets": _snippets(rec, kws)})
    out.sort(key=lambda d: (-d["score"], -d["no"]))
    return out[:max(1, int(limit))]


def _snippets(rec: LedgerRecord, kws: Sequence[str], width: int = 40,
              cap: int = 3) -> list[str]:
    hits: list[str] = []
    for line in rec.body_lines:
        low = line.lower()
        if not any(k in low for k in kws):
            continue
        pos = min((low.find(k) for k in kws if k in low), default=0)
        a = max(0, pos - width)
        b = min(len(line), pos + width)
        snip = line[a:b].strip()
        if snip and snip not in hits:
            hits.append(snip)
        if len(hits) >= cap:
            break
    return hits


def stats(path: Path = LEDGER) -> dict:
    recs = parse_records(path=path)
    p = Path(path)
    return {
        "path": str(p),
        "records": len(recs),
        "latest_no": max((r.no for r in recs), default=0),
        "lines": len(p.read_text(encoding="utf-8").splitlines()) if p.exists() else 0,
        "bytes": p.stat().st_size if p.exists() else 0,
        "mtime": p.stat().st_mtime if p.exists() else 0.0,
    }


# ---------------------------------------------------------------- guard
def sensitive_hits(text: str) -> list[str]:
    return [p for p in _SECRET_PATTERNS if re.search(p, str(text or ""), re.I)]


def _assert_clean(text: str) -> None:
    hits = sensitive_hits(text)
    if hits:
        raise LedgerError(
            "拒绝写入：疑似敏感内容（%s）。台账只记指纹，不记明文。" % "、".join(hits))


# ---------------------------------------------------------------- locking
@contextmanager
def _file_lock(timeout: float = 20.0):
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _thread_lock:
        fh = open(LOCK_FILE, "a+")
        acquired = False
        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                try:
                    if os.name == "nt":
                        import msvcrt

                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError:
                    time.sleep(0.05)
            if not acquired:
                raise LedgerError("台账被其它进程占用，稍后重试")
            yield
        finally:
            try:
                if acquired:
                    if os.name == "nt":
                        import msvcrt

                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()


# ---------------------------------------------------------------- write
def _backup(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"{path.stem}.{stamp}.md"
    shutil.copy2(path, dest)
    backups = sorted(BACKUP_DIR.glob(f"{path.stem}.*.md"))
    for old in backups[:-_BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return dest


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _commit(path: Path, doc: _Doc) -> Optional[Path]:
    backup = _backup(path)
    _atomic_write(path, doc.render())
    return backup


# ---------------------------------------------------------------- CRUD
def add_record(title: str, body: Iterable[str] | str = (), *,
               no: Optional[int] = None, stamp_time: bool = True,
               path: Path = LEDGER, sync_index: bool = True) -> dict:
    """Append a new record.  ``body`` is a list of lines or a text block."""
    title = str(title or "").strip()
    if not title:
        raise LedgerError("标题不能为空")
    if len(title) > 200:
        raise LedgerError("标题过长（>200 字）")
    lines = _normalise_body(body)
    if stamp_time and not any(l.lstrip("- ").startswith("时间：") for l in lines):
        lines = [f"- 时间：{_today()}", ""] + lines
    _assert_clean(title + "\n" + "\n".join(lines))

    timestamp = time.time()
    with _file_lock():
        doc = _parse_doc(path=path)
        used = {r.no for r in doc.records}
        new_no = int(no) if no is not None else (max(used, default=0) + 1)
        if new_no in used:
            raise LedgerError(f"记录 {new_no:04d} 已存在")
        header = f"## 记录 {new_no:04d}：{title}"
        doc.records.append(
            LedgerRecord(no=new_no, title=title, header=header,
                         body_lines=["", *lines],
                         start=0, end=0))
        _commit(path, doc)
    if sync_index:
        _sync_index("incremental")
    return {"ok": True, "action": "add", "no": new_no, "title": title,
            "record": get_record(new_no, path=path),
            "elapsed": round(time.time() - timestamp, 3)}


def update_record(no: int, *, title: Optional[str] = None,
                  append_lines: Optional[Iterable[str] | str] = None,
                  replace_body: Optional[Iterable[str] | str] = None,
                  path: Path = LEDGER, sync_index: bool = True) -> dict:
    """Update a record: rename, append lines, or replace its whole body."""
    if title is None and append_lines is None and replace_body is None:
        raise LedgerError("没有要修改的内容（title/append_lines/replace_body 至少一项）")
    timestamp = time.time()
    with _file_lock():
        doc = _parse_doc(path=path)
        rec = next((r for r in doc.records if r.no == int(no)), None)
        if rec is None:
            raise LedgerError(f"未找到记录 {int(no):04d}")
        if title is not None:
            new_title = str(title).strip()
            if not new_title:
                raise LedgerError("标题不能为空")
            rec.title = new_title
            rec.header = f"## 记录 {rec.no:04d}：{new_title}"
        if replace_body is not None:
            rec.body_lines = ["", *_normalise_body(replace_body)]
        elif append_lines is not None:
            rec.body_lines = [*rec.body_lines, *_normalise_body(append_lines)]
        _assert_clean(rec.title + "\n" + rec.body_text())
        _commit(path, doc)
    if sync_index:
        _sync_index("rebuild")
    return {"ok": True, "action": "update", "no": int(no),
            "record": get_record(int(no), path=path),
            "elapsed": round(time.time() - timestamp, 3)}


def delete_record(no: int, *, path: Path = LEDGER, sync_index: bool = True,
                  confirm: bool = False) -> dict:
    """Delete a record.  Requires ``confirm=True`` (destructive)."""
    if not confirm:
        raise LedgerError("删除是破坏性操作，需显式 confirm=True")
    timestamp = time.time()
    with _file_lock():
        doc = _parse_doc(path=path)
        before = len(doc.records)
        doc.records = [r for r in doc.records if r.no != int(no)]
        if len(doc.records) == before:
            raise LedgerError(f"未找到记录 {int(no):04d}")
        _commit(path, doc)
    if sync_index:
        _sync_index("rebuild")
    return {"ok": True, "action": "delete", "no": int(no),
            "elapsed": round(time.time() - timestamp, 3)}


def _normalise_body(body: Iterable[str] | str) -> list[str]:
    if body is None:
        return []
    if isinstance(body, str):
        raw = body.splitlines()
    else:
        raw = []
        for item in body:
            raw.extend(str(item).splitlines())
    return [l.rstrip() for l in raw]


def _today() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------- index
def _sync_index(mode: str) -> None:
    """Keep the keyword search face in step with the ledger (best effort).

    * ``incremental`` — index only new rows (fast, for pure appends).
    * ``rebuild``     — a full rebuild (142s) is spawned as a detached process
      so the caller returns immediately; a stale index only costs recall
      ranking, never correctness (search falls back to the live file).
    """
    try:
        from tools.ledger_mem_import import index_ledger_new_rows

        if mode == "incremental":
            index_ledger_new_rows(LEDGER, since_line=_last_indexed_line())
            return
    except Exception:
        pass
    if mode == "rebuild":
        _spawn_rebuild()


def _last_indexed_line() -> int:
    try:
        from backend.target_kw_index import KeywordIndex

        idx = KeywordIndex()
        con = idx._conn(writable=False)
        try:
            rows = con.execute(
                "SELECT docid FROM kw_docs WHERE source='ledger'").fetchall()
        finally:
            con.close()
        best = 0
        for (docid,) in rows:
            part = str(docid).rsplit(":", 1)[-1]
            if part.isdigit():
                best = max(best, int(part))
        return best
    except Exception:
        return 0


def _spawn_rebuild() -> None:
    if not _INDEX_SCRIPT.exists():
        return
    try:
        import subprocess

        flags = 0
        if os.name == "nt":
            flags = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
        subprocess.Popen(
            [sys.executable, "-B", str(_INDEX_SCRIPT), "index", "--all", "--quiet"],
            cwd=str(_PROJECT_ROOT), creationflags=flags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL)
    except Exception:
        pass


__all__ = [
    "LEDGER", "BACKUP_DIR", "LedgerError", "LedgerRecord",
    "parse_records", "next_record_no", "get_record", "list_records", "search",
    "add_record", "update_record", "delete_record", "stats", "sensitive_hits",
]
