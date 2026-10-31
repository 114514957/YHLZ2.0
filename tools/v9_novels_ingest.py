"""小说正文入库：下载物象/图书素材.zip（.nb = UTF-8 章节文本）→ PT 语料。

老爹 2026-10-20：「在下载物象里，我给过你的」——确认 zip 内四本：
  异常生物见闻录(1777 段) / 希灵帝国(1675) / 诡秘之主(1455) / 苏菲的世界(37)
许可：老爹裁定（D-3，版权自担，个人非商用、不对外分发）→ license=owner_waiver。
处理：每本按段号排序拼接 → 按段落边界切 ~12000 字块（长文入 context 池）。
产出：data/pd/v9_novels.jsonl + novels_manifest.json
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
ZIP = ROOT / "下载物象" / "图书素材.zip"
OUT = ROOT / "data" / "pd"


def dec(name: str) -> str:
    try:
        return name.encode("cp437").decode("gbk")
    except Exception:
        return name


def chunk(text: str, size: int = 12000) -> list[str]:
    paras = [p for p in text.split("\n") if p.strip()]
    out, buf, n = [], [], 0
    for p in paras:
        buf.append(p)
        n += len(p)
        if n >= size:
            out.append("\n".join(buf))
            buf, n = [], 0
    if buf:
        out.append("\n".join(buf))
    return [x for x in out if len(x) >= 500]


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", type=int, default=12000)
    args, _ = ap.parse_known_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not ZIP.exists():
        print("缺少", ZIP, file=sys.stderr)
        return 2
    z = zipfile.ZipFile(ZIP)
    books: dict[str, list[tuple[int, str]]] = {}
    for info in z.infolist():
        if info.is_dir():
            continue
        name = dec(info.filename)
        if "/" not in name:
            continue
        folder, fname = name.split("/", 1)
        m = re.match(r"(\d+)-", fname)
        if not m:
            continue
        seq = int(m.group(1))
        try:
            text = z.read(info).decode("utf-8")
        except Exception:
            continue
        books.setdefault(folder, []).append((seq, text))

    rows, evid = [], []
    for folder, parts in books.items():
        parts.sort()
        full = "\n".join(t for _s, t in parts)
        segs = chunk(full, args.chunk)
        book = re.sub(r"[0-9a-f]{16}$", "", folder)
        for i, seg in enumerate(segs):
            rows.append({"text": seg, "source": f"novel:{book}",
                         "source_id": f"novel#{book}#{i}",
                         "group_id": f"novel:{book}",
                         "license": "owner_waiver",
                         "license_note": "老爹 D-3 裁定：仅本地非商用训练，不对外分发",
                         "chars": len(seg),
                         "content_hash": hashlib.sha256(seg.encode()).hexdigest()[:16]})
        evid.append({"book": book, "chapters": len(parts),
                     "chars": len(full), "segments": len(segs)})
        print(f"  ✓ {book}: {len(parts)} 段 / {len(full):,} 字 → {len(segs)} 块")

    out = OUT / "v9_novels.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    manifest = {"built_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
                "source_zip": str(ZIP.relative_to(ROOT)),
                "books": evid,
                "docs": len(rows),
                "chars": sum(r["chars"] for r in rows),
                "long_docs_8k": sum(1 for r in rows if r["chars"] >= 8000),
                "file": str(out.relative_to(ROOT))}
    (OUT / "novels_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("docs", "chars", "long_docs_8k")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
