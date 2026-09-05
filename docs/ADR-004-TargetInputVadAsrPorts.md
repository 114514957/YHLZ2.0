# ADR-004: Target Input, VAD, and ASR Port Boundaries

## Status

Accepted for the isolated target voice chain. It does not authorize production-entry replacement or a C/full-duplex claim.

## Context

The target output path now has a process-isolated Qwen Provider and an observable playback boundary. The input side still has only generic media/segment/ASR bridge scaffolding. The legacy VAD and ASR modules contain global state, compatibility paths, and network-oriented behavior, so connecting them would recreate the coupling this refactor is meant to remove.

The selected Realtek input can be opened at 16 kHz, one channel, float32. That is a device-format prerequisite only. It does not prove microphone quality, VAD quality, ASR, echo control, B, or C.

## Decision

1. `SoundDeviceInputSource` captures an explicitly selected one-channel float32 stream. The logical VAD/ASR format remains 16 kHz. When a verified Windows endpoint only opens at native 48 kHz, `TargetInputResampler` is the explicit stateful bridge from 48 kHz capture to 16 kHz processing; probe metadata reports maximum/default channels and rates, not the selected capture format.
2. `TargetVADProvider` is the only planned real VAD implementation for the target chain. It runs Silero VAD locally through CPU ONNX Runtime, owns its LSTM/context state, has bounded input, and exposes `start`, `detect_speech`, `reset_stream`, `stop`, `wait_stopped`, and redacted `health`.
3. The Silero model is a separate ignored binary under `models/voice/vad`; its source, MIT license, version, SHA-256, and tensor contract live in a tracked manifest under `assets/voice/vad`. Runtime verifies an existing local binary and never downloads dynamically.
4. `ASRProviderPort` will remain separate from `ASRBridge`. The bridge owns segment ownership, cancellation and routing to the wake gate; the provider owns only transcribing one bounded segment plus cooperative `interrupt` and `wait_stopped` evidence. No model means `unavailable`, never a Mock transcript or network fallback.
5. A VAD runtime failure is an input-core fault. It is relayed through the existing media/runtime event path, drops the affected frame, and prevents a successful C claim. No repair action may modify data, `memory`, audio caches, or the legacy engines.

## Consequences

VAD can be validated independently on CPU without consuming TTS GPU capacity. A real VAD/short microphone proof can establish only an input-side B prerequisite. ASR model selection remains deliberately deferred until a local model, resource budget, language quality and cancellation behavior can be measured under the same port contract.

This adds one small asset manifest, one bounded resampling boundary and provider contracts, but avoids permanently coupling model APIs, capture format assumptions, device selection, and turn ownership.
