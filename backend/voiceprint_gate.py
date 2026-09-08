"""Voiceprint gate (ledger 0218): only the enrolled user's voice passes.

Solves "只收录我的声纹声音": every candidate speech segment is embedded by
cam++ (FunASR) and cosine-compared to the stored user vector; segments below
``threshold`` (other people, speaker/TV echo, noise) are dropped before they
ever reach ASR or trigger the capture/end logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

VOICEPRINT_FILE = _PROJECT_ROOT / "cache" / "voiceprint" / "user_embedding.npy"
CAMPPLUS_DIR = _PROJECT_ROOT / "models" / "voice" / "sv" / "campplus"


class VoiceprintGate:
    def __init__(
        self,
        *,
        embedding_path: Path = VOICEPRINT_FILE,
        model_dir: Path = CAMPPLUS_DIR,
        device: str = "auto",
        threshold: float = 0.5,
        verbose: bool = False,
    ) -> None:
        self.embedding_path = Path(embedding_path)
        self.model_dir = Path(model_dir)
        self.device = self._resolve_device(device)
        self.threshold = float(threshold)
        self.verbose = bool(verbose)
        self._model = None
        self._user_vec = None

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device in ("cuda", "gpu"):
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        return "cpu"

    def _ensure(self):
        if self._model is None:
            if not self.embedding_path.exists():
                raise FileNotFoundError(
                    f"voiceprint missing: {self.embedding_path} "
                    f"(run tools/voiceprint_enroll.py or enroll_file.py)")
            import numpy as np
            from funasr import AutoModel

            self._user_vec = np.load(str(self.embedding_path)).reshape(-1)
            self._user_vec = self._user_vec / (
                np.linalg.norm(self._user_vec) + 1e-9)
            self._model = AutoModel(
                model=str(self.model_dir), device=self.device,
                disable_update=True, disable_pbar=True, disable_log=True)
        return self._model

    def verify(self, audio) -> tuple[bool, float]:
        """Return (is_user, cosine_similarity) for one speech segment.

        Uses the BEST of several sliding windows (1.2 s) inside the segment so
        a noisy/quiet frame never drags the score down — this matters on the
        weak far-field mic where close-mic enrollment vectors sit in a
        different acoustic domain."""
        import numpy as np

        model = self._ensure()
        audio = np.asarray(audio, dtype="float32").reshape(-1)
        if audio.size < 6400:  # < 0.4 s: too short to judge
            return False, 0.0
        win = int(1.2 * 16000)      # 1.2 s window
        hop = int(0.7 * 16000)
        starts = list(range(0, audio.size - win + 1, hop)) or [0]
        best = -1.0
        for s in starts:
            seg = audio[s:s + win]
            if float(np.sqrt(np.mean(seg * seg))) < 0.004:
                continue  # near-silence window: skip (no identity info)
            r = model.generate(input=seg)
            try:
                e = np.asarray(r[0]["spk_embedding"],
                               dtype="float32").reshape(-1)
            except (KeyError, IndexError, TypeError):
                continue
            e = e / (np.linalg.norm(e) + 1e-9)
            best = max(best, float(np.dot(e, self._user_vec)))
        return best >= self.threshold, best


if __name__ == "__main__":
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.5)
    a = ap.parse_args()
    g = VoiceprintGate(threshold=a.threshold, verbose=True)
    print("gate ready; feed segments via verify()")
