"""台账检索 v2：记录级 FTS5 + 元数据过滤（2026-11-13 P0）。

背景：v1 把每一行切成一条索引（docid=记录:行号），返回行片段；没有 BM25 长度归一、
没有过滤、没有记录级排序。v2 改为：

* 一条记录 = 一个文档（标题 + 正文），FTS5 `bm25()` 排序；
* 中文先切 bigram 写 tokens（Python 自带 SQLite 没有 trigram 分词器）；
* `records` 表带 ts / kind / status / tags，支持 since/until/kind/tags 过滤；
* 全量重建 ~1s，按台账 mtime/size 自动判新旧；不动 v1 索引，可随时回滚。

只读台账、只写自己的 `cache/search/ledger_v2.db`。
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "上下文台账.md"
DEFAULT_DB = ROOT / "cache" / "search" / "ledger_v2.db"

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_LAT = re.compile(r"[a-zA-Z0-9_]+")
_REC = re.compile(r"^## 记录 (\d{4})[：:]\s*(.*)$")
_TS = re.compile(r"时间[：:]\s*(\d{4}-\d{2}-\d{2})")
_TAG = re.compile(r"(?:^|[\s，。；])#([\w\u4e00-\u9fff-]{2,20})")

_KIND_WORDS = (
    ("决策", ("决策", "拍板", "口径", "定了", "决定")),
    ("结论", ("结论", "确认", "验证", "实测", "结果")),
    ("踩坑", ("踩坑", "教训", "事故", "翻车", "失败")),
    ("状态", ("状态", "进展", "进度", "收尾", "当前")),
)


def tokens(text: str) -> str:
    """中文 bigram + 拉丁词，空格分隔，给 FTS5 unicode61 吃。"""
    out: list[str] = []
    for chunk in _CJK.findall(text or ""):
        if len(chunk) == 1:
            out.append(chunk)
        else:
            out.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
    out.extend(m.group(0).lower() for m in _LAT.finditer(text or ""))
    return " ".join(out)


def _kind_of(title: str, body: str) -> str:
    blob = (title or "") + "\n" + (body or "")
    for kind, words in _KIND_WORDS:
        if any(w in blob for w in words):
            return kind
    return "note"


def _tags_of(title: str, body: str) -> str:
    found: list[str] = []
    for m in _TAG.finditer((title or "") + "\n" + (body or "")):
        t = m.group(1)
        if t not in found:
            found.append(t)
    return ",".join(found[:20])


def parse_records(ledger: Path = LEDGER) -> list[dict]:
    text = Path(ledger).read_text(encoding="utf-8")
    records: list[dict] = []
    cur: dict | None = None
    start = 0
    for idx, line in enumerate(text.splitlines(), start=1):
        m = _REC.match(line.strip())
        if m:
            if cur:
                records.append(cur)
            cur = {"rec": int(m.group(1)), "title": m.group(2).strip(),
                   "body": [], "start": idx}
        elif cur is not None:
            cur["body"].append(line)
    if cur:
        records.append(cur)
    for r in records:
        body = "\n".join(r["body"]).strip()
        m = _TS.search(body)
        r["body"] = body
        r["end"] = r["start"] + len(r["body"].splitlines())
        r["ts"] = m.group(1) if m else ""
        r["kind"] = _kind_of(r["title"], body)
        r["tags"] = _tags_of(r["title"], body)
        r["status"] = "active"
        r["hash"] = hashlib.sha256(
            (r["title"] + "\n" + body).encode("utf-8")).hexdigest()[:16]
    return records


class LedgerV2:
    def __init__(self, db_path: Path | str = DEFAULT_DB) -> None:
        self.db_path = Path(db_path)

    # ---------- schema / build ----------
    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.db_path), timeout=30)
        con.execute("PRAGMA temp_store=MEMORY")
        return con

    def _init(self, con: sqlite3.Connection) -> None:
        con.execute("""
            CREATE TABLE IF NOT EXISTS records (
              id INTEGER PRIMARY KEY,
              rec INTEGER NOT NULL,
              title TEXT NOT NULL,
              body TEXT NOT NULL,
              ts TEXT,
              kind TEXT,
              status TEXT DEFAULT 'active',
              tags TEXT,
              hash TEXT,
              start_line INTEGER,
              end_line INTEGER
            )""")
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_rec ON records(rec)")
        con.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS rec_fts USING fts5(
              rid UNINDEXED, tokens, tokenize='unicode61')""")
        con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, val TEXT)")

    def rebuild(self, ledger: Path = LEDGER) -> dict:
        records = parse_records(ledger)
        con = self._connect()
        try:
            # 派生缓存：结构变了就整表重建（台账原文不受影响）
            con.execute("DROP TABLE IF EXISTS rec_fts")
            con.execute("DROP TABLE IF EXISTS records")
            self._init(con)
            con.executemany(
                "INSERT INTO records(id,rec,title,body,ts,kind,status,tags,hash,"
                "start_line,end_line) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(i, r["rec"], r["title"], r["body"], r["ts"], r["kind"],
                  r["status"], r["tags"], r["hash"], r["start"], r["end"])
                 for i, r in enumerate(records, start=1)])
            con.executemany(
                "INSERT INTO rec_fts(rid,tokens) VALUES (?,?)",
                [(i, tokens(r["title"] + "\n" + r["body"]))
                 for i, r in enumerate(records, start=1)])
            p = Path(ledger)
            st = p.stat()
            con.executemany(
                "INSERT OR REPLACE INTO meta(key,val) VALUES (?,?)",
                [("built_at", str(time.time())),
                 ("ledger_mtime", str(st.st_mtime)),
                 ("ledger_size", str(st.st_size)),
                 ("records", str(len(records)))])
            con.commit()
        finally:
            con.close()
        return {"records": len(records), "db": str(self.db_path)}

    def ensure_fresh(self, ledger: Path = LEDGER) -> dict | None:
        p = Path(ledger)
        if not p.exists():
            return None
        st = p.stat()
        con = self._connect()
        try:
            self._init(con)
            rows = dict(con.execute("SELECT key,val FROM meta").fetchall())
        except Exception:  # noqa: BLE001
            rows = {}
        finally:
            con.close()
        if (not rows
                or abs(float(rows.get("ledger_mtime", 0)) - st.st_mtime) > 0.5
                or str(rows.get("ledger_size", "")) != str(st.st_size)):
            return self.rebuild(ledger)
        return None

    # ---------- search ----------
    def search(self, query: str, limit: int = 5, *, since: str | None = None,
               until: str | None = None, kind: str | None = None,
               tags: str | None = None, status: str | None = None,
               ledger: Path = LEDGER) -> list[dict]:
        q = str(query or "").strip()
        if not q:
            return []
        self.ensure_fresh(ledger)
        terms = [t for t in tokens(q).split() if len(t) >= 2]
        if not terms:
            terms = [q]
        # 去重并限制项数，避免长查询把 AND 卡死
        seen: list[str] = []
        for t in terms:
            if t not in seen:
                seen.append(t)
        match = " ".join('"' + t.replace('"', "") + '"' for t in seen[:16])

        where = ["rec_fts MATCH ?"]
        args: list[object] = [match]
        if since:
            where.append("r.ts >= ?")
            args.append(since)
        if until:
            where.append("r.ts <= ?")
            args.append(until)
        if kind:
            where.append("r.kind = ?")
            args.append(kind)
        if tags:
            where.append("r.tags LIKE ?")
            args.append(f"%{tags}%")
        if status:
            where.append("r.status = ?")
            args.append(status)

        sql = (
            "SELECT r.rec, r.title, r.body, r.ts, r.kind, r.status, r.tags, "
            "r.start_line, r.end_line, bm25(rec_fts) AS score "
            "FROM rec_fts JOIN records r ON r.id = rec_fts.rid "
            "WHERE " + " AND ".join(where) +
            " ORDER BY score LIMIT ?")
        args.append(max(1, min(int(limit), 20)) * 3)
        con = self._connect()
        try:
            rows = con.execute(sql, args).fetchall()
        finally:
            con.close()
        out = []
        seen_rec: set[int] = set()
        for (rec, title, body, ts, kind, status, tags, start, end, score) in rows:
            if rec in seen_rec:
                continue
            seen_rec.add(rec)
            out.append({"rec": rec, "title": title, "ts": ts, "kind": kind,
                        "status": status, "tags": tags,
                        "score": round(float(score), 3),
                        "start": start, "end": end,
                        "snippet": _snippet(body, seen)})
            if len(out) >= max(1, min(int(limit), 20)):
                break
        return out

    def stats(self) -> dict:
        con = self._connect()
        try:
            self._init(con)
            n = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            built = dict(con.execute("SELECT key,val FROM meta").fetchall())
        finally:
            con.close()
        return {"records": n, "db": str(self.db_path),
                "size_kb": round(self.db_path.stat().st_size / 1024, 1)
                if self.db_path.exists() else 0,
                "ledger_mtime": built.get("ledger_mtime"),
                "balance": built.get("records")}


def _snippet(body: str, terms: list[str], width: int = 60) -> str:
    low = (body or "").lower()
    pos = -1
    for t in terms:
        p = low.find(t.lower())
        if p >= 0 and (pos < 0 or p < pos):
            pos = p
    if pos < 0:
        return (body or "")[:120].replace("\n", " ")
    a = max(0, pos - width)
    b = min(len(body), pos + width)
    return body[a:b].replace("\n", " ").strip()
