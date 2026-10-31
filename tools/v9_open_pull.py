"""A 类开源拉样（老爹 2026-10-18 批准；每库 ≤300 行，只取公开预览行）。

用 HF datasets-server rows API（无需 token 的公开集），**显式空代理**（NO_PROXY 里的
`[::1]` 会让 httpx/urllib 代理解析炸掉——台账 0837/0815 的老坑）。
每个库落：data/v9_open_pull/<slug>.json（含 license 快照与来源 URL）+ 汇总 manifest。

用法：python tools/v9_open_pull.py [--rows 200]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import urllib.parse
import urllib.request
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "v9_open_pull"

# A 类（§2.7）：slug -> (repo, 许可, 备注)
TARGETS = {
    "lccc-slim": ("lorinma/Slim-LCCC-zh", "未标+门控", "门控集可能 401"),
    "emotion-intel": ("LooksJuicy/Chinese-Emotional-Intelligence", "apache-2.0", "情绪回应"),
    "multi-emotion": ("Johnson8187/Chinese_Multi-Emotion_Dialogue_Dataset", "MIT", "多情绪对白"),
    "adorable-eq": ("MemorialSummer/chinese-adorable-high-emotional-intelligence-chat", "cc-by-4.0", "可爱情绪语域"),
    "companion-sft": ("zhcompanion/companion-roleplay-sft", "cc-by-nc-4.0", "陪伴/反助手腔"),
    "roleplay-sharegpt": ("shibing624/roleplay-zh-sharegpt-gpt4-data", "apache-2.0", "格式参考"),
    "evol-character": ("bai-roleplay/evol-character-200", "apache-2.0", "人设一致性"),
    "roleplay-novel": ("LooksJuicy/Chinese-Roleplay-Novel", "apache-2.0", "酒馆格式"),
    "interview-small": ("zhangjun640/Chinese_interview_small", "MIT", "访谈（小）"),
    "interview-medium": ("zhangjun640/Chinese_interview_medium", "MIT", "访谈（中）"),
}


def _open(url: str):
    """走系统代理（本机需 127.0.0.1:7897 才能出网）；直连兜底。"""
    req = urllib.request.Request(url, headers={"User-Agent": "yhlz-v9-pull/1.0"})
    try:
        return urllib.request.urlopen(req, timeout=30).read()
    except Exception:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(req, timeout=25).read()


def fetch_rows(repo: str, rows: int, offset: int = 0) -> dict:
    q = urllib.parse.urlencode({"dataset": repo, "config": "default",
                                "split": "train", "offset": offset, "length": rows})
    url = f"https://datasets-server.huggingface.co/rows?{q}"
    try:
        data = json.loads(_open(url))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                "url": url}
    return {"ok": True, "url": url, "payload": data}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=200)
    ap.add_argument("--pages", type=int, default=1, help="每个数据集翻几页")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"pulled_at": datetime.now().isoformat(timespec="seconds"),
                "rows_requested": args.rows, "items": []}
    for slug, (repo, lic, note) in TARGETS.items():
        # 2026-10-20（ledger 0908）：分页拉多页，行数上限 = rows * pages
        pages = []
        for page in range(args.pages):
            r = fetch_rows(repo, args.rows, offset=page * args.rows)
            if not r.get("ok"):
                if page == 0:
                    pages.append(r)
                break
            pages.append(r)
            total = ((r.get("payload") or {}).get("num_rows_total") or 0)
            if total and (page + 1) * args.rows >= total:
                break
        got = {"ok": any(x.get("ok") for x in pages), "pages": pages,
               "url": pages[0].get("url") if pages else ""}
        item = {"slug": slug, "repo": repo, "license": lic, "note": note}
        if not got["ok"]:
            errs = [x.get("error") for x in got.get("pages") or [] if x.get("error")]
            item.update({"ok": False, "error": (errs[0] if errs else "no rows")})
            manifest["items"].append(item)
            print(f"  ✗ {slug:18s} {item['error'][:90]}")
            continue
        rows = []
        for pg in got["pages"]:
            rows.extend((pg.get("payload") or {}).get("rows") or [])
        blob = json.dumps(rows, ensure_ascii=False)
        sha = hashlib.sha256(blob.encode()).hexdigest()[:16]
        path = OUT / f"{slug}.json"
        path.write_text(json.dumps({"repo": repo, "license": lic, "note": note,
                                    "source_url": got["url"], "rows": len(rows),
                                    "sha16": sha, "data": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        item.update({"ok": True, "rows": len(rows), "sha16": sha,
                     "bytes": path.stat().st_size,
                     "path": str(path.relative_to(ROOT))})
        manifest["items"].append(item)
        print(f"  ✓ {slug:18s} rows={len(rows):3d} sha16={sha} "
              f"{path.stat().st_size//1024}KB")
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for i in manifest["items"] if i.get("ok"))
    print(f"[pull] 成功 {ok}/{len(TARGETS)} → {OUT / 'manifest.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
