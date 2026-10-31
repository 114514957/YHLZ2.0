#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 HuggingFace 下 parquet 取开源中文对话原话（走系统代理；datasets-server 会 429，故用 parquet 直链）。

用法：
    python tools/v9_hf_dialogue_pull.py --ds zhcompanion
    python tools/v9_hf_dialogue_pull.py --ds lccc --files 1
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OPENER = urllib.request.build_opener()      # 走系统代理（127.0.0.1:7897）
OUT = os.path.join(ROOT, "cache", "v9_open_corpus", "20261020_hf")

DS = {
    "lccc": ("silver/lccc", "base", "MIT",
             "LCCC 真实中文对话（dialog 数组，分词带空格）"),
    "zhcompanion": ("zhcompanion/companion-roleplay-sft", "default", "cc-by-nc-4.0",
                    "陪伴角色扮演，多轮 messages，繁体"),
    "emotion": ("LooksJuicy/Chinese-Emotional-Intelligence", "default", "apache-2.0",
                "情商问答 instruction/output"),
    "adorable": ("MemorialSummer/chinese-adorable-high-emotional-intelligence-chat",
                 "default", "cc-by-4.0", "高情商可爱聊天 user/girl"),
}


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "yhlz/1.0"})
    with OPENER.open(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main() -> int:
    import pandas as pd

    ap = argparse.ArgumentParser()
    ap.add_argument("--ds", required=True, choices=list(DS))
    ap.add_argument("--files", type=int, default=1, help="train 切分下取几个 parquet")
    a = ap.parse_args()
    ds, cfg, lic, note = DS[a.ds]
    os.makedirs(OUT, exist_ok=True)

    u = "https://huggingface.co/api/datasets/%s/parquet/%s" % (
        urllib.parse.quote(ds), urllib.parse.quote(cfg))
    d = get_json(u)
    urls = (d.get("train") or [])[: a.files]
    print("%s ｜%s ｜%s" % (ds, lic, note))
    print("train parquet %d/%d 个，取前 %d 个" % (len(d.get("train") or []), len(urls), len(urls)))

    frames = []
    for i, url in enumerate(urls):
        p = os.path.join(OUT, "%s_train%d.parquet" % (a.ds, i))
        if not os.path.exists(p):
            req = urllib.request.Request(url, headers={"User-Agent": "yhlz/1.0"})
            with OPENER.open(req, timeout=300) as r:
                data = r.read()
            open(p, "wb").write(data)
            print("   下载 %s %.1f MB" % (os.path.basename(p), len(data) / 1e6))
        else:
            print("   已存在 %s" % os.path.basename(p))
        frames.append(pd.read_parquet(p))
    df = pd.concat(frames, ignore_index=True)
    print("总行数 %d ｜列 %s" % (len(df), list(df.columns)))

    p = os.path.join(OUT, "%s.jsonl" % a.ds)
    with io.open(p, "w", encoding="utf-8") as fh:
        for rec in df.to_dict("records"):
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    print("已写 -> %s" % os.path.relpath(p, ROOT))
    print("样例: %s" % json.dumps(df.iloc[0].to_dict(), ensure_ascii=False,
                                  default=str)[:420])
    return 0


if __name__ == "__main__":
    sys.exit(main())
