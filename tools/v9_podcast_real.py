"""英文 AI 播客转写 → 中文（ledger 0911）。

老爹：「why not，Lex Fridman、Latent Space 都是优秀播客」。
英文转写确实能下，但直接进中文语料没用；这里做**机器翻译**，只取技术内容：
  · 源：HF `Whispering-GPT/lex-fridman-podcast`（346 集）、
        `Faraz-Ahmad/latent-space-podcast-archive`（3 集）
  · 挑 AI 相关标题；每集截前 ~5000 字符，按 1200 字符分块译成中文口语
  · 标 machine_translated / reference_only；不伪装成中文原创

用法：python tools/v9_podcast_real.py --episodes 3
产出：data/pd/v9_podcast_real_zh.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pd" / "v9_podcast_real_zh.jsonl"
PROXY = "http://127.0.0.1:7897"
SRC = {
    "lex": ("Whispering-GPT/lex-fridman-podcast", "text"),
    "latent": ("Faraz-Ahmad/latent-space-podcast-archive", "transcript"),
}
AI_WORDS = ("AI", "LLM", "AGI", "DeepSeek", "OpenAI", "GPT", "model", "agent",
            "transformer", "reasoning", "scaling")


def opner():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def rows(repo: str, n: int, offset: int = 0) -> list[dict]:
    q = urllib.parse.urlencode({"dataset": repo, "config": "default", "split": "train",
                                "offset": offset, "length": n})
    d = json.loads(opner().open(urllib.request.Request(
        "https://datasets-server.huggingface.co/rows?" + q,
        headers={"User-Agent": "YHLZ/1.0"}), timeout=60).read())
    return [((x.get("row") or {})) for x in d.get("rows") or []]


def translate(base: str, text: str, retries: int = 2) -> str:
    body = {"model": "local",
            "messages": [{"role": "system",
                          "content": "你是翻译。把英文播客转写译成中文口语，保留技术术语，"
                                     "不要总结、不要省略，逐句译。"},
                         {"role": "user", "content": text}],
            "temperature": 0.2, "max_tokens": min(1600, len(text) * 3)}
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    last = None
    for i in range(retries + 1):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=240).read())
            return str((d.get("choices") or [{}])[0].get("message", {}).get("content") or "")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(3)
    raise last  # type: ignore[misc]


def chunks(text: str, size: int = 1200) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8081")
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--chars", type=int, default=4000)
    args = ap.parse_args()
    out, stats = [], {}
    for show, (repo, field) in SRC.items():
        try:
            all_rows = rows(repo, 50)
        except Exception as exc:  # noqa: BLE001
            print(f"[{show}] rows fail {type(exc).__name__}", file=sys.stderr)
            continue
        picked = []
        for r in all_rows:
            title = str(r.get("title") or r.get("episode_title") or "")
            if any(w.lower() in title.lower() for w in AI_WORDS):
                picked.append(r)
            if len(picked) >= args.episodes:
                break
        n = 0
        for r in picked:
            title = str(r.get("title") or r.get("episode_title") or "")
            text = str(r.get(field) or "")
            if len(text) < 800:
                continue
            piece = text[: args.chars]
            zh = []
            for ch in chunks(piece):
                try:
                    zh.append(translate(args.base, ch))
                except Exception as exc:  # noqa: BLE001
                    print(f"[{show}] translate fail: {type(exc).__name__}", file=sys.stderr)
                    zh = []
                    break
            if not zh:
                continue
            body = "\n".join(zh)
            # 质量门：重复行/短译/占位符堆叠直接丢（gemma 会掉进"（沉默）……"循环）
            lines = [x for x in body.splitlines() if x.strip()]
            if lines and max(lines.count(x) for x in set(lines)) > 3:
                print(f"  ✗ {show} 重复行过多，丢弃", file=sys.stderr)
                continue
            if len(body) < len(piece) * 0.3:
                print(f"  ✗ {show} 译文过短，丢弃", file=sys.stderr)
                continue
            if body.count("沉默") > 3 or body.count("……") > 20:
                print(f"  ✗ {show} 占位符过多，丢弃", file=sys.stderr)
                continue
            out.append({"text": body, "source": f"podcastreal:{show}", "title": title,
                        "license": "reference_only", "machine_translated": True,
                        "original_lang": "en", "source_url":
                        f"https://huggingface.co/datasets/{repo}",
                        "chars": len(body),
                        "content_hash": hashlib.sha256(body.encode()).hexdigest()[:16]})
            n += 1
            print(f"  ✓ {show} / {title[:60]} → {len(body)} 字", flush=True)
            time.sleep(1)
        stats[show] = n
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(out), "by_show": stats,
                      "file": str(OUT.relative_to(ROOT))}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
