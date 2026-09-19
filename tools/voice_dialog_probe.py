"""Voice dialog probe assembly (D-step, ledger 0152): mic -> ASR -> session
(orchestrator) -> TTS speaker out.  Real-machine self test; capture path
mirrors target_echo_chain_probe (pure synchronous, no asyncio audio mixing).

ledger 0406/0408: ``engine="audio"`` bypasses ASR — the captured 16k mono
segment is sent to the model as ``input_audio`` (audio-direct); sherpa/funasr
stay as fallback engines.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools.voice_dsp import StreamResampler, segment_dsp  # noqa: E402

_CLIPS_DIR = _PROJECT_ROOT / "cache" / "voice_clips"


def _default_input_device() -> int:
    """First openable input device (endpoint indices shift when Windows audio
    settings change; PortAudio's default input may be -1)."""
    import sounddevice as sd

    try:
        d = int(sd.default.device[0])
        if d >= 0 and sd.query_devices(d)["max_input_channels"] > 0:
            return d
    except Exception:
        pass
    for i, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] > 0:
            return i
    raise RuntimeError("no input device available")


def _segment_gate(block_rms: float, vad_speech: bool, noise_floor: float,
                  *, noise_ratio: float = 3.0,
                  abs_min_rms: float = 0.004) -> bool:
    """One-block speech decision for mic segmentation (ledger 0417).

    Silero VAD is the primary gate; the energy gate relative to the observed
    noise floor rejects background media that Silero may score as speech.
    Pure function so the tuning logic is unit-testable.
    """
    gate = max(float(abs_min_rms), float(noise_floor) * float(noise_ratio))
    return bool(vad_speech) and float(block_rms) > gate


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


_REASONING_MARKERS = (
    "（思考模式", "(思考模式", "思考模式启动", "分析用户意图", "**分析",
    "**思考", "思考过程", "**回应策略", "**最终选择", "**结论", "<analysis>",
)


def _spoken_text(answer: str, limit: int = 200) -> str:
    """What the TTS should actually say (ledger 0422): strip project markers,
    cut any leaked reasoning trace, collapse whitespace, keep it short."""
    import re

    t = re.sub(r"\[\[.*?\]\]", "", str(answer or ""), flags=re.S)
    cut = len(t)
    for marker in _REASONING_MARKERS:
        i = t.find(marker)
        if i >= 0:
            cut = min(cut, i)
    t = re.sub(r"\s+", " ", t[:cut]).strip()
    return _sentence_cut(t, limit)


def _split_sentences(text: str, max_parts: int = 3, min_len: int = 6) -> list[str]:
    """Split spoken text into <=max_parts pieces at sentence ends (ledger 0434).

    Lets synthesis/playback start on the first sentence while later sentences
    are still being synthesized — Edge-TTS is the dominant, network-bound stage.
    """
    import re

    t = str(text or "").strip()
    if not t:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[。！？!?…])", t) if p.strip()]
    if len(parts) <= 1:
        return [t]
    out: list[str] = []
    buf = ""
    for p in parts:
        buf += p
        if len(buf) >= int(min_len):
            out.append(buf)
            buf = ""
    if buf:
        if len(out) < int(max_parts):
            out.append(buf)
        elif out:
            out[-1] += buf
    if len(out) > int(max_parts):
        out = out[: int(max_parts) - 1] + ["".join(out[int(max_parts) - 1:])]
    return out


def _write_segment_wav(path: Path, frames: list, samplerate: int) -> bool:
    """float32 frames -> 16k mono PCM16 wav for llama.cpp ``input_audio``."""
    import numpy as np
    import soundfile as sf

    if not frames:
        return False
    data = np.concatenate(frames).astype("float32")
    if data.size < int(0.2 * samplerate):
        return False
    np.clip(data, -1.0, 1.0, out=data)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), data, int(samplerate), subtype="PCM_16")
    except Exception:
        return False
    return True


def _condition_tts_wav(path: Path) -> None:
    """CX-O-style TTS conditioning (ledger 0421): trim trailing silence and
    peak-normalize to 0.85 with a hard 0.98 ceiling (never clip).

    This is the adapted half of the CX-O finding: their 45x fixed gain is for
    tiny streaming chunks and blows up a full utterance, but peak normalization
    + tail trim gives consistent loudness for free.
    """
    try:
        import numpy as np
        import soundfile as sf

        x, sr = sf.read(str(path), dtype="float32")
        if x.ndim > 1:
            x = x.mean(axis=1)
        if x.size == 0:
            return
        peak = float(np.max(np.abs(x)))
        if peak >= 0.0001:
            block = max(1, int(int(sr) * 0.04))
            thresh = peak * 0.00316
            last = len(x)
            while last > block and float(np.max(np.abs(x[last - block:last]))) < thresh:
                last -= block
            last = max(last, int(int(sr) * 0.05))
            x = x[:last] * (0.85 / peak)
        x = np.clip(x, -0.98, 0.98)
        sf.write(str(path), x, int(sr), subtype="PCM_16")
    except Exception:
        pass


def _tts_edge_wav(text: str, out_dir: Path) -> tuple[str, str]:
    """Edge-TTS (online) -> 24k mono wav; Windows SAPI fallback (ledger 0409).

    Zero VRAM — the live chain cannot run Qwen3-TTS next to llama-server on an
    8 GB card.  Returns ``(wav_path, error)``."""
    import asyncio
    import base64

    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / "reply.wav"
    err = ""
    try:
        import edge_tts
        import imageio_ffmpeg

        mp3 = out_dir / "reply.mp3"
        voice = os.getenv("YHLZ_TTS_VOICE", "zh-CN-XiaoyiNeural")
        rate = os.getenv("YHLZ_TTS_RATE", "+8%")

        async def _go() -> None:
            await edge_tts.Communicate(text, voice, rate=rate).save(str(mp3))

        asyncio.run(_go())
        if mp3.exists() and mp3.stat().st_size > 0:
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run([exe, "-y", "-i", str(mp3), "-ac", "1", "-ar",
                            "24000", str(wav)],
                           capture_output=True, timeout=120)
            if wav.exists() and wav.stat().st_size > 44:
                _condition_tts_wav(wav)
                return str(wav), ""
        err = "edge produced no audio"
    except Exception as exc:  # noqa: BLE001
        err = f"edge {type(exc).__name__}: {str(exc)[:80]}"
    b64 = base64.b64encode(text.encode("utf-8")).decode()
    ps = ("Add-Type -AssemblyName System.Speech; "
          f"$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}')); "
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{wav}'); $s.Speak($t); $s.Dispose()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", ps], capture_output=True, timeout=120)
    except Exception:  # noqa: BLE001
        return "", err or "tts failed"
    if wav.exists() and wav.stat().st_size > 44:
        _condition_tts_wav(wav)
        return str(wav), ""
    return "", err or "tts failed"


# ---------------------------------------------------------------- local TTS
_LOCAL_TTS_DIR = _PROJECT_ROOT / "models" / "tts" / "piper-zh-huayan"
_LOCAL_TTS = None
_LOCAL_TTS_LOCK = None


def _ensure_espeak_ascii() -> str:
    """espeak-ng rejects non-ASCII data dirs ('Illegal byte sequence'); copy
    the bundled data to an ASCII temp path once (ledger 0435)."""
    import shutil
    import tempfile

    src = _LOCAL_TTS_DIR / "espeak-ng-data"
    if not src.exists():
        return ""
    dst = Path(tempfile.gettempdir()) / "yhlz_espeak"
    if not (dst / "phontab").exists():
        try:
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        except Exception:  # noqa: BLE001
            return ""
    return str(dst)


def _tts_local_wav(text: str, out_dir: Path) -> tuple[str, str]:
    """Local sherpa-onnx VITS/Piper synthesis: CPU, zero VRAM, ~0.8 s/sentence.

    Default engine (ledger 0435): Edge measured 3.5-8.6 s network-bound while
    this is ~0.8 s offline with intelligible output.
    """
    import threading

    global _LOCAL_TTS, _LOCAL_TTS_LOCK
    try:
        import numpy as np
        import sherpa_onnx
        import soundfile as sf

        if not _LOCAL_TTS_DIR.exists():
            return "", "local tts model missing"
        if _LOCAL_TTS_LOCK is None:
            _LOCAL_TTS_LOCK = threading.Lock()
        espeak = _ensure_espeak_ascii()
        if espeak:
            os.environ["ESPEAK_DATA_PATH"] = espeak
        with _LOCAL_TTS_LOCK:
            if _LOCAL_TTS is None:
                onnx = next(_LOCAL_TTS_DIR.glob("*.onnx"), None)
                tokens = _LOCAL_TTS_DIR / "tokens.txt"
                if onnx is None or not tokens.exists():
                    return "", "local tts model incomplete"
                cfg = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                            model=str(onnx), tokens=str(tokens),
                            data_dir=espeak),
                        num_threads=2,
                    ),
                    max_num_sentences=1,
                )
                _LOCAL_TTS = sherpa_onnx.OfflineTts(cfg)
            audio = _LOCAL_TTS.generate(str(text), sid=0, speed=1.0)
        out_dir.mkdir(parents=True, exist_ok=True)
        wav = out_dir / "reply.wav"
        sf.write(str(wav), np.asarray(audio.samples, dtype="float32"),
                 int(audio.sample_rate), subtype="PCM_16")
        _condition_tts_wav(wav)
        return str(wav), ""
    except Exception as exc:  # noqa: BLE001
        return "", f"local tts {type(exc).__name__}: {str(exc)[:120]}"


def _tts_engine_wav(text: str, out_dir: Path, engine: str) -> tuple[str, str, str]:
    """Dispatch with a local -> edge (-> SAPI) fallback chain."""
    eng = str(engine or "local").lower()
    if eng == "local":
        wav, _err = _tts_local_wav(text, out_dir)
        if wav:
            return wav, "", "local"
        eng = "edge"
    if eng == "edge":
        wav, err = _tts_edge_wav(text, out_dir)
        if wav:
            return wav, "", "edge"
        return "", err, "edge"
    return "", f"unknown tts engine: {engine}", eng


def _play_wav(path: Path) -> bool:
    """Play via winmm MCI (ledger 0156: sounddevice swallows the tail)."""
    import ctypes

    mci = ctypes.windll.winmm.mciSendStringW
    alias = f"vd{abs(hash(str(path))) % 10_000_000}"
    wav_path = str(path).replace("\\", "\\\\")
    if mci(f'open "{wav_path}" alias {alias}', None, 0, None) != 0:
        return False
    try:
        return mci(f"play {alias} wait", None, 0, None) == 0
    finally:
        mci(f"close {alias}", None, 0, None)


def voice_dialog_once(
    *,
    tts_device: int | None = None,
    capture_rate: int = 16_000,
    duration_s: float = 12.0,
    print_text: bool = False,
    cap_gain: float = 6.0,
    engine: str = "sherpa",
    tts_engine: str = "local",
    device: int | None = None,
    min_speech_blocks: int = 3,
    noise_ratio: float = 3.0,
    abs_min_rms: float = 0.004,
    max_clip_s: float = 20.0,
    segment_dsp_mode: str = "agc+lim",
    no_tts: bool = False,
) -> dict:
    """Run one voice turn: listen until speech+silence, answer via the
    ConversationSession (real LLM), speak the answer on the speaker.

    engine: 'sherpa' (default, ~2 s load, streaming zipformer), 'funasr'
    (paraformer, ~70 s load — keep as fallback) or 'audio' (audio-direct:
    no ASR — the segment goes straight to the model as input_audio)."""
    import numpy as np
    import sounddevice as sd

    from backend.target_chain import CancellationSignal
    from backend.target_entry import ConversationSession
    from backend.target_memory import TargetMemoryService
    from backend.target_scheduler_tools import setup_scheduler_capabilities
    from backend.target_vad import TargetVADProvider
    from backend.voice_frontend import VoiceFrontend

    audio_mode = str(engine).lower() == "audio"
    asr = None
    if not audio_mode:
        if str(engine).lower() in ("funasr", "paraformer"):
            from backend.target_funasr_asr import FunasrASRConfig, FunasrOnlineASRProvider

            model_dir = _PROJECT_ROOT / "models" / "voice" / "asr" / "paraformer-zh-streaming"
            asr = FunasrOnlineASRProvider(FunasrASRConfig(model_dir=model_dir))
        else:
            from backend.target_sherpa_asr import SherpaOnlineASRConfig, SherpaOnlineASRProvider

            asr = SherpaOnlineASRProvider(SherpaOnlineASRConfig())

    vad = TargetVADProvider()
    vad.start()
    if asr is not None:
        asr.start()
    if print_text:
        print("[ready] 模型已加载，请现在说话…", flush=True)

    dev = int(device) if device is not None else _default_input_device()
    cap_rate = int(capture_rate)
    try:
        sd.check_input_settings(device=dev, samplerate=cap_rate, channels=1)
    except Exception:
        cap_rate = int(sd.query_devices(dev)["default_samplerate"])
    block = max(160, int(cap_rate * 0.1))  # ~100 ms blocks
    resampler = StreamResampler(cap_rate, 16_000)  # NEKO-style soxr HQ stream
    stream = sd.InputStream(device=dev, samplerate=cap_rate, channels=1,
                            dtype="float32", blocksize=block, latency="low")
    stream.start()
    sig = CancellationSignal()
    if asr is not None:
        asr.open_stream("dlg", 1, 16_000, 1, sig)
    frontend = VoiceFrontend(sample_rate=16_000)
    total = int(duration_s * 10)
    t0 = time.time()
    accum = ""
    last_grow = 0.0
    tail_silent = 0
    speaking = False
    frames: list = []
    pre_roll: list = []
    noise_floor = 0.0
    start_streak = 0
    voiced_blocks = 0
    for _ in range(total):
        if time.time() - t0 > duration_s:
            break
        data, _ = stream.read(block)
        mono = resampler.process(
            np.asarray(data[:, 0] if data.ndim > 1 else data, dtype="float32"))
        enhanced, is_speech = frontend.process(mono)
        if float(cap_gain) != 1.0:
            # legacy override: manual gain still honoured as an extra boost
            enhanced = np.clip(enhanced * float(cap_gain), -1.0, 1.0).astype("float32")
        vad_speech = bool(vad.detect_speech(enhanced, 16_000))
        if audio_mode:
            # ledger 0417 tuning: Silero AND noise-floor energy gate, plus a
            # minimum consecutive-speech streak, so background media or room
            # noise cannot open a segment on its own.
            rms = float(np.sqrt(np.mean(np.square(enhanced))) + 1e-9)
            gated = _segment_gate(rms, vad_speech, noise_floor,
                                  noise_ratio=noise_ratio,
                                  abs_min_rms=abs_min_rms)
            if not speaking:
                if not gated:
                    # slow-tracking floor = quietest non-speech block seen
                    noise_floor = rms if noise_floor <= 0.0 else min(rms, noise_floor)
                start_streak = start_streak + 1 if gated else 0
                if start_streak >= int(min_speech_blocks):
                    speaking = True
                    voiced_blocks = 0
                    frames.extend(pre_roll)  # ~0.8 s pre-roll for the onset
                    pre_roll = []
            if speaking:
                if gated:
                    voiced_blocks += 1
                frames.append(np.array(enhanced, dtype="float32", copy=True))
            else:
                pre_roll.append(np.array(enhanced, dtype="float32", copy=True))
                if len(pre_roll) > 8:
                    pre_roll.pop(0)
            speech = gated
        else:
            speech = vad_speech or is_speech
            for upd in asr.push_audio("dlg", enhanced, 16_000, sig):
                if upd.text and len(upd.text) > len(accum):
                    accum = upd.text
                    last_grow = time.time()
        tail_silent = tail_silent + 1 if not speech else 0
        if audio_mode:
            if speaking and tail_silent >= 6:  # hit-to-stop: 0.6 s silence
                break
            if speaking and len(frames) >= int(max_clip_s * 10):
                break  # runaway guard
        elif accum and tail_silent >= 6 and time.time() - last_grow > 0.6:
            break
    if audio_mode and speaking:
        tail = resampler.flush()
        if tail.size:
            frames.append(tail.astype("float32"))
    text = ""
    if asr is not None:
        from backend.streaming_asr_bridge import ASRStreamUpdateKind

        final = asr.finish_stream("dlg", sig)
        text = accum or (final.text if final.kind is ASRStreamUpdateKind.FINAL else "")
    stream.stop()
    stream.close()
    vad.stop("done")
    if asr is not None:
        asr.stop("done")

    result: dict = {"heard": text, "answer": "", "status": "no-speech",
                    "engine": engine}
    clip = ""
    if audio_mode:
        if frames and str(segment_dsp_mode).lower() not in ("off", "none", ""):
            # ledger 0422: NEKO-derived AGC/Limiter on the saved segment only
            # (VAD/segmentation decisions stay untouched).
            data = np.concatenate(frames).astype("float32")
            data16 = (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16)
            data16 = segment_dsp(data16, str(segment_dsp_mode))
            frames = [data16.astype("float32") / 32768.0]
        clip_path = _CLIPS_DIR / ("seg_" + time.strftime("%Y%m%d_%H%M%S") + ".wav")
        if (not speaking or voiced_blocks < int(min_speech_blocks)
                or not _write_segment_wav(clip_path, frames, 16_000)):
            return result
        clip = str(clip_path)
        result["clip"] = clip
    elif not text.strip():
        return result

    session = ConversationSession(
        memory=TargetMemoryService(),
        registry=setup_scheduler_capabilities(),
    )
    import asyncio

    async def _turn() -> dict:
        info = await session.run_turn(text, audio=([clip] if audio_mode else None))
        task = getattr(session, "_voice_task", None)
        if task is not None:
            try:
                # keep the loop alive until the async transcript lands
                await asyncio.wait_for(asyncio.shield(task), timeout=20)
            except Exception:
                pass
        return info

    info = asyncio.run(_turn())
    result.update(
        {
            "answer": info["answer"],
            "tools": [u["name"] for u in info["tool_uses"]],
            "status": "answered",
        }
    )
    if print_text:
        if clip:
            print("[clip]", clip)
        print("[heard]", text or "（音频直入）")
        print("[answer]", info["answer"])
    if no_tts:
        result["tts_exit"] = None
        return result
    play_text = _spoken_text(info["answer"], 200)
    if not play_text:
        result["tts_exit"] = None
        return result
    if str(tts_engine).lower() == "qwen":
        tts_cmd = [
            sys.executable, "-m", "backend.tts_speaker_probe",
            "--speakers", "Vivian", "--text", play_text,
        ]
        if tts_device is not None:
            tts_cmd += ["--device", str(tts_device)]
        tts = subprocess.Popen(
            tts_cmd,
            cwd=str(_PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        tts.wait(timeout=120)
        result["tts_engine"] = "qwen"
        result["tts_exit"] = tts.returncode
        result["tts_device"] = tts_device
        return result
    # ledger 0434: sentence-level pipeline — start playing the first sentence
    # while the rest are still being synthesized (TTS was the bottleneck).
    pieces = _split_sentences(play_text, max_parts=3)
    result["tts_parts"] = len(pieces)
    played = False
    wav_last = ""
    err = ""
    used = str(tts_engine).lower()
    t0 = time.perf_counter()
    for i, piece in enumerate(pieces):
        wav, e, eng = _tts_engine_wav(piece, _CLIPS_DIR / "tts_parts" / str(i),
                                      tts_engine)
        used = eng
        if not wav:
            err = e
            continue
        wav_last = wav
        if "tts_first_audio_ms" not in result:
            result["tts_first_audio_ms"] = int((time.perf_counter() - t0) * 1000)
        played = _play_wav(Path(wav)) or played
    result["tts_engine"] = used
    result["tts_wav"] = wav_last
    result["tts_played"] = played
    result["tts_exit"] = 0 if played else 1
    if err and not wav_last:
        result["tts_error"] = err
    return result


def main() -> int:
    import argparse
    import json

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="one voice dialog turn")
    ap.add_argument("--engine", default="sherpa",
                    choices=["sherpa", "funasr", "audio"])
    ap.add_argument("--tts", default="local", choices=["local", "edge", "qwen"],
                    help="local = CPU 零显存 ~0.8s（推荐，ledger 0435）")
    ap.add_argument("--cap-gain", type=float, default=1.0)
    ap.add_argument("--duration-s", type=float, default=12.0)
    ap.add_argument("--device", type=int, default=None,
                    help="输入设备索引（默认自动选第一个可用输入）")
    ap.add_argument("--segment-dsp", dest="segment_dsp", default="agc+lim",
                    choices=["off", "lim", "agc+lim"],
                    help="语音段保存前的 NEKO 式 AGC/限幅（ledger 0422）")
    ap.add_argument("--no-tts", action="store_true")
    a = ap.parse_args()
    r = voice_dialog_once(engine=a.engine, cap_gain=a.cap_gain,
                          duration_s=a.duration_s, print_text=True,
                          tts_engine=a.tts, device=a.device,
                          segment_dsp_mode=a.segment_dsp, no_tts=a.no_tts)
    print(json.dumps(r, ensure_ascii=False)[:600])
    return 0 if r["status"] == "answered" else 1


if __name__ == "__main__":
    raise SystemExit(main())
