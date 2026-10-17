"""会话存档迁移工具（ledger 0817）。

`save_session` 的守卫拒绝静默接管"无 channel 的旧存档"（防公共来源被悄悄覆盖），
于是 2026-10-13 群 `1094579571` 的会话**每轮都保存失败**、上下文从不落盘——
表现就是老爹说的"精分/重复读上下文"。

本工具把那一步**显式化**：默认只扫描（dry-run），`--apply` 才迁移；迁移先备份到
`cache/sessions/_migrated/`，再补 `channel`。

用法：
    python tools/migrate_sessions.py                 # 扫描，列出待迁移
    python tools/migrate_sessions.py --apply         # 迁移能从文件名判定归属的
    python tools/migrate_sessions.py --apply --all-qq  # 连 qq_qq_g* 之外的 qq_* 也按名迁移
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

SESSIONS = ROOT / "cache" / "sessions"
NAME_RE = re.compile(r"^qq_(?P<channel>qq_[pg]\d+|public)$")


def classify(name: str) -> str | None:
    """从存档名推断 channel（只认形状明确的 qq_qq_<g|p><数字> / qq_public）。"""
    m = NAME_RE.match(name)
    return m.group("channel") if m else None


def scan() -> list[dict]:
    out: list[dict] = []
    for p in sorted(SESSIONS.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            out.append({"name": p.stem, "state": f"unreadable:{type(exc).__name__}"})
            continue
        if not isinstance(d, dict):
            out.append({"name": p.stem, "state": "not-an-object"})
            continue
        ch = d.get("channel")
        out.append({"name": p.stem,
                    "state": "ok" if ch else "legacy-no-channel",
                    "channel": ch, "turns": d.get("turns"),
                    "guess": classify(p.stem), "size": p.stat().st_size})
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="迁移无 channel 的旧会话存档")
    ap.add_argument("--apply", action="store_true", help="真的迁移（默认只扫描）")
    args = ap.parse_args()

    from backend.target_entry import ConversationSession

    rows = scan()
    todo = [r for r in rows if r["state"] == "legacy-no-channel"]
    print(f"共 {len(rows)} 个存档，其中待迁移 {len(todo)} 个：")
    for r in rows:
        tag = {"ok": "✓", "legacy-no-channel": "!"}.get(r["state"], "?")
        print(f"  {tag} {r['name']:36s} channel={str(r.get('channel')):20s} "
              f"turns={str(r.get('turns')):>4s} → 推断={r.get('guess') or '（无法从名推断）'}")
    if not args.apply:
        print("\n（dry-run；加 --apply 执行迁移，迁移前自动备份到 cache/sessions/_migrated/）")
        return 0
    done = skipped = 0
    for r in todo:
        if not r.get("guess"):
            print(f"  跳过 {r['name']}：无法从文件名判定归属（需人工指定 channel）")
            skipped += 1
            continue
        rep = ConversationSession.migrate_legacy_archive(r["name"], r["guess"])
        print(f"  {r['name']} → {rep}")
        done += 1 if rep.get("ok") else 0
        skipped += 0 if rep.get("ok") else 1
    print(f"\n迁移完成：成功 {done}，跳过 {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
