"""元亨的「看一眼屏幕」接口 —— 把 dsh-see-now 当普通 Node 库调用（2026-11-04）。

为什么这么接：dsh-see-now 是 DSH 插件，但它的 capture/pipeline/pack/png/tokens
都是纯模块、零 dependencies。所以元亨不需要装 DSH 插件，只要：
    node tools/see_now_bridge.mjs --capture --seconds N --quality low
拿回 {png, tokens, frames, spans}，再把 png 作为 image_url 塞进消息。

本机现状：ffmpeg 缺失 → `capture()` 会如实返回 ok=False + hint；
`probe()` 不依赖 ffmpeg，用合成画面验证打包/编码/token 口径（0.1.1 实测 798x462 = 222 token）。

接口约定（给 capability 层）：
    TOOL_NAME   = "see_now"
    TOOL_SPEC   = {...OpenAI function schema...}
    capture(seconds=6, quality="low", region=None) -> dict
    as_image_part(png_path) -> {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from typing import Literal

from pydantic import BaseModel, Field

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "tools" / "see_now_bridge.mjs"
OUT_DIR = ROOT / "cache" / "tmp"
NODE = "node"

# 上一次成功抓屏的墙上时间（秒）；模块级，够挡住同一进程里的连拍。
_LAST_CAPTURE_AT = 0.0


def ffmpeg_path() -> str:
    """按可靠度找 ffmpeg：环境变量 → imageio-ffmpeg 自带 → PATH。"""
    env = str(os.getenv("YHLZ_FFMPEG", "") or "").strip()
    if env and pathlib.Path(env).is_file():
        return env
    try:
        import imageio_ffmpeg  # 已装（imageio 的依赖），自带一份静态 ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and pathlib.Path(exe).is_file():
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg") or "ffmpeg"

TOOL_NAME = "see_now"


class SeeNowArgs(BaseModel):
    """工具参数（typed：schema 里 raw 是 bool、quality 是枚举，模型更好用）。"""

    seconds: int = Field(6, ge=3, le=20, description="看最近多少秒（默认 6）")
    quality: Literal["low", "standard", "high", "ultra"] = Field(
        "low", description="画质档：low 222 token；越高越贵")
    region: str = Field("", description='只看一块 "x,y,w,h"（屏幕物理像素）；不给=整屏')
    raw: bool = Field(
        False,
        description="读字模式：一帧原生像素、不缩放（必须配合 region）。"
                    "问“上面写了什么字”时用它，比拼图更清楚也更省 token。")

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "看一眼老爹现在的屏幕。返回一张按「变化量」筛过的拼图（静止画面几乎不出图），"
            "外加每格的相对秒数。默认 low 档只够看布局与颜色，看不清小字；"
            "**要读具体文字：传 region 框住那块 + raw=true**（原生像素，实测读得准且 token 更少）。"
            "读不清就说读不清，不要编具体文字。"
            "适合：老爹说“这个界面怎么不对”/“看我在干什么”时。不要连续频繁调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "description": "看最近多少秒（3-20，默认 6）",
                },
                "quality": {
                    "type": "string",
                    "enum": ["low", "standard", "high", "ultra"],
                    "description": "画质档；low=222 token，越高越贵",
                },
                "region": {
                    "type": "string",
                    "description": "只看一块 x,y,w,h（屏幕物理像素）；不给就是整屏",
                },
            },
        },
    },
}


def _run_bridge(args: list[str], timeout: int = 120) -> dict:
    cmd = [NODE, str(BRIDGE), *args]
    proc = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout)
    lines = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()]
    payload: dict = {}
    if lines:
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError:
            payload = {"ok": False, "error": f"bridge 输出不可解析：{lines[-1][:200]}"}
    else:
        payload = {"ok": False,
                   "error": f"bridge 无输出（exit={proc.returncode}）",
                   "stderr": (proc.stderr or "")[-400:]}
    payload.setdefault("stderr", (proc.stderr or "")[-400:])
    return payload


def probe(quality: str = "low", out: str | None = None) -> dict:
    """不依赖 ffmpeg 的自检：合成画面 → 拼图 → 返回 png 与 token 数。"""
    target = out or str(OUT_DIR / "see_now_probe.png")
    return _run_bridge(["--probe", "--quality", quality, "--out", target])


def capture(seconds: int = 6, quality: str = "low", region: str | None = None,
            out: str | None = None, raw: bool = False) -> dict:
    """真抓屏。需要 ffmpeg；失败时返回 ok=False + hint。

    raw=True → 读字模式：一帧、原生像素、不缩放（必须给 region）。
    实测同样的字：全屏 low 拼图读不出来/会编；420x240 原生裁剪读得准，且 token 更少。
    """
    target = out or str(OUT_DIR / ("see_now_raw.png" if raw else "see_now_capture.png"))
    if raw:
        if not region:
            return {"ok": False, "error": "raw 模式需要 region（整屏原图太大）",
                    "hint": "先框一块窗口：region=x,y,w,h"}
        args = ["--raw", "--region", region, "--out", target, "--ffmpeg", ffmpeg_path()]
    else:
        args = ["--capture", "--quality", quality,
                "--seconds", str(max(3, min(20, int(seconds)))),
                "--out", target, "--ffmpeg", ffmpeg_path()]
        if region:
            args += ["--region", region]
    payload = _run_bridge(args, timeout=max(60, int(seconds) + 60))
    if payload.get("ok") and payload.get("png"):
        payload["abs_path"] = str(pathlib.Path(payload["png"]).resolve())
    return payload


def capture_native(out: str | None = None) -> dict:
    """整屏原生分辨率单帧（给 OCR 用：不缩放，字是全像素）。"""
    target = out or str(OUT_DIR / "see_now_native.png")
    payload = _run_bridge(["--raw", "--out", target, "--ffmpeg", ffmpeg_path()],
                          timeout=90)
    if payload.get("ok") and payload.get("png"):
        payload["abs_path"] = str(pathlib.Path(payload["png"]).resolve())
    return payload


def as_image_part(png_path: str) -> dict:
    """PNG → OpenAI 兼容的 image_url part（与 target_orchestrator._to_data_url 同口径）。"""
    data = pathlib.Path(png_path).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


def capability_result(params: dict | None = None) -> dict:
    """capability 层的 handler：一次调用 = 看一次屏幕。

    返回 dict（不是字符串）：orchestrator 见到 image 会把图拼进工具结果；
    只认 text 的调用方（日志/证据/读回）仍拿得到字符串。

    节流（台账 1082 的 P3）：
      * 两次成功抓屏之间至少 `YHLZ_SEE_NOW_GAP` 秒（默认 20）；
      * 每次调用写一行 `cache/logs/see_now.log`；
      * 频率上限之内再来的调用**不抓屏**，直接回一句提示，省 token。
    """
    params = dict(params or {})
    seconds = int(params.get("seconds", 6) or 6)
    quality = str(params.get("quality", "low") or "low")
    region = params.get("region") or None
    raw = str(params.get("raw", "")).strip().lower() in ("1", "true", "yes", "on")
    gap = float(os.getenv("YHLZ_SEE_NOW_GAP", "20") or 20)

    global _LAST_CAPTURE_AT
    now = time.time()
    if _LAST_CAPTURE_AT and now - _LAST_CAPTURE_AT < gap:
        left = int(gap - (now - _LAST_CAPTURE_AT)) + 1
        text = f"刚看过屏幕（{int(now - _LAST_CAPTURE_AT)} 秒前），{left} 秒后再看。"
        _log_line(f"throttled gap={left}s")
        return {"text": text, "image": None, "tokens": 0, "frames": [],
                "spans": [], "ok": True, "error": "", "throttled": True}

    payload = capture(seconds=seconds, quality=quality, region=region, raw=raw)
    ok = bool(payload.get("ok"))
    if ok:
        _LAST_CAPTURE_AT = now
    _log_line(
        f"capture ok={ok} mode={'raw' if raw else 'sheet'} seconds={seconds} "
        f"quality={quality} region={region or '-'} "
        f"frames={len(payload.get('frames') or [])} tokens={payload.get('tokens')} "
        f"size={payload.get('size')} png={payload.get('png')} err={payload.get('error') or ''}")
    return {
        "text": render_summary(payload),
        "image": payload.get("png") if ok else None,
        "tokens": payload.get("tokens"),
        "frames": payload.get("frames") or [],
        "spans": payload.get("spans") or [],
        "ok": ok,
        "error": "" if ok else str(payload.get("error") or ""),
    }


def _log_line(line: str) -> None:
    try:
        path = ROOT / "cache" / "logs" / "see_now.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {line}\n")
    except Exception:
        pass


def render_summary(payload: dict) -> str:
    """给模型看的一句文本摘要（图之外的口径）。"""
    if not payload.get("ok"):
        return f"看屏幕失败：{payload.get('error', '未知错误')}（{payload.get('hint', '')}）".strip()
    if payload.get("mode") == "raw":
        w, h = payload.get("size") or ["?", "?"]
        return f"屏幕原图裁剪：{w}x{h} 原生像素（不缩放，读字用）。"
    frames = payload.get("frames") or []
    spans = payload.get("spans") or [0, 0]
    times = ", ".join(f"{f.get('t')}s" for f in frames)
    return (f"屏幕拼图：{len(frames)} 帧（{spans[0]}~{spans[1]}s：{times}），"
            f"{payload.get('size', ['?', '?'])[0]}x{payload.get('size', ['?', '?'])[1]}，"
            f"{payload.get('tokens')} token。")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    result = probe() if mode == "probe" else capture()
    print(json.dumps(result, ensure_ascii=False, indent=1)[:1200])
    print("summary:", render_summary(result))
