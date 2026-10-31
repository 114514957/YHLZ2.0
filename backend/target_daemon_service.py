"""Opt-in Target graph owner on the daemon event loop."""
from __future__ import annotations

import asyncio
import os
from collections import deque
from pathlib import Path
from typing import Any

from backend.target_device_binding import TargetDeviceBinding, resolve_devices
from backend.target_workbench_adapter import TargetWorkbenchAdapter


class TargetDaemonService:
    def __init__(self, binding: TargetDeviceBinding, model_dir: Path | None = None, *,
                 voice_profile: str | None = None, sd: Any = None,
                 session_factory=None, voice_supervisor=None):
        self.binding = binding
        self.model_dir = Path(model_dir) if model_dir is not None else None
        self.voice_profile = voice_profile
        self.sd = sd
        self.composition = None
        self.adapter = None
        self.devices = None
        self.run_task = None
        self.monitor_task = None
        self.error_code = None
        self.native_capture = os.getenv("YHLZ_TARGET_NATIVE_CAPTURE", "0") == "1"
        self.session_factory = session_factory
        self.voice_supervisor = voice_supervisor
        self.recent_traces = deque(maxlen=20)
        self._shutdown_task = None

    async def start(self) -> None:
        if self.composition is not None:
            raise RuntimeError("TARGET-ALREADY-STARTED")
        import sounddevice as sounddevice
        from backend.llm_hybrid_compose import create_hybrid_reasoner
        from backend.media_adapter import SoundDeviceInputSource
        from backend.session_kernel import ProviderCapabilities
        from backend.target_composition import TargetVoiceComposition, TargetVoiceCompositionConfig
        from backend.target_playback import PlaybackConfig, SoundDevicePlaybackPort
        from backend.target_sherpa_asr import SherpaOnlineASRProvider
        from backend.target_vad import TargetVADProvider
        from backend.target_voice_profile import build_target_qwen_config

        if self.session_factory is None:
            raise RuntimeError("TARGET-VOICE-SESSION-REQUIRED")
        from backend.session_audio_reasoner import SessionAudioReasoner

        self.sd = self.sd or sounddevice
        devices = resolve_devices(self.sd, self.binding)
        composition = TargetVoiceComposition(
            TargetVoiceCompositionConfig(qwen=build_target_qwen_config(
                voice_profile=self.voice_profile, model_dir=self.model_dir),
                segmented_tts_enabled=True),
            reasoner=SessionAudioReasoner(
                self.session_factory, create_hybrid_reasoner(),
                tools_enabled=os.getenv("YHLZ_TARGET_VOICE_TOOLS", "0") == "1"),
            playback=SoundDevicePlaybackPort(
                PlaybackConfig(device=devices.output_index,
                               device_sample_rate=devices.output_sample_rate,
                               channels=devices.output_channels), sounddevice_module=self.sd),
        )
        self.composition = composition
        try:
            composition.create_runtime(
                asr=None if self.native_capture else SherpaOnlineASRProvider(),
                native_audio_submit=self.submit_audio if self.native_capture else None,
                source=SoundDeviceInputSource(
                    self.sd, blocksize=max(1, round(devices.input_sample_rate * .020))),
                vad=TargetVADProvider(),
                duplex_enabled=True,
            )
            devices.verify(self.sd)
            composition.start(devices.descriptor(), ProviderCapabilities(continuous_capture=True))
            self.devices = devices
            self.adapter = TargetWorkbenchAdapter(chain=composition.chain,
                                                   runtime=composition.runtime)
            self.run_task = asyncio.create_task(composition.run())
            self.monitor_task = asyncio.create_task(self._monitor())
        except BaseException:
            await self.shutdown()
            raise

    async def _monitor(self) -> None:
        try:
            while True:
                await asyncio.sleep(2)
                if self.run_task.done():
                    self.error_code = "TARGET-MEDIA-STOPPED"
                    break
                try:
                    self.devices.verify(self.sd)
                except Exception:
                    self.error_code = "TARGET-DEVICE-CHANGED"
                    break
        except asyncio.CancelledError:
            return
        await self.shutdown()

    async def submit_text(self, text: str):
        if self.error_code or self.adapter is None:
            raise RuntimeError(self.error_code or "TARGET-NOT-READY")
        self.devices.verify(self.sd)
        return await self.adapter.submit_text(text)

    async def submit_audio(self, audio, *, text: str = "", source: str = "daemon_audio"):
        """节点A: submit an audio turn through the same shared Target graph."""
        if self.error_code or self.adapter is None:
            raise RuntimeError(self.error_code or "TARGET-NOT-READY")
        self.devices.verify(self.sd)
        from backend import gpu_lock
        if not gpu_lock.chat_enter():
            raise RuntimeError("TARGET-GPU-BUSY")
        from backend.voice_turn_trace import VoiceTurnTrace, current_trace
        trace = VoiceTurnTrace(self.binding.route)
        if source == "microphone_native":
            trace.mark("vad_segment_submitted")
        token = current_trace.set(trace)
        if self.voice_supervisor is not None:
            self.voice_supervisor.enter_foreground()
        try:
            result = await self.adapter.submit_audio(audio, text=text, source=source)
            trace.finish(result.status, result.error_code)
            return result
        except asyncio.CancelledError:
            trace.mark("request_cancelled")
            trace.finish("cancelled")
            if trace.turn_id and self.composition is not None:
                result = await self.composition.chain.interrupt(
                    "audio_request_cancelled", expected_turn_id=trace.turn_id)
                if result is not None and (result.timed_out_tasks or result.failed_tasks):
                    self.error_code = "TARGET-STOP-UNCONFIRMED"
            raise
        except Exception as exc:
            trace.finish("failed", type(exc).__name__)
            raise
        finally:
            trace.mark("request_finished")
            current_trace.reset(token)
            self.recent_traces.append(trace.snapshot())
            try:
                await asyncio.to_thread(trace.save)
            except Exception:
                # Telemetry failure must not cause a second spoken answer.
                pass
            finally:
                if self.voice_supervisor is not None:
                    self.voice_supervisor.leave_foreground()
                gpu_lock.chat_exit()

    async def interrupt(self):
        if self.adapter is None:
            raise RuntimeError("TARGET-NOT-READY")
        return await self.adapter.interrupt()

    async def shutdown(self) -> None:
        # All callers observe the same cleanup completion, never a cleared
        # composition pointer while another task still owns live devices.
        if self._shutdown_task is None:
            caller = asyncio.current_task()
            self._shutdown_task = asyncio.create_task(self._shutdown(caller))
        await asyncio.shield(self._shutdown_task)

    async def _shutdown(self, caller) -> None:
        monitor, self.monitor_task = self.monitor_task, None
        if monitor is not None and monitor is not caller:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        self.adapter = None
        try:
            if self.composition is not None:
                await self.composition.shutdown("daemon_stop")
                self.composition = None
        except BaseException:
            self.error_code = "TARGET-CLEANUP-UNCONFIRMED"
            raise
        finally:
            run, self.run_task = self.run_task, None
            if run is not None and run is not caller:
                if not run.done():
                    run.cancel()
                await asyncio.gather(run, return_exceptions=True)

    def health(self) -> dict:
        return {"enabled": True, "ready": self.adapter is not None and not self.error_code,
                "audio_route": self.binding.route, "error_code": self.error_code,
                "duplex_verified": False,
                "segmented_tts": True, "audio_reasoner": "session_gemma",
                "capture_input": "native_audio" if self.native_capture else "sherpa_text",
                "recent_traces": list(self.recent_traces)}
