"""Speaker audition probe for Qwen3-TTS CustomVoice (1.7B, instruct-capable).

Synthesizes the fixed default test text with an excited instruction for the
candidate speakers, saves WAV copies under ``artifacts/tts_probe/speaker_*``
and plays them sequentially for human choice.  This is an audition tool, not a
certification probe; it never writes business data or ``memory``.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np

from faster_qwen3_tts.model import FasterQwen3TTS

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

TEST_TEXT = "进步始于思想，元亨开拓未来"
NATURAL_INSTRUCT = "请用自然、平实、清晰的语调说这句话，语速适中。"
SPEAKERS = ["Vivian", "Serena", "Ono_Anna", "Sohee"]


def _default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _PROJECT_ROOT / "artifacts" / "tts_probe" / ("speaker_test_" + stamp)


def _write_wav(path: Path, samples: np.ndarray, sr: int) -> None:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), samples, sr)


def _play(path: Path, sr: int, gain: float = 1.0, device: Optional[int] = None) -> bool:
    import tempfile

    import soundfile as sf

    data, file_sr = sf.read(str(path), dtype="float32")
    if file_sr != sr:
        x = np.linspace(0, 1, int(data.size * sr / file_sr))
        data = np.interp(x, np.linspace(0, 1, data.size), data).astype("float32")
    if float(gain) != 1.0:
        data = np.clip(data * float(gain), -1.0, 1.0).astype("float32")
    mono = data[:, 0] if data.ndim > 1 and data.shape[1] > 1 else data
    # Real-machine evidence (ledger 0156): sounddevice blocksize playback
    # swallows the audio tail on MME; the OS SoundPlayer is complete.
    if device is None:
        import ctypes

        tmp = path.with_name("__play_gain.wav")
        try:
            sf.write(str(tmp), mono, int(sr))
            mci = ctypes.windll.winmm.mciSendStringW
            alias = f"yhlz{abs(hash(str(tmp))) % 10_000_000}"
            wav_path = str(tmp).replace("\\", "\\\\")
            if mci(f'open "{wav_path}" alias {alias}', None, 0, None) != 0:
                return False
            try:
                if mci(f"play {alias} wait", None, 0, None) != 0:
                    return False
                return True
            finally:
                mci(f"close {alias}", None, 0, None)
        except Exception as exc:
            print(f"  system playback failed: {type(exc).__name__}: {exc}")
            return False
        finally:
            try:
                tmp.unlink()
            except Exception:
                pass
    import sounddevice as sd

    try:
        stream = sd.OutputStream(device=int(device), samplerate=int(sr),
                                 channels=1, dtype="float32")
        stream.start()
        stream.write(mono)
        sd.sleep(int(mono.size / int(sr) * 1000) + 300)  # let tail drain
        stream.stop()
        stream.close()
        return True
    except Exception as exc:
        print(f"  playback failed: {type(exc).__name__}: {exc}")
        return False


def run_probe(
    output_dir: Path,
    *,
    model_dir: Path,
    speakers: list[str],
    text: str = TEST_TEXT,
    instruct: str = NATURAL_INSTRUCT,
    language: str = "Chinese",
    play: bool = True,
    play_gain: float = 1.0,
    device: Optional[int] = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    summary: dict[str, Any] = {"probe": "tts_speaker_audition_v1", "status": "failed"}
    results = []
    try:
        import torch

        model = FasterQwen3TTS.from_pretrained(
            str(model_dir),
            device="cuda",
            dtype=torch.bfloat16,
        )
        summary["model_dir"] = str(model_dir)
        summary["speakers_requested"] = list(speakers)
        for speaker in speakers:
            t0 = time.perf_counter()
            wavs, sr = model.generate_custom_voice(
                text=text,
                language=language,
                speaker=speaker,
                instruct=instruct,
            )
            samples = np.asarray(wavs[0], dtype="float32")
            wav = output_dir / f"{speaker}.wav"
            _write_wav(wav, samples, int(sr))
            played = _play(wav, int(sr), play_gain, device) if play else False
            results.append(
                {
                    "speaker": speaker,
                    "audio_len_s": round(float(samples.size) / int(sr), 2),
                    "sample_rate": int(sr),
                    "wav": str(wav.relative_to(_PROJECT_ROOT)),
                    "played": bool(played),
                    "synthesize_ms": round((time.perf_counter() - t0) * 1000, 1),
                }
            )
        summary["results"] = results
        summary["status"] = "passed" if results else "failed"
    except Exception as exc:
        summary["error_code"] = "TTS-SPEAKER-PROBE-FAILED"
        summary["error_type"] = type(exc).__name__
        summary["detail"] = str(exc)[:200]
    finally:
        summary["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=_PROJECT_ROOT / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-1.7B-CustomVoice",
    )
    parser.add_argument("--speakers", nargs="+", default=SPEAKERS)
    parser.add_argument("--text", default=TEST_TEXT)
    parser.add_argument("--instruct", default=NATURAL_INSTRUCT)
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--no-play", action="store_true")
    parser.add_argument("--play-gain", type=float, default=1.0)
    parser.add_argument("--device", type=int, default=None,
                        help="output device index (default = system default)")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = run_probe(
        args.output_dir or _default_output_dir(),
        model_dir=args.model_dir,
        speakers=args.speakers,
        text=args.text,
        instruct=args.instruct,
        language=args.language,
        play=not args.no_play,
        play_gain=args.play_gain,
        device=args.device,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if not args.no_play and any(not r.get("played") for r in summary.get("results", [])):
        return 2
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
