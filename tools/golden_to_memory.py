# -*- coding: utf-8 -*-
"""把「黄金样本」导入记忆库，作为她的记忆源（台账 1255 决策）。

为什么这么做：
  · 老爹定调："合理外推可接受，黄金样本里的样本集作为记忆"。
  · 黄金样本是**老爹亲自标过 rating/status 的**，质量高于抓来的群聊流水；
    让召回优先从它里面取，比让模型自由发挥可靠。

规则：
  · 只导 `status in {keep, fixed}`（`candidate`/`drop` 默认跳过，`--include-candidate` 可放开）
  · `rating` 决定重要性：5→9、4→7、3→5、其它→4（<4 不进注入）
  · type 由 tags 推断：偏好→preference；情绪/日常→event；其余→fact
  · source 写成 `golden:owner`（这样分层判成 owner，能进注入）
  · 幂等：按 `golden-<id>` 查重，已存在就更新文本与重要性，不重复插入

用法：
    python tools/golden_to_memory.py            # 干跑，只报统计
    python tools/golden_to_memory.py --apply    # 真写库（会先备份 memstore.db）
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOLDEN = ROOT / "docs" / "素材" / "黄金样本.md"
DB = ROOT / "cache" / "memstore" / "memstore.db"
BLOCK = re.compile(r"^##\s+golden-(\S+)\s*$", re.M)
FIELD = re.compile(r"^-\s*([a-z_]+)\s*:\s*(.*)$", re.M)


def parse(path: Path) -> list[dict]:
    text = io.open(path, encoding="utf-8", errors="replace").read()
    parts = BLOCK.split(text)
    # parts = [前言, id1, body1, id2, body2, ...]
    out = []
    for i in range(1, len(parts) - 1, 2):
        gid = parts[i].strip()
        body = parts[i + 1]
        if not re.match(r"^\d+$", gid):
            continue                      # 跳过"示例"
        fields = {k: v.strip() for k, v in FIELD.findall(body)}
        # 取 ### 老爹 / ### 元亨 段落（可多行，到下一个 ## 或文件尾）
        m_owner = re.search(r"###\s*老爹\s*\n(.+?)(?=\n###|\Z)", body, re.S)
        m_her = re.search(r"###\s*元亨\s*\n(.+?)(?=\n###|\Z)", body, re.S)
        owner = (m_owner.group(1).strip() if m_owner else "")
        her = (m_her.group(1).strip() if m_her else "")
        if not (owner or her):
            continue
        out.append({"id": gid, **fields, "owner": owner, "her": her})
    return out


def mem_type(tags: str) -> str:
    t = str(tags or "")
    if "偏好" in t or "喜欢" in t:
        return "preference"
    if "情绪" in t or "日常" in t or "晚安" in t or "鼓励" in t:
        return "event"
    return "fact"


def importance_of(rating: str) -> int:
    try:
        r = int(str(rating).strip())
    except Exception:  # noqa: BLE001
        return 4
    return {5: 9, 4: 7, 3: 5}.get(r, 4)


def summary_of(b: dict) -> str:
    o, h = b.get("owner", "").replace("\n", " "), b.get("her", "").replace("\n", " ")
    parts = []
    if o:
        parts.append("老爹说过：" + o[:160])
    if h:
        parts.append("元亨答：" + h[:160])
    return "【黄金样本 %s】%s" % (b["id"], " ｜ ".join(parts))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--include-candidate", action="store_true")
    a = ap.parse_args()

    if not GOLDEN.exists():
        print("找不到 %s" % GOLDEN)
        return 1
    blocks = parse(GOLDEN)
    keep = [b for b in blocks
            if b.get("status", "").lower() in ("keep", "fixed")
            or (a.include_candidate and b.get("status", "").lower() == "candidate")]
    print("解析到 %d 块｜可选 %d 块（keep/fixed%s）"
          % (len(blocks), len(keep),
             "+candidate" if a.include_candidate else ""))

    rows = []
    for b in keep:
        rows.append({"gid": b["id"], "type": mem_type(b.get("tags", "")),
                     "importance": importance_of(b.get("rating", "")),
                     "summary": summary_of(b), "tags": b.get("tags", "")})
    from collections import Counter
    print("  类型分布：%s" % dict(Counter(r["type"] for r in rows)))
    print("  重要性分布：%s" % dict(Counter(r["importance"] for r in rows)))
    for r in rows[:3]:
        print("  样例[%s] %s" % (r["gid"], r["summary"][:110]))

    if not a.apply:
        print("\n（干跑；加 --apply 才写库）")
        return 0

    # 备份
    bak = DB.with_name("memstore.db.bak_golden_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(DB, bak)
    print("\n已备份：%s" % bak.name)

    con = sqlite3.connect(DB)
    ins = upd = 0
    try:
        cols = {c[1] for c in con.execute("pragma table_info(l2_items)")}
        now = time.time()
        for r in rows:
            iid = "gld_%s" % r["gid"]
            summ = r["summary"]
            h = hashlib.sha1(summ.encode("utf-8")).hexdigest()[:16]
            got = con.execute("select id from l2_items where id=?", (iid,)).fetchone()
            if got:
                con.execute("update l2_items set summary=?, importance=?, "
                            "content_hash=?, source=? where id=?",
                            (summ, r["importance"], h, "golden:owner", iid))
                upd += 1
            else:
                fields = {"id": iid, "tier": "L2", "type": r["type"],
                          "importance": r["importance"], "summary": summ,
                          "content_hash": h, "keywords": r["tags"],
                          "status": "active", "evidence_ref": "golden:%s" % r["gid"],
                          "created_at": now, "version": 1, "source": "golden:owner",
                          "belief": 1.0, "salience": float(r["importance"]),
                          "confidence": 1.0}
                fields = {k: v for k, v in fields.items() if k in cols}
                q = "insert into l2_items(%s) values(%s)" % (
                    ",".join(fields), ",".join("?" * len(fields)))
                con.execute(q, tuple(fields.values()))
                ins += 1
        con.commit()
    finally:
        con.close()
    print("写入完成：新增 %d、更新 %d" % (ins, upd))
    print("下一步：python tools/memory_index_build.py  （重建向量索引，让它们可被召回）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
