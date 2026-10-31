"""Music library CLI — the one implementation the DSH plugin shells out to.

Subcommands:
    list   [--query TEXT] [--limit N] [--json]
    info   <handle> [--json]
    play   <handle>
    send   <handle>
    repair [--dry-run]          # rewrite stale absolute paths (2026-10 目录重排后)

`handle` accepts a song id (song_2026...), a 1-based list index, a title
substring, or a tag. The index lives at `cache/songs/songs.json` and is owned by
`backend/song_library.py`; this CLI loads that module directly (by file path) so
it never imports the whole backend package.

Path fallback: after the 2026-10-22 folder restructure the index still points at
`...\\YHLZ\\音频素材\\...` while the files moved under `...\\YHLZ\\YH\\音频素材\\...`.
Read paths try the stored path first, then the `\\YH\\`-inserted variant, so the
library works without rewriting anything; `repair` performs that rewrite (with a
timestamped backup) when you want the index itself clean.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIB_PATH = ROOT / "backend" / "song_library.py"
INDEX = ROOT / "cache" / "songs" / "songs.json"


def _load_library():
    spec = importlib.util.spec_from_file_location("yh_song_library", LIB_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _fmt_time(ts) -> str:
    try:
        v = float(ts or 0)
    except (TypeError, ValueError):
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(v)) if v > 0 else ""


def _stored_path(lib, item: dict) -> pathlib.Path | None:
    raw = item.get("path")
    if raw:
        return pathlib.Path(str(raw))
    name = item.get("file")
    if name:
        return ROOT / "cache" / "songs" / str(name)
    return None


def _remap(p: pathlib.Path) -> pathlib.Path | None:
    """`...\\YHLZ\\<x>` -> `...\\YHLZ\\YH\\<x>` (the 2026-10 restructure)."""
    s = str(p)
    marker = "\\YHLZ\\"
    if marker in s and "\\YHLZ\\YH\\" not in s:
        return pathlib.Path(s.replace(marker, marker + "YH\\", 1))
    return None


def resolve_file(lib, item: dict) -> tuple[pathlib.Path | None, str]:
    """Return (path, how) where how is 'stored' | 'remapped' | 'missing'."""
    p = _stored_path(lib, item)
    if p is None:
        return None, "missing"
    if p.is_file():
        return p, "stored"
    alt = _remap(p)
    if alt is not None and alt.is_file():
        return alt, "remapped"
    return None, "missing"


def _public(lib, item: dict) -> dict:
    path, how = resolve_file(lib, item)
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "tags": item.get("tags") or [],
        "source": item.get("source") or "",
        "target": item.get("target") or "",
        "created": _fmt_time(item.get("created")),
        "path": str(path) if path else None,
        "exists": bool(path),
        "path_state": how,
    }


def cmd_list(lib, query: str, limit: int) -> list[dict]:
    items = [_public(lib, i) for i in lib.list_songs()]
    q = str(query or "").strip().lower()
    if q:
        def hit(it: dict) -> bool:
            hay = " ".join([
                str(it.get("id") or ""), str(it.get("title") or ""),
                " ".join(map(str, it.get("tags") or [])),
                str(it.get("source") or ""),
            ]).lower()
            return q in hay
        items = [i for i in items if hit(i)]
    if limit and limit > 0:
        items = items[:limit]
    return items


def _render_list(items: list[dict]) -> str:
    if not items:
        return "歌库是空的（或没有匹配）。"
    lines = [f"歌库共 {len(items)} 首："]
    for n, it in enumerate(items, 1):
        tags = ("  #" + " #".join(map(str, it["tags"]))) if it.get("tags") else ""
        mark = "" if it.get("exists") else "  [文件缺失]"
        lines.append(f"{n}. 《{it.get('title')}》  {it.get('id')}  {it.get('created')}{tags}{mark}")
    return "\n".join(lines)


def _play_fallback(path: pathlib.Path) -> str:
    """No sounddevice: hand the file to the OS default player."""
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return "交给系统默认播放器"
        return "当前平台不支持自动播放"
    except Exception as exc:  # noqa: BLE001
        return f"启动播放器失败：{type(exc).__name__}"


def cmd_repair(lib, dry_run: bool) -> int:
    """Rewrite `path` entries that only resolve via the \\YH\\ remap."""
    raw = json.loads(INDEX.read_text(encoding="utf-8"))
    changed = []
    for sid, it in raw.items():
        p = _stored_path(lib, it)
        if p is None or p.is_file():
            continue
        alt = _remap(p)
        if alt is not None and alt.is_file():
            changed.append((sid, str(p), str(alt)))
    if not changed:
        print("没有需要修复的条目。")
        return 0
    print(f"可修复 {len(changed)} 条（旧路径 -> 新路径）{'（dry-run，不写盘）' if dry_run else ''}")
    for sid, old, new in changed[:5]:
        print(f"  {sid}\n    旧：{old}\n    新：{new}")
    if len(changed) > 5:
        print(f"  …其余 {len(changed) - 5} 条")
    if dry_run:
        return 0
    backup = INDEX.with_name(INDEX.name + ".bak-" + time.strftime("%Y%m%d%H%M%S"))
    shutil.copyfile(INDEX, backup)
    for sid, _old, new in changed:
        raw[sid]["path"] = new
    INDEX.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写入（备份：{backup.name}）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="music_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--query", default="")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--json", action="store_true")

    for name in ("info", "play", "send"):
        p = sub.add_parser(name)
        p.add_argument("handle")
        if name == "info":
            p.add_argument("--json", action="store_true")

    p_repair = sub.add_parser("repair")
    p_repair.add_argument("--dry-run", action="store_true")

    a = ap.parse_args(argv)
    lib = _load_library()

    if a.cmd == "list":
        items = cmd_list(lib, a.query, a.limit)
        if a.json:
            print(json.dumps(items, ensure_ascii=False))
        else:
            print(_render_list(items))
        return 0

    if a.cmd == "repair":
        return cmd_repair(lib, a.dry_run)

    item = lib.resolve(a.handle)
    if item is None:
        print(f"没有这首歌：{a.handle}")
        return 2
    path, how = resolve_file(lib, item)
    if path is None:
        print(f"《{item.get('title')}》的文件不在了（索引有记录，磁盘上没有）。")
        return 3

    if a.cmd == "info":
        pub = _public(lib, item)
        if a.json:
            print(json.dumps(pub, ensure_ascii=False))
        else:
            print(f"《{pub['title']}》  {pub['id']}")
            print(f"  文件：{pub['path']}")
            print(f"  标签：{'、'.join(map(str, pub['tags'])) or '（无）'}")
            print(f"  创建：{pub['created']}   来源：{pub['source'] or '—'}   对象：{pub['target'] or '—'}")
            if how == "remapped":
                print("  （索引里是旧路径，实际文件在重排后的位置）")
        return 0

    if a.cmd == "play":
        try:
            import sounddevice  # noqa: F401
            import soundfile  # noqa: F401
            import threading
            data, sr = soundfile.read(str(path), dtype="float32")
            threading.Thread(target=lambda: (sounddevice.play(data, int(sr)), sounddevice.wait()),
                             daemon=True, name="song-play").start()
            print(f"正在播放：《{item.get('title')}》")
        except Exception:
            print(f"《{item.get('title')}》：{_play_fallback(path)}")
        return 0

    if a.cmd == "send":
        # backend's send_qq resolves the path itself; with a remapped file we send
        # the resolved path directly through the same NapCat helper.
        if how == "stored":
            print(lib.send_qq(a.handle))
            return 0
        try:
            import asyncio
            tools = str(ROOT / "tools")
            if tools not in sys.path:
                sys.path.insert(0, tools)
            import qq_bot as qb
            cfg = qb._find_onebot_config(None)
            s = qb._ws_settings(cfg)
            url = f"ws://{s['host']}:{s['port']}"
            if s.get("token"):
                url += f"?access_token={s['token']}"
            uri = "file:///" + str(path).replace("\\", "/")
            ev = asyncio.run(qb._napcat_call(
                url, "upload_private_file",
                {"user_id": int(qb.MASTER_UIN), "file": uri, "name": path.name},
                timeout=30))
            if ev and ev.get("status") == "ok":
                print(f"已发送：《{item.get('title')}》")
                return 0
            print(f"QQ 发送失败（{str(ev)[:60]}）")
        except Exception as exc:  # noqa: BLE001
            print(f"QQ 发送异常：{type(exc).__name__}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
