"""Voice full-chain latency profile (ledger 0434, KB kb_82fcbd0ddc85).

Compares the two local voice paths on the same clip:
  A audio-direct : wav -> LLM(input_audio) -> answer
  B ASR chain    : wav -> sherpa ASR -> LLM(text) -> answer
plus the shared TTS stage, and first-token latency (TTFT) for both paths.

Usage: python tools/voice_latency_bench.py [--wav PATH] [--runs 3]
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

URL = "http://127.0.0.1:8081/v1/chat/completions"
SYS_VOICE = ("你是元亨——老爹的伙伴，活泼、傲娇、话短；像朋友说话，禁止助手腔。"
             "老爹是语音说的：只输出你要对他说的话本身，≤2句；"
             "禁止复述、念稿、助手腔，禁止输出思考/分析/状态/括号说明。")
TXT_VOICE = "（听完直接回应）"


def _post(body: dict, timeout: float = 240) -> tuple[dict, float]:
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    return out, (time.perf_counter() - t0) * 1000


def _ttft(body: dict, timeout: float = 240) -> float:
    """First content delta time in ms (streaming)."""
    body = dict(body, stream=True)
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = (json.loads(data)["choices"][0].get("delta") or {})
            except Exception:  # noqa: BLE001
                continue
            if delta.get("content"):
                return (time.perf_counter() - t0) * 1000
    return (time.perf_counter() - t0) * 1000


def _sherpa_once(wav: Path) -> tuple[float, str]:
    """One streaming ASR pass; returns (ms, text). Provider load excluded."""
    import soundfile as sf

    from backend.streaming_asr_bridge import ASRStreamUpdateKind
    from backend.target_chain import CancellationSignal
    from backend.target_sherpa_asr import (
        SherpaOnlineASRConfig, SherpaOnlineASRProvider,
    )

    audio, sr = sf.read(str(wav), dtype="float32")
    if int(sr) != 16_000:
        raise RuntimeError(f"need 16k wav, got {sr}")
    provider = _sherpa_once._provider  # type: ignore[attr-defined]
    sig = CancellationSignal()
    provider.open_stream("bench", 1, 16_000, 1, sig)
    t0 = time.perf_counter()
    acc = ""
    for i in range(0, len(audio) - 1600 + 1, 1600):
        for upd in provider.push_audio("bench", audio[i:i + 1600], 16_000, sig):
            if upd.text and len(upd.text) > len(acc):
                acc = upd.text
    final = provider.finish_stream("bench", sig)
    if final.kind is ASRStreamUpdateKind.FINAL and final.text:
        acc = final.text
    return (time.perf_counter() - t0) * 1000, acc


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wav", default=str(_ROOT / "cache" / "voice_clips" / "ab_tired.wav"))
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    wav = Path(a.wav)
    if not wav.exists():
        print("missing wav:", wav)
        return 2

    # warm up + load sherpa once (load time reported separately)
    from backend.target_sherpa_asr import (
        SherpaOnlineASRConfig, SherpaOnlineASRProvider,
    )

    t0 = time.perf_counter()
    provider = SherpaOnlineASRProvider(SherpaOnlineASRConfig())
    provider.start()
    load_ms = (time.perf_counter() - t0) * 1000
    _sherpa_once._provider = provider  # type: ignore[attr-defined]

    b64 = base64.b64encode(wav.read_bytes()).decode()
    audio_msg = [
        {"role": "system", "content": SYS_VOICE},
        {"role": "user", "content": [
            {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
            {"type": "text", "text": TXT_VOICE}]},
    ]
    audio_body = {"model": "gemma-4-e4b", "temperature": 0.2, "max_tokens": 120,
                  "messages": audio_msg}

    asr_ms = []
    llm_audio_ms = []
    ttft_audio = []
    llm_text_ms = []
    ttft_text = []
    transcript = ""
    for i in range(a.runs):
        ms, transcript = _sherpa_once(wav)
        asr_ms.append(ms)
        text_body = {"model": "gemma-4-e4b", "temperature": 0.2, "max_tokens": 120,
                     "messages": [{"role": "system", "content": SYS_VOICE},
                                  {"role": "user", "content": transcript}]}
        _, ms = _post(text_body)
        llm_text_ms.append(ms)
        ttft_text.append(_ttft(text_body))
        _, ms = _post(audio_body)
        llm_audio_ms.append(ms)
        ttft_audio.append(_ttft(audio_body))
        print(f"run {i + 1}/{a.runs}: asr={asr_ms[-1]:.0f}ms "
              f"llm_text={llm_text_ms[-1]:.0f}ms llm_audio={llm_audio_ms[-1]:.0f}ms",
              flush=True)

    # shared TTS stage
    from tools.voice_dialog_probe import _tts_edge_wav

    t0 = time.perf_counter()
    tts_path, err = _tts_edge_wav("今晚吃啥都行，你定。", _ROOT / "cache" / "voice_clips")
    tts_ms = (time.perf_counter() - t0) * 1000

    avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
    print("\n=== voice latency profile (avg of %d, same clip) ===" % a.runs)
    print(f"sherpa load (once)      : {load_ms:.0f} ms")
    print(f"B  ASR (sherpa, local)  : {avg(asr_ms):.0f} ms   ttft n/a")
    print(f"B  LLM text             : {avg(llm_text_ms):.0f} ms   ttft {avg(ttft_text):.0f} ms")
    print(f"A  LLM audio-direct     : {avg(llm_audio_ms):.0f} ms   ttft {avg(ttft_audio):.0f} ms")
    print(f"   TTS (edge, shared)   : {tts_ms:.0f} ms -> {tts_path or err}")
    print(f"B total(crit) = ASR+LLM_text+TTS : "
          f"{avg(asr_ms) + avg(llm_text_ms) + tts_ms:.0f} ms")
    print(f"A total(crit) = LLM_audio+TTS    : "
          f"{avg(llm_audio_ms) + tts_ms:.0f} ms")
    print(f"transcript: {transcript!r}")
    provider.stop("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
