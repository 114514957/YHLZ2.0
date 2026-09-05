"""Always-on wake-word spotting (ledger 0155/0156): sherpa-onnx KWS.

Open-vocabulary KWS (wenetspeech zipformer 3.3M zh).  Default wake keyword:
元亨 (boost 2.0 / threshold 0.4 in keywords file).  Streaming loop is plain
synchronous (PortAudio-safe, per ledger 0141 audio discipline).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
KWS_MODEL_DIR = (
    _PROJECT_ROOT / "models" / "voice" / "kws"
    / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
)
KEYWORDS_FILE = _PROJECT_ROOT / "models" / "voice" / "kws" / "kw_tokens.txt"


def _pick_onnx(directory: Path, kind: str) -> str:
    """Prefer int8 encoder/decoder/joiner when present."""
    cands = sorted(directory.glob(f"{kind}-*.int8.onnx")) or sorted(
        directory.glob(f"{kind}-*.onnx")
    )
    if not cands:
        raise FileNotFoundError(f"{kind} onnx missing in {directory}")
    return str(cands[0])


class WakeWordSpotter:
    """sherpa-onnx KWS wrapper; load lazily (first listen)."""

    def __init__(
        self,
        *,
        model_dir: Path = KWS_MODEL_DIR,
        keywords_file: Path = KEYWORDS_FILE,
        keywords_score: float = 2.0,
        keywords_threshold: float = 0.4,
        num_threads: int = 2,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.keywords_file = Path(keywords_file)
        self.keywords_score = float(keywords_score)
        self.keywords_threshold = float(keywords_threshold)
        self.num_threads = int(num_threads)
        self._spotter: Any = None

    def _ensure(self) -> Any:
        if self._spotter is None:
            import sherpa_onnx

            if not self.keywords_file.exists():
                raise FileNotFoundError(f"keywords file missing: {self.keywords_file}")
            self._spotter = sherpa_onnx.KeywordSpotter(
                tokens=str(self.model_dir / "tokens.txt"),
                encoder=_pick_onnx(self.model_dir, "encoder"),
                decoder=_pick_onnx(self.model_dir, "decoder"),
                joiner=_pick_onnx(self.model_dir, "joiner"),
                keywords_file=str(self.keywords_file),
                num_threads=self.num_threads,
                sample_rate=16000,
                feature_dim=80,
                keywords_score=self.keywords_score,
                keywords_threshold=self.keywords_threshold,
                provider="cpu",
            )
        return self._spotter

    def feed(self, samples: np.ndarray, stream: Any = None) -> str:
        """Offline feed (utterance + tail padding + input_finished).

        Matches the official API example (ledger 0157): decode inside the
        is_ready loop, get_result returns the keyword string.
        """
        import numpy as _np

        spotter = self._ensure()
        own = stream is None
        if own:
            stream = spotter.create_stream()
        audio = _np.asarray(samples, dtype="float32")
        tail = _np.zeros(int(0.66 * 16000), dtype="float32")
        stream.accept_waveform(16000, audio)
        stream.accept_waveform(16000, tail)
        stream.input_finished()
        keyword = ""
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
            r = spotter.get_result(stream)
            if r:
                keyword = str(r).strip()
                if own:
                    spotter.reset_stream(stream)
                break
        if own:
            spotter.reset_stream(stream)
        return keyword

    def listen_once(
        self,
        *,
        duration_s: float = 60.0,
        device: int = 1,
        on_keyword: Any = None,
        poll_s: float = 0.05,
    ) -> dict:
        """Capture 16k mic continuously; yield on wake keyword.

        on_keyword(keyword, elapsed_s) may be set; loop ends after duration_s
        or when on_keyword returns False.
        """
        import sounddevice as sd

        spotter = self._ensure()
        stream = spotter.create_stream()
        total = int(duration_s * 10)  # one 1600-sample frame = 0.1 s @16k
        t0 = time.time()
        wakes: list[dict] = []
        with sd.InputStream(device=int(device), samplerate=16000, channels=1,
                            dtype="float32", blocksize=1600) as inp:
            for _ in range(total):
                data, _ = inp.read(1600)
                mono = np.asarray(data[:, 0] if data.ndim > 1 else data,
                                  dtype="float32")
                stream.accept_waveform(16000, mono)
                while spotter.is_ready(stream):
                    spotter.decode_stream(stream)
                    kw = str(spotter.get_result(stream) or "").strip()
                    if kw:
                        rec = {"keyword": kw,
                               "elapsed_s": round(time.time() - t0, 2)}
                        wakes.append(rec)
                        keep = True
                        if on_keyword is not None:
                            try:
                                keep = on_keyword(kw, rec["elapsed_s"]) is not False
                            except Exception:
                                keep = True
                        spotter.reset_stream(stream)
                        if not keep:
                            return {"wakes": wakes,
                                    "duration_s": round(time.time() - t0, 2)}
        return {"wakes": wakes, "duration_s": round(time.time() - t0, 2)}
