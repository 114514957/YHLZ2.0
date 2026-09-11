"""Voice capture + ASR test entry (ledger 0218/0219).

Flow:
    start -> type 1 -> listen -> utterance ends 3 s after your voice stops ->
    print recognized text.

Capture chain (NEKO-style, ledger 0219):
    mic 48k -> RNNoise denoise -> AGC/limiter -> 16k -> local VAD segmentation
    -> ASR (sherpa-onnx streaming; SenseVoiceSmall when present).
Voiceprint gating is OPT-IN (--gate): we first verify whether RNNoise
cleaning alone makes background/TV/others stop triggering; if it does, the
voiceprint gate is dropped.

Commands: 1 listen | 2 close | 0 exit
"""
from __future__ import annotations

import sys
import time
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

VOICE_END_SILENCE_S = 1.5     # end utterance 1.5 s after last voice
MIN_USER_SPEECH_S = 0.3       # shortest accepted speech segment
MIN_LEAD_FRAMES = 3           # consecutive voiced frames to open a candidate
SEG_CLOSE_SILENCE_S = 0.7     # close a candidate segment after this silence
SEG_MAX_S = 3.0               # hard cap on one candidate segment
RNNOISE_SR = 48000

SENSEVOICE_DIR = _PROJECT_ROOT / "models" / "voice" / "asr" / "SenseVoiceSmall"


_SV = None  # SenseVoice singleton (load once)


def release_sv():
    """Free the SenseVoice cuda model so Qwen3-TTS etc. can load (8 GB card:
    ASR and TTS must NOT be resident at the same time)."""
    global _SV
    _SV = None
    import torch

    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _get_sv():
    global _SV
    if _SV is None:
        from funasr import AutoModel

        os.chdir(_PROJECT_ROOT)  # funasr/sentencepiece: relative path avoids
        # Windows non-ASCII absolute-path quirk seen during testing
        _SV = AutoModel(model=os.path.relpath(str(SENSEVOICE_DIR),
                                              _PROJECT_ROOT),
                        device="cuda", disable_update=True, disable_pbar=True,
                        disable_log=True)
    return _SV


def _build_asr(backend: str):
    if backend == "sensevoice" and SENSEVOICE_DIR.exists():
        return ("sensevoice", _get_sv())
    from backend.target_sherpa_asr import SherpaOnlineASRConfig, SherpaOnlineASRProvider

    return ("sherpa", SherpaOnlineASRProvider(SherpaOnlineASRConfig()))


def _transcribe(audio, backend_info, sid: str = "cap") -> str:
    import numpy as np

    kind, engine = backend_info
    if kind == "sensevoice":
        r = engine.generate(input=np.asarray(audio, dtype="float32"),
                            language="zh", use_itn=True, batch_size_s=60)
        text = str((r[0] or {}).get("text") or "") if r else ""
        return _clean(text)
    from backend.target_chain import CancellationSignal

    asr = engine
    sig = CancellationSignal()
    asr.open_stream(sid, 1, 16000, 1, sig)
    text = ""
    for i in range(0, len(audio), 1600):
        chunk = audio[i:i + 1600]
        if len(chunk) < 1600:
            chunk = np.concatenate([chunk, np.zeros(1600 - len(chunk),
                                                    dtype="float32")])
        for u in asr.push_audio(sid, chunk, 16000, sig):
            if u.text:
                text = u.text
    final = asr.finish_stream(sid, sig)
    # provider stays READY across turns: do NOT stop() here
    return _clean(str((final.text if final.text else text) or ""))


def _clean(text: str) -> str:
    """Drop ASR noise tags (SIL/MM/SPK/...), brackets, extra spaces."""
    import re

    t = str(text or "")
    t = re.sub(r"\b(SIL|MM|UM|UH|SPK|SPEAKER|NOISE|MUSIC|LAUGH)\b", " ", t,
               flags=re.IGNORECASE)
    t = re.sub(r"[\[<].*?[\]>]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"([，。！？,.!?])\1+", r"\1", t)
    return t.strip()


def _capture_loop(device: int, cap_gain: float, duration_s: float,
                  denoise: str, gate, verbose_gate: bool, debug: bool,
                  on_level=None, on_segment=None, on_chunk=None) -> dict:
    """Try rnnoise (48k) capture; on any audio-layer failure degrade to raw
    16k so the test entry always runs and prints what went wrong.
    on_level(level, is_speech) optional per-~500ms activity callback.
    on_segment(audio16k) called per accepted user segment (short pause cut).
    on_chunk(audio16k_frame) called per enhanced frame (for streaming ASR)."""
    if denoise == "rnnoise":
        try:
            return _capture_impl(device, cap_gain, duration_s, "rnnoise",
                                 gate, verbose_gate, debug, on_level,
                                 on_segment, on_chunk)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] rnnoise 采集失败({type(exc).__name__}: "
                  f"{str(exc)[:90]})，降级 raw 16k", flush=True)
    return _capture_impl(device, cap_gain, duration_s, "off",
                         gate, verbose_gate, debug, on_level, on_segment,
                         on_chunk)


def _capture_impl(device: int, cap_gain: float, duration_s: float,
                  denoise: str, gate, verbose_gate: bool, debug: bool,
                  on_level=None, on_segment=None, on_chunk=None) -> dict:
    import numpy as np
    import sounddevice as sd

    from backend.voice_frontend import VoiceFrontend

    fe = VoiceFrontend(sample_rate=16000)
    proc = None
    if denoise == "rnnoise":
        try:
            from backend.target_audio_processor import NEKOAudioProcessor

            proc = NEKOAudioProcessor()
            if not proc.available:
                print("[warn] rnnoise lib unavailable -> fallthrough", flush=True)
                proc = None
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] rnnoise init failed: {type(exc).__name__} -> "
                  f"off", flush=True)
            proc = None
    cap_sr = RNNOISE_SR if proc is not None else 16000
    blk = RNNOISE_SR // 10 if proc is not None else 1600  # 100 ms

    user_utt: list[np.ndarray] = []
    user_started = False
    user_silent_s = 0.0
    lead = 0
    seg: list[np.ndarray] = []
    seg_silent_s = 0.0
    seg_len_s = 0.0
    utt_len_s = 0.0
    t0 = time.time()
    last_dbg = 0.0
    with sd.InputStream(device=device, samplerate=cap_sr, channels=1,
                        dtype="float32", blocksize=blk,
                        latency="low") as inp:
        while time.time() - t0 < duration_s:
            data, _ = inp.read(blk)
            raw = np.asarray(data[:, 0] if data.ndim > 1 else data,
                             dtype="float32")
            if float(cap_gain) != 1.0:
                raw = np.clip(raw * float(cap_gain), -1.0, 1.0).astype("float32")
            if proc is not None:
                mono16, _prob = proc.process_mono(raw, RNNOISE_SR)
                mono = np.asarray(mono16, dtype="float32").reshape(-1)
            else:
                mono = raw
            if mono.size == 0:
                continue
            enhanced, is_speech = fe.process(mono)
            if on_chunk is not None:
                try:
                    on_chunk(enhanced)
                except Exception:
                    pass

            if debug and time.time() - last_dbg >= 1.0:
                last_dbg = time.time()
                print(f"[dbg] t={time.time()-t0:.1f}s "
                      f"nf={fe.noise_floor:.4f} gain={fe.gain:.1f} "
                      f"sp={int(is_speech)} seg={len(seg)} "
                      f"user={int(user_started)} usil={user_silent_s:.1f}",
                      flush=True)

            if is_speech:
                seg.append(enhanced.copy())
                seg_len_s += 0.1
                seg_silent_s = 0.0
                lead += 1
            else:
                seg_silent_s += 0.1
                if 0 < lead < MIN_LEAD_FRAMES:
                    lead = 0
                    seg = []
                    seg_len_s = 0.0

            if on_level is not None:
                _lvl_t = globals().get("_last_level_t", 0.0)
                if time.time() - _lvl_t >= 0.5:
                    globals()["_last_level_t"] = time.time()
                    try:
                        on_level(float(np.sqrt(np.mean(enhanced * enhanced))),
                                 bool(is_speech))
                    except Exception:
                        pass

            seg_ready = (len(seg) > 0 and
                         (seg_silent_s >= SEG_CLOSE_SILENCE_S or
                          seg_len_s >= SEG_MAX_S))
            if seg_ready:
                seg_audio = np.concatenate(seg)
                seg_s = float(seg_audio.size) / 16000.0
                seg = []
                seg_len_s = 0.0
                seg_silent_s = 0.0
                if seg_s >= MIN_USER_SPEECH_S:
                    accept = True
                    sim = 1.0
                    if gate is not None:
                        accept, sim = gate.verify(seg_audio)
                    if accept:
                        user_utt.append(seg_audio)
                        utt_len_s += seg_s
                        user_silent_s = 0.0
                        if not user_started:
                            user_started = True
                            print("…听到你", end="", flush=True)
                        if on_segment is not None:
                            try:
                                on_segment(seg_audio)
                            except Exception:
                                pass
                    elif verbose_gate:
                        print(f"(忽略非主人声 sim={sim:.2f})", flush=True)
                    else:
                        if user_started:
                            user_silent_s += seg_s
                else:
                    if user_started:
                        user_silent_s += seg_s

            if user_started and len(seg) == 0 and not is_speech:
                user_silent_s += 0.1
                if user_silent_s >= VOICE_END_SILENCE_S:
                    break
    if proc is not None:
        try:
            proc.reset()
        except Exception:
            pass
    if not user_utt or utt_len_s < 0.2:
        return {"started": False, "audio": None}
    return {"started": True, "audio": np.concatenate(user_utt)}


def main() -> int:
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=1)
    ap.add_argument("--cap-gain", type=float, default=1.0)
    ap.add_argument("--duration-s", type=float, default=300.0)
    ap.add_argument("--denoise", default="rnnoise", choices=["off", "rnnoise"])
    ap.add_argument("--gate", action="store_true",
                    help="enable voiceprint gating (opt-in; off by default)")
    ap.add_argument("--sim-thr", type=float, default=0.4)
    ap.add_argument("--verbose-gate", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--asr", default="auto",
                    choices=["auto", "sherpa", "sensevoice"])
    ap.add_argument("--tts", action="store_true")
    ap.add_argument("--tts-speaker", default="Vivian")
    a = ap.parse_args()

    backend = a.asr
    if backend == "auto":
        backend = "sensevoice" if SENSEVOICE_DIR.exists() else "sherpa"
    asr_info = _build_asr(backend)
    print(f"加载 ASR（{asr_info[0]}）…", flush=True)
    if asr_info[0] == "sherpa":
        asr_info[1].start()
    gate = None
    if a.gate:
        from backend.voiceprint_gate import VoiceprintGate

        print("加载声纹模型…", flush=True)
        gate = VoiceprintGate(threshold=a.sim_thr, verbose=a.verbose_gate)
        gate._ensure()
    mode = f"{a.denoise}降噪" + ("+声纹门" if gate else "")
    print(f"就绪（{mode}）。输入 1 聆听，2 关闭，0 退出。", flush=True)

    tts_model = None
    if a.tts:
        import torch
        from faster_qwen3_tts import FasterQwen3TTS

        print("加载 TTS…", flush=True)
        tts_model = FasterQwen3TTS.from_pretrained(
            str(_PROJECT_ROOT / "models" / "qwen3-tts" /
                "Qwen3-TTS-12Hz-1.7B-CustomVoice"),
            device="cuda", dtype=torch.bfloat16)

    while True:
        try:
            line = input("cmd> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line in ("2",):
            print("已关闭。", flush=True)
            break
        if line in ("0", "exit", "quit", ""):
            break
        if line != "1":
            continue
        print("聆听中…（短停顿即分段识别；停 3 秒结束）", flush=True)
        parts = []
        seg_no = 0

        def seg_cb(audio):
            nonlocal seg_no
            seg_no += 1
            try:
                t = _transcribe(audio, asr_info,
                                sid=f"seg{int(time.time() * 1000)}{seg_no}")
                if t:
                    parts.append(t)
                    print("\n[段已识别] " + t, flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"(段识别错误 {type(exc).__name__}: {str(exc)[:80]})",
                      flush=True)

        r = _capture_loop(a.device, a.cap_gain, a.duration_s, a.denoise,
                          gate, a.verbose_gate, a.debug, on_segment=seg_cb)
        if not r.get("started"):
            print("\n[未捕捉到语音]", flush=True)
            continue
        text = "".join(parts)
        if not text and r.get("audio") is not None:
            try:
                text = _transcribe(r["audio"], asr_info,
                                   sid=f"cap{int(time.time() * 1000)}")
            except Exception:
                text = ""
        print("\n========================")
        print(f"[识别结果] {text or '(空)'}")
        print("========================", flush=True)
        if tts_model is not None and text:
            import numpy as np
            import soundfile as sf

            wavs, sr = tts_model.generate_custom_voice(
                text=text, language="Chinese", speaker=a.tts_speaker,
                instruct="自然地读出来。")
            samples = np.asarray(wavs[0], dtype="float32")
            out = _PROJECT_ROOT / "cache" / "tts_test" / "heard.wav"
            out.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(out), samples, int(sr))
            import sounddevice as sd

            sd.play(samples, int(sr))
            sd.wait()
    try:
        asr_info[1].stop("done")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
