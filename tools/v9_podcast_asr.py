"""中文播客拉取：RSS → 音频 → 本地 ASR（ledger 0918）。

老爹：「我没找到导出，尝试其他方法拉取」。
路径：**播客 RSS 拿音频 → faster-whisper 本地转写**（不依赖任何导出功能）。

  · 源：硅谷101（fireside）、十字路口 / OnBoard!（xyzfm）
  · 只下前 N 集、单集上限可配；转写用 small/int8，中文可用
  · 许可：reference_only + personal_noncommercial（老爹个人非商用，不对外分发）

用法：python tools/v9_podcast_asr.py --show 十字路口 --episodes 1 --model small
产出：data/pd/v9_podcast_asr.jsonl（+ cache/podcast_audio/<id>.mp3 与 .json）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pd" / "v9_podcast_asr.jsonl"
AUDIO = ROOT / "cache" / "podcast_audio"
PROXY = "http://127.0.0.1:7897"
FEEDS = {
    "硅谷101": "https://feeds.fireside.fm/sv101/rss",
    "十字路口": "https://feed.xyzfm.space/68fyjknth9hj",
    "OnBoard!": "https://feed.xyzfm.space/xxg7ryklkkft",
}


def opner():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def feed_items(feed: str, limit: int) -> list[dict]:
    xml = opner().open(urllib.request.Request(feed, headers={"User-Agent": "Mozilla/5.0"}),
                       timeout=60).read().decode("utf-8", "replace")
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml, flags=re.S)[:limit]:
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, flags=re.S)
        enc = re.search(r"<enclosure[^>]+url=\"([^\"]+)\"", it)
        ln = re.search(r"<enclosure[^>]+length=\"(\d+)\"", it)
        if not enc:
            continue
        out.append({"title": (t.group(1).strip() if t else "?"),
                    "url": enc.group(1),
                    "mb": round(int(ln.group(1)) / 1024 / 1024, 1) if ln else None})
    return out


def download(url: str, dest: pathlib.Path) -> pathlib.Path:
    if dest.exists() and dest.stat().st_size > 1024 * 1024:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with opner().open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                      timeout=300) as r, dest.open("wb") as fh:
        while True:
            chunk = r.read(1024 * 512)
            if not chunk:
                break
            fh.write(chunk)
    return dest


def transcribe(path: pathlib.Path, model_name: str) -> list[dict]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8",
                         download_root=str(ROOT / "cache" / "hf" / "whisper"))
    segs, info = model.transcribe(str(path), language="zh", vad_filter=True,
                                  beam_size=5, condition_on_previous_text=False)
    out = []
    for s in segs:
        txt = (s.text or "").strip()
        if txt:
            out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": txt})
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # 台账 0815/0837 的老坑：NO_PROXY 里的 [::1] 会让 httpx/huggingface_hub 解析炸掉
    for _k in ("NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(_k, None)
    os.environ["HTTPS_PROXY"] = PROXY
    os.environ["HTTP_PROXY"] = PROXY
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    # 本地缓存目录 + 关掉 symlink/xet（Windows 权限/硬链接会报 os error 5）
    os.environ["HF_HOME"] = str(ROOT / "cache" / "hf")
    os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", default="十字路口")
    ap.add_argument("--episodes", type=int, default=1)
    ap.add_argument("--model", default="small")
    ap.add_argument("--max-mb", type=float, default=80)
    args = ap.parse_args()
    feed = FEEDS.get(args.show)
    if not feed:
        print("未知节目", args.show, file=sys.stderr)
        return 2
    items = [x for x in feed_items(feed, args.episodes * 3)
             if (x.get("mb") or 0) <= args.max_mb][: args.episodes]
    rows = []
    for it in items:
        slug = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", it["title"])[:40]
        mp3 = AUDIO / f"{args.show}_{slug}.mp3"
        print(f"[dl] {it['title'][:50]} ({it['mb']} MB)", flush=True)
        try:
            download(it["url"], mp3)
        except Exception as exc:  # noqa: BLE001
            print("  dl fail", type(exc).__name__, str(exc)[:80], file=sys.stderr)
            continue
        print(f"[asr] {mp3.name} …", flush=True)
        t0 = time.time()
        try:
            segs = transcribe(mp3, args.model)
        except Exception as exc:  # noqa: BLE001
            print("  asr fail", type(exc).__name__, str(exc)[:120], file=sys.stderr)
            continue
        body = "".join(s["text"] for s in segs)
        print(f"  完成 {len(segs)} 段 / {len(body)} 字 / {time.time()-t0:.0f}s", flush=True)
        (AUDIO / f"{mp3.stem}.json").write_text(
            json.dumps({"title": it["title"], "segments": segs}, ensure_ascii=False),
            encoding="utf-8")
        rows.append({"text": body, "title": it["title"], "source": f"podcastasr:{args.show}",
                     "license": "reference_only", "personal_noncommercial": True,
                     "asr": f"faster-whisper-{args.model}", "chars": len(body),
                     "content_hash": hashlib.sha256(body.encode()).hexdigest()[:16]})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if OUT.exists():
        existing = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()]
    have = {x.get("content_hash") for x in existing}
    merged = existing + [x for x in rows if x.get("content_hash") not in have]
    with OUT.open("w", encoding="utf-8") as fh:
        for r in merged:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    rows = merged
    print(json.dumps({"rows": len(rows), "file": str(OUT.relative_to(ROOT))},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
