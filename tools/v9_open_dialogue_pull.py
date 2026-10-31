#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""拉开源中文对话语料（HF 不通，走 ModelScope + GitHub）。

依据 `docs/报告/HF开源素材集候选清单_20261008.md`：
  · HF 主站/镜像/datasets-server 实测**全不通**（WinError 10060 / 超时）
  · ModelScope 与 GitHub raw **可通** → 只拉这两个源上有的候选
  · 口径：外部对白**只作学习证据，不复制台词入 SFT**（见《开源素材元亨适配筛选》）

用法：
    python tools/v9_open_dialogue_pull.py --list
    python tools/v9_open_dialogue_pull.py --pull
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
OUT = os.path.join(ROOT, "cache", "v9_open_corpus", "20261020")

# (代号, 平台, 仓库, 文件路径, 许可, 说明)
SOURCES = [
    ("THE", "modelscope", "catbohe/TreeHoleEcho", "data.jsonl",
     "Apache-2.0", "树洞回声：共情倾听 1012 条单轮"),
    ("ARYA", "modelscope", "newcjh/Arya", "Arya.json",
     "未标注（待核）", "中文角色扮演对话"),
    ("HANA", "modelscope", "xuanxixue/HANA", "sample/README.md",
     "未标注（待核）", "HANA 对话集（先看 sample 目录）"),
]


def ms_url(ds: str, path: str) -> str:
    return ("https://modelscope.cn/api/v1/datasets/%s/repo"
            "?Revision=master&FilePath=%s" % (ds, urllib.request.quote(path)))


def ms_tree(ds: str, path: str = "") -> list[dict]:
    import urllib.parse
    url = ("https://modelscope.cn/api/v1/datasets/%s/repo/tree"
           "?Revision=master&Path=%s" % (ds, urllib.parse.quote(path)))
    req = urllib.request.Request(url, headers={"User-Agent": "yhlz/1.0"})
    with OPENER.open(req, timeout=40) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    return (d.get("Data") or {}).get("Files") or []


def fetch(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "yhlz/1.0"})
    with OPENER.open(req, timeout=timeout) as r:
        return r.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--pull", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    if a.list:
        for code, plat, repo, path, lic, note in SOURCES:
            print("%-5s %-11s %-32s %-20s %-16s %s"
                  % (code, plat, repo, path, lic, note))
        print("\nModelScope 目录树：")
        for ds in ("xuanxixue/HANA", "newcjh/Arya"):
            try:
                fs = ms_tree(ds)
                print("  %s → %s" % (ds, [(f.get('Path'), f.get('Type')) for f in fs[:8]]))
                for f in fs:
                    if f.get("Type") != "blob":
                        sub = ms_tree(ds, f.get("Path"))
                        print("     %s/ → %s" % (f.get("Path"),
                                                 [x.get('Path') for x in sub[:8]]))
            except Exception as e:
                print("  %s ❌ %s" % (ds, str(e)[:70]))
        return 0

    if not a.pull:
        ap.print_help()
        return 2

    manifest = []
    for code, plat, repo, path, lic, note in SOURCES:
        try:
            data = fetch(ms_url(repo, path))
        except Exception as e:
            print("  ❌ %-5s %s: %s" % (code, repo, str(e)[:80]))
            continue
        ext = os.path.splitext(path)[1] or ".bin"
        dst = os.path.join(OUT, "%s_%s%s" % (code, repo.split("/")[-1], ext))
        open(dst, "wb").write(data)
        # 统计
        rows = 0
        try:
            if ext == ".jsonl":
                rows = sum(1 for x in io.open(dst, encoding="utf-8", errors="replace")
                           if x.strip())
            elif ext == ".json":
                obj = json.load(io.open(dst, encoding="utf-8-sig", errors="replace"))
                rows = len(obj) if hasattr(obj, "__len__") else 1
        except Exception:
            pass
        print("  ✅ %-5s %-28s %8.1f KB  %s 行/项"
              % (code, os.path.basename(dst), len(data) / 1024, rows or "?"))
        manifest.append({"code": code, "repo": repo, "path": path, "license": lic,
                         "note": note, "file": os.path.basename(dst),
                         "bytes": len(data), "rows": rows})

    io.open(os.path.join(OUT, "MANIFEST.json"), "w", encoding="utf-8").write(
        json.dumps({"pulled_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
                    "sources": manifest}, ensure_ascii=False, indent=1) + "\n")
    print("\n清单 -> %s" % os.path.join(OUT, "MANIFEST.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
