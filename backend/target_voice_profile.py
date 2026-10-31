"""Local-only Target voice profiles; independent of the legacy workbench.

No explicit model/profile means the existing Edge Xiaoyi reference cloned by
Qwen Base. An explicit model-only override retains the old CustomVoice route.
Missing clone assets are errors, never a network or different-speaker fallback.
"""
from pathlib import Path
from typing import Any

from backend.tts_qwen_provider import QwenTTSConfig

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VOICE_PROFILE = "xiaoyi"


def build_target_qwen_config(
    *, voice_profile: str | None = None, model_dir: Path | str | None = None,
    root: Path = ROOT, **overrides: Any,
) -> QwenTTSConfig:
    profile = voice_profile or ("customvoice" if model_dir is not None else DEFAULT_VOICE_PROFILE)
    if profile == "customvoice":
        if model_dir is None:
            raise ValueError("customvoice requires an explicit local model_dir")
        return QwenTTSConfig(model_dir=model_dir, **overrides)
    if profile != "xiaoyi":
        raise ValueError(f"unsupported Target voice profile: {profile}")
    refs = Path(root) / "models/tts/refs/xiaoyi"
    wav = refs / "ref01.wav"
    transcript = refs / "ref01.txt"
    model = Path(model_dir) if model_dir is not None else Path(root) / "models/qwen3-tts/Qwen3-TTS-12Hz-0.6B-Base"
    for asset in (model, wav, transcript):
        if not asset.exists():
            raise FileNotFoundError(f"local Xiaoyi asset missing: {asset}")
    if not model.is_dir() or not wav.is_file() or not transcript.is_file():
        raise ValueError("invalid local Xiaoyi asset type")
    ref_text = transcript.read_text(encoding="utf-8-sig").strip()
    if not ref_text or not wav.stat().st_size:
        raise ValueError("local Xiaoyi reference audio/text must not be empty")
    if overrides.get("speaker", "Vivian") != "Vivian":
        raise ValueError("speaker override only applies to customvoice; Xiaoyi uses its local reference")
    return QwenTTSConfig(
        model_dir=model, voice_mode="clone", clone_voice_id="xiaoyi",
        ref_audio=wav, ref_text=ref_text, **overrides,
    )
