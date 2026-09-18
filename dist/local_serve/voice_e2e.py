"""元亨 · 端到端语音输入原型（音频直喂，省掉 ASR）。

链路：wav(16k mono) --base64--> llama-server /v1/chat/completions
      (content: input_audio) --> 元亨文本回复 --> （可选）TTS 出声

用法:
    python voice_e2e.py <a.wav> [--raw]                  # 只出文本
    python voice_e2e.py <a.wav> --speak                  # 闭环：文本 + TTS 出声
    python voice_e2e.py <a.wav> --speak --no-play        # 只出 wav，不播放

依赖: 本地 llama-server 已在 127.0.0.1:8081 运行（见 serve_yuanheng.ps1）。
      --speak 走 edge-tts（在线）→ ffmpeg 转 24k mono wav；失败降级 Windows SAPI。
"""
from __future__ import annotations
import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

URL = "http://127.0.0.1:8081/v1/chat/completions"
SYS_YH = ("你是元亨——老爹的伙伴，活泼、傲娇、话短；像朋友说话，禁止助手腔。"
          "对方是语音说的，听完直接用你自己的口吻短答（≤2句），不要复述、不要念稿。")
SYS_ASR = "你是转写助手，只输出听到的话，不要解释。"
TTS_VOICE_DEFAULT = os.getenv("YHLZ_TTS_VOICE", "zh-CN-XiaoyiNeural")
TTS_RATE_DEFAULT = os.getenv("YHLZ_TTS_RATE", "+8%")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def ask(wav: Path, system: str, prompt: str, max_tokens: int = 120) -> str:
    """Send the wav to llama-server; transport errors raise (caller reports)."""
    b64 = base64.b64encode(wav.read_bytes()).decode()
    body = {"model": "gemma-4-e4b", "stream": False, "temperature": 0.6,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
                    {"type": "text", "text": prompt},
                ]},
            ]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode())["choices"][0]["message"].get("content", "")


def _run_ask(wav: Path, system: str, prompt: str) -> tuple[bool, str]:
    try:
        return True, ask(wav, system, prompt)
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:200]}"


def _sentence_cut(text: str, limit: int = 200) -> str:
    """Cut at the last sentence-ending punctuation within limit (no mid-sentence
    truncation that would sound like a swallowed ending)."""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    for sep in ("。", "！", "？", "!", "?", "…"):
        idx = head.rfind(sep)
        if idx > limit * 0.3:
            return head[: idx + 1]
    return head


def _tts_edge(text: str, out_dir: Path, voice: str, rate: str) -> tuple[str, str]:
    """Edge-TTS (online) -> mp3 -> 24k mono wav. Returns (wav_path, "")."""
    import edge_tts  # noqa: PLC0415
    import imageio_ffmpeg  # noqa: PLC0415

    mp3 = out_dir / "reply.mp3"
    wav = out_dir / "reply.wav"

    async def _go() -> None:
        await edge_tts.Communicate(text, voice, rate=rate).save(str(mp3))

    asyncio.run(_go())
    if not (mp3.exists() and mp3.stat().st_size > 0):
        return "", "edge-tts produced no audio"
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([exe, "-y", "-i", str(mp3), "-ac", "1", "-ar", "24000", str(wav)],
                   capture_output=True, timeout=120)
    if not (wav.exists() and wav.stat().st_size > 44):
        return "", "ffmpeg produced no wav"
    return str(wav), ""


def _tts_sapi(text: str, out_dir: Path) -> tuple[str, str]:
    """Offline Windows SAPI fallback. Returns (wav_path, "")."""
    wav = out_dir / "reply_sapi.wav"
    b64 = base64.b64encode(text.encode("utf-8")).decode()
    ps = ("Add-Type -AssemblyName System.Speech; "
          f"$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}')); "
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{wav}'); $s.Speak($t); $s.Dispose()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, timeout=120)
    except Exception as exc:  # noqa: BLE001
        return "", f"SAPI {type(exc).__name__}: {str(exc)[:120]}"
    if wav.exists() and wav.stat().st_size > 44:
        return str(wav), ""
    return "", "SAPI produced no wav"


def _tts_wav(text: str, out_dir: Path, voice: str, rate: str) -> tuple[str, str, str]:
    """Synthesize to wav with fallback. Returns (wav_path, engine, error)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    edge_err = ""
    try:
        path, edge_err = _tts_edge(text, out_dir, voice, rate)
        if path:
            return path, "edge", ""
    except Exception as exc:  # noqa: BLE001
        edge_err = f"edge-tts {type(exc).__name__}: {str(exc)[:120]}"
    path, sapi_err = _tts_sapi(text, out_dir)
    if path:
        return path, "sapi", ""
    return "", "", f"edge: {edge_err or 'failed'}; sapi: {sapi_err or 'failed'}"


def _play_wav(path: Path) -> bool:
    """Play via winmm MCI (ledger 0156: sounddevice blocksize swallows the tail)."""
    import ctypes

    mci = ctypes.windll.winmm.mciSendStringW
    alias = f"vx{abs(hash(str(path))) % 10_000_000}"
    wav_path = str(path).replace("\\", "\\\\")
    if mci(f'open "{wav_path}" alias {alias}', None, 0, None) != 0:
        return False
    try:
        return mci(f"play {alias} wait", None, 0, None) == 0
    finally:
        mci(f"close {alias}", None, 0, None)


def _wav_duration_s(path: Path) -> float:
    try:
        import soundfile as sf  # noqa: PLC0415

        info = sf.info(str(path))
        return round(float(info.frames) / float(info.samplerate), 2) if info.samplerate else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def _default_out_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return _PROJECT_ROOT / "artifacts" / "voice_e2e" / stamp


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--raw", action="store_true", help="只转写（不走人设）")
    ap.add_argument("--speak", action="store_true", help="闭环：元亨文本交给 TTS 出声")
    ap.add_argument("--voice", default=TTS_VOICE_DEFAULT, help="edge-tts voice")
    ap.add_argument("--rate", default=TTS_RATE_DEFAULT, help="edge-tts rate, e.g. +8%%")
    ap.add_argument("--out-dir", type=Path, default=None, help="TTS 产物目录")
    ap.add_argument("--no-play", action="store_true", help="只生成 wav，不播放")
    a = ap.parse_args()
    wav = Path(a.wav)
    if not wav.exists():
        print("找不到 wav:", wav)
        return 2

    t0 = time.perf_counter()
    if a.raw:
        ok, text = _run_ask(wav, SYS_ASR, "转写这段音频，只输出内容。")
        if not ok:
            print("[llm] FAILED", text)
            return 2
        print("[转写]", text)
        print(f"[e2e] llm={int((time.perf_counter() - t0) * 1000)}ms")
        return 0

    ok, reply = _run_ask(wav, SYS_YH, "（听完直接回应）")
    llm_ms = int((time.perf_counter() - t0) * 1000)
    if not ok:
        print("[llm] FAILED", reply)
        return 2
    print("[元亨]", reply)
    if not a.speak:
        print(f"[e2e] llm={llm_ms}ms")
        return 0

    text = _sentence_cut(reply, 200)
    out_dir = a.out_dir or _default_out_dir()
    t1 = time.perf_counter()
    tts_path, engine, tts_err = _tts_wav(text, out_dir, a.voice, a.rate)
    tts_ms = int((time.perf_counter() - t1) * 1000)
    if not tts_path:
        print("[tts] FAILED", tts_err)
        return 3

    duration = _wav_duration_s(Path(tts_path))
    played = False
    if not a.no_play:
        played = _play_wav(Path(tts_path))
    total_ms = int((time.perf_counter() - t0) * 1000)
    summary = {
        "input_wav": str(wav),
        "reply_text": reply,
        "speak_text": text,
        "tts_engine": engine,
        "tts_wav": tts_path,
        "tts_duration_s": duration,
        "played": played,
        "llm_ms": llm_ms,
        "tts_ms": tts_ms,
        "total_ms": total_ms,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[tts] engine={engine} dur={duration}s wav={tts_path}")
    print(f"[e2e] llm={llm_ms}ms tts={tts_ms}ms total={total_ms}ms played={played}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
