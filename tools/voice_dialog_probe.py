"""Voice dialog probe assembly (D-step, ledger 0152): mic -> ASR -> session
(orchestrator) -> TTS speaker out.  Real-machine self test; capture path
mirrors target_echo_chain_probe (pure synchronous, no asyncio audio mixing).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


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


def voice_dialog_once(
    *,
    tts_device: Optional[int] = None,
    capture_rate: int = 16_000,
    duration_s: float = 12.0,
    print_text: bool = False,
    cap_gain: float = 6.0,
) -> dict:
    """Run one voice turn: listen until speech+silence, transcribe, answer via
    the ConversationSession (real LLM), speak the answer on the speaker."""
    import numpy as np
    import sounddevice as sd

    from backend.target_funasr_asr import FunasrASRConfig, FunasrOnlineASRProvider
    from backend.target_memory import TargetMemoryService
    from backend.target_scheduler_tools import setup_scheduler_capabilities
    from backend.target_entry import ConversationSession
    from backend.target_vad import TargetVADProvider
    from backend.target_chain import CancellationSignal
    from backend.streaming_asr_bridge import ASRStreamUpdateKind

    model_dir = _PROJECT_ROOT / "models" / "voice" / "asr" / "paraformer-zh-streaming"
    vad = TargetVADProvider()
    asr = FunasrOnlineASRProvider(FunasrASRConfig(model_dir=model_dir))
    vad.start()
    asr.start()
    if print_text:
        print("[ready] 模型已加载，请现在说话…", flush=True)

    stream = sd.InputStream(device=1, samplerate=capture_rate, channels=1,
                            dtype="float32", blocksize=1600)
    stream.start()
    sig = CancellationSignal()
    asr.open_stream("dlg", 1, capture_rate, 1, sig)
    total = int(duration_s * 10)
    t0 = time.time()
    accum = ""
    last_grow = 0.0
    tail_silent = 0
    for _ in range(total):
        if time.time() - t0 > duration_s:
            break
        data, _ = stream.read(1600)
        mono = np.asarray(data[:, 0] if data.ndim > 1 else data, dtype="float32")
        if float(cap_gain) != 1.0:
            mono = np.clip(mono * float(cap_gain), -1.0, 1.0).astype("float32")
        speech = bool(vad.detect_speech(mono, capture_rate))
        for upd in asr.push_audio("dlg", mono, capture_rate, sig):
            if upd.text and len(upd.text) > len(accum):
                accum = upd.text
                last_grow = time.time()
        tail_silent = tail_silent + 1 if not speech else 0
        if accum and tail_silent >= 6 and time.time() - last_grow > 0.6:
            break  # hit-to-stop: content heard + 0.6 s silence = done
    final = asr.finish_stream("dlg", sig)
    text = accum or (final.text if final.kind is ASRStreamUpdateKind.FINAL else "")
    stream.stop()
    stream.close()
    vad.stop("done")
    asr.stop("done")

    result = {"heard": text, "answer": "", "status": "no-speech"}
    if not text.strip():
        return result
    import asyncio

    def _run() -> dict:
        session = ConversationSession(
            memory=TargetMemoryService(),
            registry=setup_scheduler_capabilities(),
        )
        info = asyncio.run(session.run_turn(text))
        return info

    info = _run()
    result.update(
        {
            "answer": info["answer"],
            "tools": [u["name"] for u in info["tool_uses"]],
            "status": "answered",
        }
    )
    if print_text:
        print("[heard]", text)
        print("[answer]", info["answer"])
    play_text = _sentence_cut(info["answer"], 200)
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
    result["tts_exit"] = tts.returncode
    result["tts_device"] = tts_device
    return result


def main() -> int:
    import json

    r = voice_dialog_once(print_text=True)
    print(json.dumps(r, ensure_ascii=False)[:600])
    return 0 if r["status"] == "answered" else 1


if __name__ == "__main__":
    raise SystemExit(main())
