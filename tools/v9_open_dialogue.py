"""开放对话数据集 → 语料（ledger 0908）。

把 `data/v9_open_pull/*.json` 里的对话型数据集转成 speaking 文档：
  · emotion-intel      instruction → output（1 轮，apache-2.0）
  · adorable-eq        user → girl（1 轮，cc-by-4.0）
  · roleplay-novel     conversations 多轮（≤8 轮成篇，apache-2.0）
  · companion-sft      messages 多轮（cc-by-nc-4.0 → 记 nc_only）
  · multi-emotion      只有单句+情绪标签，**不是对话**，跳过

产出：data/pd/v9_open_dialogue.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "v9_open_pull"
OUT = ROOT / "data" / "pd" / "v9_open_dialogue.jsonl"


def doc(text: str, slug: str, lic: str, i: int, role: str = "open") -> dict:
    return {"text": text, "source": f"open:{slug}", "source_id": f"odlg#{slug}#{i}",
            "group_id": f"open:{slug}", "license": lic,
            "chars": len(text),
            "content_hash": hashlib.sha256(text.encode()).hexdigest()[:16]}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-turns", type=int, default=8)
    args = ap.parse_args()
    rows, stats = [], {}
    for p in sorted(SRC.glob("*.json")):
        if p.name == "manifest.json":
            continue
        obj = json.loads(p.read_text(encoding="utf-8"))
        data = obj.get("data") or []
        lic = obj.get("license") or "unknown"
        slug = p.stem
        n = 0
        for item in data:
            inner = item.get("row") if isinstance(item, dict) else None
            if not isinstance(inner, dict):
                inner = {}
            text = ""
            if "instruction" in inner and "output" in inner:
                q, a = str(inner["instruction"]).strip(), str(inner["output"]).strip()
                inp = str(inner.get("input") or "").strip()
                if inp:
                    q = (q + "\n" + inp).strip()
                if 6 <= len(q) <= 800 and 4 <= len(a) <= 600:
                    text = f"用户：{q}\n对方：{a}"
            elif "user" in inner and "girl" in inner:
                q, a = str(inner["user"]).strip(), str(inner["girl"]).strip()
                if 4 <= len(q) <= 200 and 4 <= len(a) <= 300:
                    text = f"用户：{q}\n对方：{a}"
            elif "conversations" in inner:
                turns = inner.get("conversations") or []
                lines = []
                for t in turns[: args.max_turns]:
                    if isinstance(t, dict):
                        who = str(t.get("role") or t.get("from") or "?")
                        say = str(t.get("content") or t.get("value") or "").strip()
                        if say:
                            lines.append(f"{who}：{say}")
                if len(lines) >= 2:
                    text = "\n".join(lines)
            elif "messages" in inner:
                lines = []
                for m in (inner.get("messages") or [])[: args.max_turns]:
                    role = str(m.get("role") or "?")
                    say = str(m.get("content") or "").strip()
                    if role != "system" and say:
                        lines.append(f"{role}：{say}")
                if len(lines) >= 2:
                    text = "\n".join(lines)
            if len(text) < 20:
                continue
            lic2 = "nc_only" if "nc" in lic.lower() else lic
            rows.append(doc(text, slug, lic2, n))
            n += 1
        stats[slug] = n
        print(f"  {slug}: {n} 篇（{lic}）")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(rows), "by_dataset": stats,
                      "file": str(OUT.relative_to(ROOT))}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
