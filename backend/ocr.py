"""Windows 自带 OCR（Windows.Media.Ocr）——不装模型、不联网、不限张数。

为什么用它：手机/电脑的「图片里提取文字」就是这个引擎。它按**原生像素**识别，
所以不需要像 VLM 那样靠缩小放大来凑笔画，整屏 2560×1600 一次就能读。

依赖：`winsdk`（已装，12MB wheel，走清华镜像；不需要额外语言包时用系统已装语言）。

用法：
    from backend import ocr
    ocr.available()              -> bool
    ocr.languages()              -> ['zh-Hans-CN', ...]
    ocr.read(png_path)           -> {"ok", "text", "lines": [...], "ms", "lang"}
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import time

_CJK = r"\u3000-\u9fff\uff00-\uffef"
_SPACE_BETWEEN_CJK = re.compile(rf"(?<=[{_CJK}])\s+(?=[{_CJK}])")


def clean(text: str) -> str:
    """Windows OCR 给中文逐字加空格；合并掉，英文/数字之间的空格保留。"""
    return _SPACE_BETWEEN_CJK.sub("", text)


def _engine():
    from winsdk.windows.media.ocr import OcrEngine

    return OcrEngine.try_create_from_user_profile_languages()


def available() -> bool:
    try:
        return _engine() is not None
    except Exception:
        return False


def languages() -> list[str]:
    try:
        from winsdk.windows.media.ocr import OcrEngine

        return [str(l.language_tag) for l in OcrEngine.available_recognizer_languages]
    except Exception:
        return []


async def _read_async(path: str) -> dict:
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    engine = _engine()
    if engine is None:
        return {"ok": False, "error": "没有可用的 OCR 引擎（系统未装识别语言？）"}
    # 不走 StorageFile（在受限进程里会 E_ACCESSDENIED）：
    # 直接把字节写进内存流，BitmapDecoder 从流里解码。
    data = pathlib.Path(path).read_bytes()
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(data)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    lines = [str(line.text) for line in result.lines]
    return {"ok": True, "text": "\n".join(lines), "lines": lines,
            "lang": str(engine.recognizer_language.language_tag)}


def read(png_path: str | pathlib.Path) -> dict:
    p = pathlib.Path(png_path)
    if not p.is_file():
        return {"ok": False, "error": f"文件不存在：{p}"}
    started = time.time()
    try:
        out = asyncio.run(_read_async(str(p.resolve())))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    out["ms"] = round((time.time() - started) * 1000)
    out["png"] = str(p)
    if out.get("ok"):
        out["lines"] = [clean(x) for x in out.get("lines") or []]
        out["text"] = "\n".join(out["lines"])
    return out


TOOL_NAME = "screen_text"


def capability_result(params: dict | None = None) -> dict:
    """capability 层：截一张原生图 → 系统 OCR → 返回文字（不带图）。"""
    params = dict(params or {})
    region = str(params.get("region") or "").strip() or None
    limit = int(params.get("limit", 120) or 120)
    r = read_screen(region=region)
    if not r.get("ok"):
        return {"text": f"读字失败：{r.get('error') or '未知错误'}", "image": None,
                "ok": False, "error": str(r.get("error") or ""), "lines": 0}
    lines = (r.get("lines") or [])[:max(1, min(400, limit))]
    body = "\n".join(lines)
    head = f"屏幕文字（{len(r.get('lines') or [])} 行，{r.get('ms')}ms"
    head += f"，区域 {region}" if region else "，整屏"
    head += "）："
    return {"text": f"{head}\n{body}"[:4000], "image": None, "ok": True,
            "lines": len(r.get("lines") or []), "ms": r.get("ms")}


def read_screen(region: str | None = None) -> dict:
    """截一张原生分辨率的图再 OCR。region="x,y,w,h" 只读一块。"""
    from backend import see_now

    shot = see_now.capture(raw=True, region=region,
                           out=str(see_now.OUT_DIR / "ocr_shot.png")) if region else \
        see_now.capture_native(out=str(see_now.OUT_DIR / "ocr_shot.png"))
    if not shot.get("ok"):
        return {"ok": False, "error": shot.get("error") or "截图失败",
                "hint": shot.get("hint") or ""}
    out = read(shot["png"])
    out["shot"] = shot.get("png")
    out["size"] = shot.get("size")
    return out


if __name__ == "__main__":
    import json
    import sys

    print("available:", available())
    print("languages:", languages())
    if len(sys.argv) > 1:
        r = read(sys.argv[1])
        print(json.dumps({k: v for k, v in r.items() if k != "lines"},
                         ensure_ascii=False)[:600])
        for line in (r.get("lines") or [])[:10]:
            print("  |", line)
