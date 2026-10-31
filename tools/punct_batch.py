#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给语料文本批量加标点（DeepSeek），失败回退规则加标点。

用法:
  python tools/punct_batch.py --src models/tts/voice_train/yuanheng_bright/data.list \
      --out models/tts/voice_train/yuanheng_bright_C_source.list

规则:
  - 只加标点，绝不改字；校验「去标点后与原文完全一致」；
  - LLM 失败/不一致 -> 规则加标点兜底；
  - 并发 4，批 12 行。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
PUNCT_RE = re.compile(r"[\s，。？！、；：…—,.?!;:()（）\"“”‘’]")
CONJ = ["但是", "因为", "所以", "然后", "就是", "其实", "不过", "而且",
        "如果", "虽然", "要是", "结果", "不然", "反正", "顺便", "回头"]


def load_env() -> None:
    p = ROOT / ".env"
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def core(s: str) -> str:
    return PUNCT_RE.sub("", s)


def rule_punct(text: str) -> str:
    s = text.strip()
    for c in CONJ:
        s = re.sub(rf"(?<!，){re.escape(c)}", "，" + c, s)
    for p in "啊吧呢嘛呀哦嗯":
        s = re.sub(rf"([{p}])(?=[^，。？！])", r"\1，", s)
    s = re.sub(r"，{2,}", "，", s).lstrip("，")
    if s.endswith(("吗", "呢", "吧")):
        s += "？"
    elif s.endswith(("啊", "呀", "啦", "哦")):
        s += "！"
    else:
        s += "。"
    return s


def call_llm(lines: list[str], key: str) -> list[str]:
    sys_prompt = ("你是中文标点修复器。只给句子加标点（，。？！、；：…），"
                  "绝对不要改字、加字、删字、换词。返回 JSON："
                  '{"lines": ["...", "..."]}，数组长度必须与输入相同。')
    payload = {
        "model": "deepseek-chat",
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": json.dumps(lines, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
    }
    r = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        json=payload, timeout=180)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    return json.loads(content)["lines"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch", type=int, default=12)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    load_env()
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise SystemExit("DEEPSEEK_API_KEY missing")

    src = Path(a.src)
    rows = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.count("|") < 3:
            continue
        rel, spk, lang, text = line.split("|", 3)
        rows.append({"rel": rel, "spk": spk, "lang": lang, "text": text.strip(),
                     "idx": len(rows)})
    print(f"rows={len(rows)}", flush=True)

    batches = [rows[i:i + a.batch] for i in range(0, len(rows), a.batch)]
    t0 = time.time()
    results: dict[int, str] = {}
    fails = 0

    def work(batch):
        texts = [r["text"] for r in batch]
        try:
            outs = call_llm(texts, key)
        except Exception:  # noqa: BLE001
            outs = []
        good = 0
        for r, out in zip(batch, outs):
            if isinstance(out, str) and core(out) == core(r["text"]):
                results[r["idx"]] = out
                good += 1
            else:
                results[r["idx"]] = rule_punct(r["text"])
        return good, len(batch)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for good, n in ex.map(work, batches):
            fails += n - good
            print(f"batch good={good}/{n} total_done={len(results)}",
                  flush=True)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"{r['rel']}|{r['spk']}|{r['lang']}|{results[r['idx']]}\n")
    print(json.dumps({"out": str(out), "rows": len(rows),
                      "fallback_or_bad": fails,
                      "secs": round(time.time() - t0, 1)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
