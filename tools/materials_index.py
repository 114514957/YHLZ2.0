"""Materials library index for Yuanheng's persona dataset (ledger 0345).

Scans every local source that can feed dataset building and writes a catalog to
`docs/素材库.md` (+ `data/finetune/materials.json`). Roles:
  - 人格核心   : owner-approved golden samples / real 老爹<->元亨 pairs
  - 元亨记忆   : L2 memory store
  - 元亨关系   : entity/relation graph
  - 元亨知识   : knowledge base
  - 元亨文字   : 认知根基 / 日记 / 成长日志 / 哲学笔记
  - 通用语料   : QQ group corpus (others' talk; knowledge only)
  - 风格参考   : external style references (galgame / ATRI / 大肥鱼) — NOT persona data

Usage:
    python tools/materials_index.py            # 扫描并写目录
    python tools/materials_index.py --list     # 只打印
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(r"C:/Users/ACE_WA~1/AppData/Local/Temp/opencode")


def _count_lines(p: Path) -> int | None:
    if not p.exists():
        return None
    if p.is_dir():
        return sum(1 for f in p.rglob("*") if f.is_file())
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:  # noqa: BLE001
        return None


def _sql_count(db: Path, sql: str) -> int | None:
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(str(db))
        n = con.execute(sql).fetchone()[0]
        con.close()
        return n
    except Exception:  # noqa: BLE001
        return None


def _golden_count() -> int | None:
    try:
        from tools.golden_build import load_golden
        return sum(1 for g in load_golden() if g["status"] in ("keep", "fixed"))
    except Exception:  # noqa: BLE001
        return None


def collect() -> list[dict]:
    def item(cat, name, path, count, note, license_="内部"):
        return {"category": cat, "name": name, "path": str(path), "count": count,
                "note": note, "license": license_}

    items = [
        item("人格核心", "黄金样本(persona_golden)", ROOT / "tools" / "persona_golden.md",
             _golden_count(), "老爹批准的元亨口吻样本", "内部"),
        item("人格核心", "真实对白(sft_persona)", ROOT / "data" / "finetune" / "sft_persona.jsonl",
             _count_lines(ROOT / "data" / "finetune" / "sft_persona.jsonl"), "老爹↔元亨真实会话对", "内部"),
        item("人格核心", "结构化记忆样本(生成中)", ROOT / "data" / "finetune" / "persona_memory.jsonl",
             _count_lines(ROOT / "data" / "finetune" / "persona_memory.jsonl"), "记忆→问答(带emo/scene/关系)", "内部"),
        item("元亨记忆", "L2 记忆库", ROOT / "cache" / "memstore" / "memstore.db",
             _sql_count(ROOT / "cache" / "memstore" / "memstore.db",
                        "SELECT COUNT(*) FROM l2_items WHERE status='active'"),
             "active 记忆条", "内部"),
        item("元亨关系", "实体/关系图", ROOT / "cache" / "entity_graph.db",
             _sql_count(ROOT / "cache" / "entity_graph.db", "SELECT COUNT(*) FROM relations"),
             "关系三元组", "内部"),
        item("元亨知识", "知识库(yuanheng_kb)", ROOT / "data" / "yuanheng_kb.db",
             _sql_count(ROOT / "data" / "yuanheng_kb.db", "SELECT COUNT(*) FROM kb_items"),
             "QQ提炼知识", "内部"),
        item("元亨文字", "认知根基", ROOT / "docs" / "元亨认知根基.md",
             _count_lines(ROOT / "docs" / "元亨认知根基.md"), "世界观/哲学/四德", "内部"),
        item("元亨文字", "日记", ROOT / "docs" / "元亨的日记.md",
             _count_lines(ROOT / "docs" / "元亨的日记.md"), "元亨第一人称", "内部"),
        item("元亨文字", "成长日志", ROOT / "docs" / "元亨的成长日志.md",
             _count_lines(ROOT / "docs" / "元亨的成长日志.md"), "记忆/冲突/快照事件流", "内部"),
        item("元亨文字", "哲学笔记", ROOT / "docs" / "notes_inbox" / "philosophy_notes.md",
             _count_lines(ROOT / "docs" / "notes_inbox" / "philosophy_notes.md"), "老爹哲学", "内部"),
        item("通用语料", "QQ 语料(清洗)", ROOT / "data" / "finetune" / "corpus_qq.jsonl",
             _count_lines(ROOT / "data" / "finetune" / "corpus_qq.jsonl"), "他人技术讨论→仅知识", "内部"),
        item("通用语料", "QQ 原文(训练)", ROOT / "data" / "finetune" / "corpus_qq_raw.jsonl",
             _count_lines(ROOT / "data" / "finetune" / "corpus_qq_raw.jsonl"), "原文本", "内部"),
        item("风格参考", "galgame 对白(cross-channel)", TMP / "galgame_ref.txt",
             _count_lines(TMP / "galgame_ref.txt"), "语气参考,禁入库", "版权"),
        item("风格参考", "ATRI 角色素材", Path(r"C:/Users/ACE_WAN——PROJECT/Downloads/2inATRI.jsonl"),
             _count_lines(Path(r"C:/Users/ACE_WAN——PROJECT/Downloads/2inATRI.jsonl")),
             "含 memory_hook/emotion/scene 方法论", "版权"),
        item("风格参考", "大肥鱼人设/台词", TMP / "dafeiyu-pet",
             None, "社区傲娇可爱人设+台词(MIT)", "MIT"),
    ]
    return items


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="元亨素材库索引")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    items = collect()

    if not args.list:
        out_json = ROOT / "data" / "finetune" / "materials.json"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        lines = ["# 元亨素材库", "",
                 "> 由 `tools/materials_index.py` 生成。`count` 为条/行数；`风格参考` 仅学语气，",
                 "> **不入库、不当人格数据**。", "",
                 "| 类别 | 素材 | 数量 | 许可 | 路径 | 备注 |",
                 "|---|---|---|---|---|---|"]
        for it in items:
            c = "缺失" if it["count"] is None else it["count"]
            lines.append(f"| {it['category']} | {it['name']} | {c} | {it['license']} | "
                         f"`{it['path']}` | {it['note']} |")
        (ROOT / "docs" / "素材库.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[ok] -> docs/素材库.md, data/finetune/materials.json ({len(items)} 项)")

    for it in items:
        c = "缺失" if it["count"] is None else it["count"]
        print(f"  [{it['category']}] {it['name']}: {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
