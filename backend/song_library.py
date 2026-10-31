"""Finished-songs library (ledger 0460).

Operator rule: only COMPLETED songs saved locally may be sent/played by the
QQ link or the main chain — singing GENERATION happens in the workbench only.

Layout: cache/songs/<id>.wav + songs.json index (title/source/target/created).
"""
from __future__ import annotations

import json
import pathlib
import threading
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
SONGS_DIR = _ROOT / "cache" / "songs"
INDEX = SONGS_DIR / "songs.json"
_lock = threading.Lock()


def _load() -> dict:
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_index(d: dict) -> None:
    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                     encoding="utf-8")


def save(title: str, wav_path, source: str = "", target: str = "",
         tags: list | None = None) -> dict:
    """Copy a finished wav into the library; returns its index item."""
    src = pathlib.Path(wav_path)
    if not src.is_file():
        raise FileNotFoundError(str(src))
    with _lock:
        d = _load()
        sid = "song_" + time.strftime("%Y%m%d%H%M%S")
        while sid in d:
            sid += "x"
        SONGS_DIR.mkdir(parents=True, exist_ok=True)
        dst = SONGS_DIR / f"{sid}.wav"
        dst.write_bytes(src.read_bytes())
        item = {"id": sid, "title": str(title or sid)[:60], "file": dst.name,
                "source": str(source or "")[:60],
                "target": str(target or "")[:120], "created": time.time(),
                "tags": [str(t)[:20] for t in (tags or [])][:6]}
        d[sid] = item
        _save_index(d)
        return item


def save_ref(title: str, wav_path, source: str = "", target: str = "",
             tags: list | None = None) -> dict:
    """Index an EXISTING wav in place (no copy) — ledger 0464.

    Used for covers that already live in 音频素材/翻唱产出/; the library only
    references them so nothing is stored twice."""
    src = pathlib.Path(wav_path)
    if not src.is_file():
        raise FileNotFoundError(str(src))
    with _lock:
        d = _load()
        sid = "song_" + time.strftime("%Y%m%d%H%M%S")
        while sid in d:
            sid += "x"
        item = {"id": sid, "title": str(title or src.stem)[:60], "file": "",
                "path": str(src), "source": str(source or "")[:60],
                "target": str(target or "")[:120], "created": time.time(),
                "tags": [str(t)[:20] for t in (tags or [])][:6]}
        d[sid] = item
        _save_index(d)
        return item


def set_tags(song_id: str, tags: list) -> str:
    """Attach mood/topic tags for contextual calls (ledger 0463)."""
    with _lock:
        d = _load()
        it = d.get(str(song_id))
        if it is None:
            return f"没有这首歌：{song_id}"
        it["tags"] = [str(t)[:20] for t in (tags or [])][:6]
        _save_index(d)
        return f"已标注《{it.get('title')}》：{'、'.join(it['tags']) or '（空）'}"


def list_songs() -> list[dict]:
    with _lock:
        d = _load()
    items = list(d.values())
    items.sort(key=lambda x: float(x.get("created") or 0), reverse=True)
    return items


def resolve(handle: str) -> dict | None:
    """Find a song by id, exact/partial title, or 1-based list index."""
    h = str(handle or "").strip()
    if not h:
        return None
    songs = list_songs()
    if h in {s.get("id") for s in songs}:
        return next(s for s in songs if s.get("id") == h)
    if h.isdigit():
        i = int(h) - 1
        if 0 <= i < len(songs):
            return songs[i]
    for s in songs:
        if h and h in str(s.get("title") or ""):
            return s
    for s in songs:
        if any(h and h in str(t) for t in (s.get("tags") or [])):
            return s
    return None


def _relocated(p: pathlib.Path) -> pathlib.Path | None:
    """`...\\YHLZ\\<x>` -> `...\\YHLZ\\YH\\<x>`（2026-10-22 目录重排后的兜底）。

    索引里的旧绝对路径在重排后全部失效（59/59）。这里只做**读时兜底**，
    不改写索引；`tools/music_cli.py repair` 才是显式迁移。
    """
    s = str(p)
    marker = "\\YHLZ\\"
    if marker in s and "\\YHLZ\\YH\\" not in s:
        alt = pathlib.Path(s.replace(marker, marker + "YH\\", 1))
        if alt.is_file():
            return alt
    return None


def song_path(song_id: str) -> pathlib.Path | None:
    it = resolve(song_id)
    if not it:
        return None
    if it.get("path"):
        p = pathlib.Path(str(it["path"]))
    else:
        p = SONGS_DIR / str(it.get("file") or "")
    if p.is_file():
        return p
    return _relocated(p)


def play(song_id: str) -> str:
    """Play a saved song on the local speaker (main chain playback)."""
    it = resolve(song_id)
    p = song_path(song_id)
    if it is None or p is None:
        return f"没有这首歌：{song_id}"
    title = str(it.get("title") or it.get("id"))

    def _run() -> None:
        try:
            import sounddevice as sd
            import soundfile as sf

            data, sr = sf.read(str(p), dtype="float32")
            sd.play(data, int(sr))
            sd.wait()
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True, name="song-play").start()
    return f"正在播放：《{title}》"


def send_qq(song_id: str) -> str:
    """Send a saved song to the master over QQ (best effort; needs NapCat)."""
    it = resolve(song_id)
    p = song_path(song_id)
    if it is None or p is None:
        return f"没有这首歌：{song_id}"
    try:
        import asyncio
        import sys

        tools = str(_ROOT / "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import qq_bot as qb

        cfg = qb._find_onebot_config(None)
        s = qb._ws_settings(cfg)
        url = f"ws://{s['host']}:{s['port']}"
        if s.get("token"):
            url += f"?access_token={s['token']}"
        uri = "file:///" + str(p).replace("\\", "/")
        ev = asyncio.run(qb._napcat_call(
            url, "upload_private_file",
            {"user_id": int(qb.MASTER_UIN), "file": uri, "name": p.name},
            timeout=30))
        if ev and ev.get("status") == "ok":
            return f"已发送：《{it.get('title')}》"
        return f"QQ 发送失败（{str(ev)[:60]}）"
    except Exception as exc:  # noqa: BLE001
        return f"QQ 发送异常：{type(exc).__name__}"
