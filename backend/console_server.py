"""YHLZ Workbench console server (ledger 0222+): single-page control deck.

Serves assets/webui/* on port 8321 and streams Yuanheng turns back as SSE:
    GET  /                -> index.html (static)
    GET  /console.css     -> styles
    GET  /console.js      -> app
    GET  /state           -> json status (daemon/gemma/session/memory)
    GET  /logs|/growth|/ledger|/mem|/sessions|/monitor
    POST /v1/chat/completions (stream) | /turn | /voice
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backend.yhlz_paths import BOT_UIN, NAPCAT_QR, NAPCAT_WEBUI, QQWATCH_SHELL
from backend import turn_control as _tc
from backend.status_views import (
    drives_list as _drives_list,
    ollama_state as _ollama_state,
    qq_status as _qq_status,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = _PROJECT_ROOT / "assets" / "webui"
LEDGER_FILE = _PROJECT_ROOT / "docs" / "上下文台账.md"
_LOG_RING: list[dict] = []
from collections import deque as _deque

_LOG_RING = _deque(maxlen=60)
_sessions: dict[str, float] = {}

SETTINGS_FILE = _PROJECT_ROOT / "data" / "console.json"
DEFAULT_SETTINGS = {
    "device": 1,
    "denoise": "rnnoise",
    "duration": 60.0,
    "asr": "sensevoice",
    "tts_speaker": "Vivian",
    "tts_speak": True,
    "tts_model": "clone",  # A4 (0454): default voice = Edge(Xiaoyi) clone
}

TTS_DIRS = {
    # 8GB VRAM: 1.7B CustomVoice OOM 实锤（0419/0434），仅保留 0.6B（ledger 0448）
    "0.6B": _PROJECT_ROOT / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-0.6B-CustomVoice",
}
# A4 (ledger 0454): Edge(Xiaoyi) timbre cloned into the local 0.6B-Base model
CLONE_CFG = {
    "model": _PROJECT_ROOT / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-0.6B-Base",
    "ref_dir": _PROJECT_ROOT / "models" / "tts" / "refs" / "xiaoyi",
    "ref": "ref01",
    "label": "0.6B·Edge克隆(Xiaoyi)",
}
# ledger 0463: accepted voices live side by side and are picked by emotion —
# xiaoyi (calm default) vs bright (designed 清亮俏皮, for upbeat lines).
# ledger 0852 (2026-10-18): 老爹定「用清亮嗓」——对话默认嗓改为 bright，
# 不再按情绪切 xiaoyi；yuanheng（02）仍只作手动可选项。
YUANHENG_CFG = dict(CLONE_CFG)
YUANHENG_CFG.update(
    ref_dir=_PROJECT_ROOT / "models" / "tts" / "refs" / "yuanheng",
    ref="ref01",
    label="元亨本音 v2（02 清亮胸腔）",
)
CLONE_VOICES: dict = {
    "yuanheng": YUANHENG_CFG,
    "xiaoyi": dict(CLONE_CFG),
    "bright": {
        "model": CLONE_CFG["model"],
        "ref_dir": _PROJECT_ROOT / "models" / "tts" / "refs" / "design_bright",
        "ref": "ref01",
        "label": "设计嗓·清亮俏皮",
    },
}
VOICE_BY_EMOTION = {"happy": "bright", "surprised": "bright",
                    "excited": "bright", "angry": "bright"}
# ledger 0853 (2026-10-18): 稳定性实验 — 0.7/20 比默认 0.9/50 明显更稳
# （同句三次 pair cos 0.789→0.898；对参考 0.838→0.894），故设为克隆默认采样。
CLONE_GEN_PARAMS = {"temperature": 0.7, "top_k": 20}
_TTS = {"model": None, "key": None}


def _pick_clone_voice(which: str, text: str) -> str:
    """clone / clone:auto -> emotion-based pick; clone:<name> explicit."""
    w = str(which or "").strip().lower()
    if w.startswith("clone:"):
        name = w.split(":", 1)[1]
        if name in CLONE_VOICES:
            return name
    try:
        from backend.emotion_classifier import classify_emotion

        emo = str((classify_emotion(str(text)) or {}).get("emotion") or "")
    except Exception:
        emo = ""
    return VOICE_BY_EMOTION.get(emo, "bright")


def _get_engine(which: str):
    """Resident Qwen3-TTS engine (single slot): CustomVoice 0.6B or clone-Base.

    Unknown/disabled keys (e.g. legacy "1.7B") fall back to 0.6B instead of
    trying to load a model that would OOM the 8GB card (ledger 0448)."""
    import torch
    from faster_qwen3_tts import FasterQwen3TTS

    key = str(which or "0.6B").strip().lower()
    key = "clone" if key.startswith("clone") else "0.6B"
    path = CLONE_CFG["model"] if key == "clone" else TTS_DIRS["0.6B"]
    if _TTS["model"] is None or _TTS["key"] != key:
        try:
            if _TTS["model"] is not None:
                del _TTS["model"]
                import gc

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
        except Exception:
            pass
        _TTS["model"] = FasterQwen3TTS.from_pretrained(
            str(path), device="cuda", dtype=torch.bfloat16)
        _TTS["key"] = key
    return _TTS["model"]


def _wav_bytes(audio, sr) -> bytes:
    """float32 mono audio -> 16-bit PCM WAV bytes (shared by /tts routes)."""
    import io as _io
    import wave as _wave

    import numpy as _np

    buf = _io.BytesIO()
    with _wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        pcm = _np.clip(_np.asarray(audio, dtype="float32"), -1.0, 1.0)
        w.writeframes((pcm * 32767.0).astype("<i2").tobytes())
    return buf.getvalue()


def _synth(which: str, text: str, speaker: str = "Vivian"):
    """Synthesize one chunk with the selected engine -> (audio, sr).

    "clone" = zero-shot Edge(Xiaoyi) timbre via the 0.6B-Base model
    (ledger 0453/0454); anything else = CustomVoice preset speaker.
    Clone failures degrade to the CustomVoice voice instead of silence."""
    if str(which or "").strip().lower().startswith("clone"):
        try:
            voice = _pick_clone_voice(which, text)
            cfg = (CLONE_VOICES.get(voice) or CLONE_VOICES.get("bright")
                   or next(iter(CLONE_VOICES.values())))
            m = _get_engine("clone")
            ref_dir = Path(cfg["ref_dir"])
            ref_wav = ref_dir / f"{cfg['ref']}.wav"
            ref_txt = ""
            try:
                ref_txt = (ref_dir / f"{cfg['ref']}.txt").read_text(
                    encoding="utf-8").strip()
            except Exception:
                pass
            wavs, sr = m.generate_voice_clone(
                text=str(text)[:120], language="Chinese",
                ref_audio=str(ref_wav), ref_text=ref_txt,
                **CLONE_GEN_PARAMS)
            audio = wavs[0] if isinstance(wavs, (list, tuple)) else wavs
            return audio, sr
        except Exception as exc:  # noqa: BLE001
            _log("tts", f"clone fail({type(exc).__name__}) -> fallback 0.6B")
    m = _get_engine("0.6B")
    wavs, sr = m.generate_custom_voice(
        text=str(text)[:120], language="Chinese",
        speaker=str(speaker or "Vivian"),
        instruct="自然地说，像和亲近的人聊天，别播音腔。")
    audio = wavs[0] if isinstance(wavs, (list, tuple)) else wavs
    return audio, sr


# ---- workbench singing module (Phase B, ledger 0457) ----
SING_DIR = _PROJECT_ROOT / "cache" / "sing"
SING_PROMPT = _PROJECT_ROOT / "models" / "tts" / "refs" / "xiaoyi" / "ref01.wav"
# ledger 0464: finished covers land in the audio materials folder
SING_OUT_DIR = _PROJECT_ROOT / "音频素材" / "翻唱产出"
_sing_lock = threading.Lock()
SING_STATE: dict = {"status": "idle", "step": "", "error": "", "result": "",
                    "output": "", "voice": "xiaoyi", "log": "", "sep": "",
                    "started": 0.0, "finished": 0.0, "song_id": ""}
# 2026-10-21 验收：Seed-VC 44k + 柔化 e 成为生产链路；SoulX 退居回滚位。
_COVER_ENGINE = os.getenv("YH_COVER_ENGINE", "produce")  # produce（投产，2026-11-06）/ seedvc / soulx（回滚）


def _wsl_path(p) -> str:
    s = str(Path(p).resolve()).replace("\\", "/")
    if len(s) > 1 and s[1] == ":":
        return "/mnt/" + s[0].lower() + s[2:]
    return s


def _unload_tts() -> None:
    try:
        if _TTS.get("model") is not None:
            _TTS["model"] = None
            _TTS["key"] = None
            import gc

            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
    except Exception:
        pass


# ---- dev mode (QQ 静默) workbench switch, ledger 0469/0470 ----
QQ_SILENT_FLAG = _PROJECT_ROOT / "cache" / "tmp" / "qq_silent.flag"


def devmode_state() -> dict:
    """开发模式状态：flag 文件（工作台开关）+ 环境变量（部署级锁定）。"""
    import os

    env = str(os.getenv("YHLZ_QQ_SILENT", "")).strip().lower() in (
        "1", "true", "yes", "on")
    flag = QQ_SILENT_FLAG.exists()
    return {"qq_silent": bool(env or flag), "flag": flag, "env": env}


def devmode_set(qq_silent: bool) -> dict:
    """开/关开发模式（QQ 桥静默）：watchdog 每轮读 flag，无需重启。"""
    try:
        if qq_silent:
            QQ_SILENT_FLAG.parent.mkdir(parents=True, exist_ok=True)
            QQ_SILENT_FLAG.write_text(
                "dev mode: QQ bridge silent (workbench toggle)\n",
                encoding="utf-8")
        else:
            QQ_SILENT_FLAG.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, **devmode_state()}


def sing_status() -> dict:
    return {"ok": True, **dict(SING_STATE)}


def _job_seedvc(tgt: Path, voice: str) -> None:
    """Production cover path (2026-10-21, ledger 0935): Seed-VC 44k + 柔化 e.

    旧 SoulX 链路已退出生产；回滚只需把 _COVER_ENGINE 切回 "soulx"。
    """
    from backend import gpu_lock, gpu_window

    _dsp_py = _PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    try:
        SING_STATE["step"] = "卸载本地 TTS，腾显存"
        _unload_tts()
        SING_STATE["step"] = "等待聊天结束（GPU 互锁）"
        if not gpu_lock.enter_window():
            raise RuntimeError("互锁状态异常（无法进入唱窗）")
        gpu_lock.wait_chat_idle(timeout=120)
        _unload_tts()
        time.sleep(2)
        SING_STATE["step"] = "唱窗：暂停 LLM 与看护"
        win = gpu_window.open_window()
        if not win.get("ok"):
            _unload_tts()
            time.sleep(5)
            win = gpu_window.open_window()
        if not win.get("ok"):
            raise RuntimeError(f"显存不足（free={win.get('free_mb')}MB）")

        SING_STATE["step"] = "翻唱中（Seed-VC 44k + 柔化 e）"
        job_dir = SING_DIR / "seedvc_job"
        job_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update({
            "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
            "HF_ENDPOINT": "https://hf-mirror.com",
            "NO_PROXY": "localhost,127.0.0.1,::1,.maas.aliyuncs.com",
            "PATH": str(_PROJECT_ROOT / "cache" / "tools"
                        / "ffmpeg-9.0.1-essentials_build" / "bin")
                    + os.pathsep + env.get("PATH", ""),
        })
        # 每首歌独立分轨目录：绝不复用上一首的 stem（2026-10-21 实测踩坑）。
        stems_dir = SING_DIR / f"stem3_{time.strftime('%Y%m%d_%H%M%S')}"
        r = subprocess.run(
            [str(_dsp_py if _dsp_py.exists() else sys.executable),
             str(_PROJECT_ROOT / "tools" / "cover_seedvc.py"),
             str(tgt), "--voice", voice, "--presets", "e",
             "--stems-dir", str(stems_dir),
             "--out-dir", str(job_dir)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=3600, env=env,
            creationflags=0x08000000)  # CREATE_NO_WINDOW：防控制台关闭杀子进程
        tail = (r.stdout or "")[-1500:] + (r.stderr or "")[-600:]
        SING_STATE["log"] = tail[-900:]
        info = None
        for line in reversed((r.stdout or "").splitlines()):
            line = line.strip()
            if line.startswith("{") and '"ok"' in line:
                try:
                    info = json.loads(line)
                    break
                except Exception:  # noqa: BLE001
                    continue
        if r.returncode != 0 or not info or not info.get("ok"):
            raise RuntimeError(f"新链路失败 exit={r.returncode}: {tail[-280:]}")
        # 2026-11-01：分离引擎必须可见——上一次静默退回 demucs 两轨（无和声）
        # 直接把质量拉低，却没人知道。降级就在日志里明写。
        _sep = str(info.get("sep") or "")
        if _sep.startswith("demucs"):
            SING_STATE["log"] = (SING_STATE.get("log", "")
                                 + " ⚠ 分离降级：demucs 两轨（无和声轨）")[-900:]
        outputs = info.get("outputs") or []
        if not outputs:
            raise RuntimeError("新链路没有产出")
        final_src = Path(outputs[0])
        out_dir = Path(info.get("out_dir") or final_src.parent)

        SING_OUT_DIR.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", tgt.stem)[:40] or "cover"
        vtag = "清亮嗓" if voice == "bright" else "Xiaoyi嗓"
        run_dir = SING_OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{stem}"
        run_dir.mkdir(parents=True, exist_ok=True)
        final = run_dir / f"成品_{stem}_{vtag}.wav"
        shutil.copy2(final_src, final)
        # 2026-10-21 老爹定：产出只要成品，不再保留干声/和声/伴奏/说明分层。
        sid = ""
        try:
            from backend import song_library

            item = song_library.save_ref(
                title=f"{stem}（元亨翻唱·{vtag}·SeedVC）", wav_path=final,
                source="workbench-cover", target=str(tgt),
                tags=["翻唱", "SeedVC"])
            sid = str(item.get("id") or "")
        except Exception:  # noqa: BLE001
            sid = ""
        SING_STATE.update(status="done", step="完成", result=str(final),
                          output=str(final), song_id=sid)
    except Exception as exc:  # noqa: BLE001
        SING_STATE.update(status="error", step="失败",
                          error=f"{type(exc).__name__}: {exc}"[:280])
    finally:
        SING_STATE["step"] = "恢复 LLM 与看护"
        try:
            gpu_window.close_window()
        except Exception:  # noqa: BLE001
            pass
        try:
            gpu_lock.release_sing()
        except Exception:  # noqa: BLE001
            pass
        SING_STATE["finished"] = time.time()
        try:
            _sing_lock.release()
        except Exception:  # noqa: BLE001
            pass


def _job_produce(tgt: Path, voice: str) -> None:
    """投产链路（2026-11-06，台账 1106/1066）：走 tools/cover_produce.py S1–S7。

    与 _job_seedvc 的区别：分轨不再靠 cover_seedvc 的 WSL/demucs 兜底，而是
    Kim(MSST) → MDX(audio-separator) → Seed-VC；`sep` 必须回传到 SING_STATE。
    """
    from backend import gpu_lock, gpu_window

    _py = _PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    try:
        SING_STATE["step"] = "卸载本地 TTS，腾显存"
        _unload_tts()
        SING_STATE["step"] = "等待聊天结束（GPU 互锁）"
        if not gpu_lock.enter_window():
            raise RuntimeError("互锁状态异常（无法进入唱窗）")
        gpu_lock.wait_chat_idle(timeout=120)
        _unload_tts()
        SING_STATE["step"] = "翻唱中（Kim → MDX → Seed-VC → 混音，约 6–7 分钟）"
        job_dir = SING_DIR / f"produce_{time.strftime('%Y%m%d_%H%M%S')}"
        job_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update({
            "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
            "HF_ENDPOINT": "https://hf-mirror.com",
            "NO_PROXY": "localhost,127.0.0.1,::1,.maas.aliyuncs.com",
        })
        r = subprocess.run(
            [str(_py if _py.exists() else sys.executable),
             str(_PROJECT_ROOT / "tools" / "cover_produce.py"),
             str(tgt), "--voice", voice, "--presets", "e",
             "--out-dir", str(job_dir)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=7200, env=env,
            creationflags=0x08000000)
        tail = (r.stdout or "")[-1500:] + (r.stderr or "")[-600:]
        SING_STATE["log"] = tail[-900:]
        info = None
        for line in reversed((r.stdout or "").splitlines()):
            line = line.strip()
            if line.startswith("{") and '"ok"' in line:
                try:
                    info = json.loads(line)
                    break
                except Exception:  # noqa: BLE001
                    continue
        if r.returncode != 0 or not info or not info.get("ok"):
            raise RuntimeError(f"投产链路失败 exit={r.returncode}: {tail[-280:]}")
        sep = str(info.get("sep") or "")
        SING_STATE["sep"] = sep
        if not sep.startswith("native-kim"):
            SING_STATE["log"] = (SING_STATE.get("log", "")
                                 + f" ⚠ 分轨链路：{sep or '未知'}")[-900:]
        final_src = Path(str(info.get("final") or ""))
        if not final_src.is_file():
            raise RuntimeError("投产链路没有成品")

        SING_OUT_DIR.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", tgt.stem)[:40] or "cover"
        vtag = "清亮嗓" if voice == "bright" else "Xiaoyi嗓"
        run_dir = SING_OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{stem}"
        run_dir.mkdir(parents=True, exist_ok=True)
        final = run_dir / f"成品_{stem}_{vtag}.wav"
        shutil.copy2(final_src, final)
        sid = ""
        try:
            from backend import song_library

            item = song_library.save_ref(
                title=f"{stem}（元亨翻唱·{vtag}·{sep or 'native'}）",
                wav_path=final, source="workbench-cover-produce",
                target=str(tgt), tags=["翻唱", "SeedVC", sep or "native"])
            sid = str(item.get("id") or "")
        except Exception:  # noqa: BLE001
            sid = ""
        SING_STATE.update(status="done", step="完成", result=str(final),
                          output=str(final), song_id=sid)
    except Exception as exc:  # noqa: BLE001
        SING_STATE.update(status="error", step="失败",
                          error=f"{type(exc).__name__}: {exc}"[:280])
    finally:
        SING_STATE["step"] = "恢复 LLM 与看护"
        try:
            gpu_window.close_window()
        except Exception:  # noqa: BLE001
            pass
        try:
            gpu_lock.release_sing()
        except Exception:  # noqa: BLE001
            pass
        SING_STATE["finished"] = time.time()
        try:
            _sing_lock.release()
        except Exception:  # noqa: BLE001
            pass


def sing_start(target: str, prompt: str = "", voice: str = "bright") -> dict:
    """Kick off a cover job in a background thread; returns immediately.

    Rule (2026-10-09): only the dry lead (干声) is converted; harmony (和声)
    and background (伴奏) keep the original audio — split lead/backing/bgm,
    SVC the lead only, then mix back. Two-stage (ledger 0458): stem split +
    F0 run OUTSIDE the GPU window so the chat stays online; only the SVC
    stage stops the LLM. Ledger 0464: voice picks the SVC prompt; the
    finished wav lands in 音频素材/翻唱产出/ and the song library references
    it. Ledger 0476: one folder per production with layers + 说明.txt."""
    tgt = Path(str(target or "")).resolve()
    if not tgt.is_file():
        return {"ok": False, "error": f"目标文件不存在：{target}"}
    voice = str(voice or "bright").strip().lower()
    # 2026-10-18: SoulX 需要 WSL 侧 prompt_<voice>/；yuanheng 的 prompt 还没准备，
    # 暂只允许既有两嗓；等 RVC/新 prompt 上线再切 yuanheng。
    if voice not in ("xiaoyi", "bright"):
        voice = "bright"
    from backend import gpu_lock

    if not gpu_lock.acquire_sing():
        return {"ok": False, "error": "GPU 任务互锁：已有唱歌任务在跑"}
    if not _sing_lock.acquire(blocking=False):
        gpu_lock.release_sing()
        return {"ok": False, "error": "已有翻唱任务在跑"}
    SING_STATE.update(status="running", step="排队启动", error="", result="",
                      output="", log="", started=time.time(), finished=0.0,
                      song_id="", voice=voice)
    if prompt:
        prm = Path(str(prompt)).resolve()
    else:
        cfg = CLONE_VOICES.get(voice) or CLONE_VOICES["bright"]
        prm = Path(cfg["ref_dir"]) / f"{cfg['ref']}.wav"

    def _job() -> None:
        from backend import gpu_window

        if _COVER_ENGINE == "produce":
            _job_produce(tgt, voice)
            return
        if _COVER_ENGINE == "seedvc":
            _job_seedvc(tgt, voice)
            return

        try:
            SING_STATE["step"] = "卸载本地 TTS，腾显存"
            _unload_tts()
            # Rule (2026-10-09): split first — only the dry lead is converted.
            stem_dir = SING_DIR / "stem3"
            stem_dir.mkdir(parents=True, exist_ok=True)
            SING_STATE["step"] = "预处理：分轨（干声/和声/伴奏，聊天不中断）"
            r0 = subprocess.run(
                ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash",
                 _wsl_path(_PROJECT_ROOT / "tools" / "wsl_stem3_split.sh"),
                 _wsl_path(tgt), _wsl_path(stem_dir)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=3600)
            if r0.returncode != 0:
                raise RuntimeError(
                    f"分轨失败 exit={r0.returncode}: "
                    f"{(r0.stderr or '')[-200:]}")
            # v3 定版 (2026-10-11, ledger 0746): 干声先过 MSST 去混响
            # （anvuew SDR19.17）；F0/SVC/清晰增强都用去混响后的干声。
            SING_STATE["step"] = "预处理：干声去混响（MSST anvuew，聊天不中断）"
            lead_in = stem_dir / "lead.wav"
            lead_dry = stem_dir / "lead_dry.wav"
            r0c = subprocess.run(
                ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash",
                 _wsl_path(_PROJECT_ROOT / "tools" / "wsl_dereverb.sh"),
                 _wsl_path(lead_in), _wsl_path(lead_dry)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=3600)
            if r0c.returncode != 0 or not lead_dry.is_file():
                raise RuntimeError(
                    f"去混响失败 exit={r0c.returncode}: "
                    f"{(r0c.stderr or '')[-200:]}")
            SING_STATE["step"] = "预处理：干声 F0（聊天不中断）"
            r0b = subprocess.run(
                ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash",
                 _wsl_path(_PROJECT_ROOT / "tools" / "wsl_soulx_prep.sh"),
                 _wsl_path(prm), _wsl_path(lead_dry),
                 "0", voice],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=1800)
            if r0b.returncode != 0:
                raise RuntimeError(
                    f"干声 F0 失败 exit={r0b.returncode}: "
                    f"{(r0b.stderr or '')[-200:]}")
            # interlock: block new chat/TTS, then let in-flight turns drain
            SING_STATE["step"] = "等待聊天结束（GPU 互锁）"
            if not gpu_lock.enter_window():
                raise RuntimeError("互锁状态异常（无法进入唱窗）")
            gpu_lock.wait_chat_idle(timeout=120)
            # v3.1 (2026-10-11 千本樱实测): 预处理期间聊天不中断，TTS 克隆引擎
            # 可能被聊天重新装载（~2.4GB），而卸载只在任务开始时做过一次 →
            # 开窗前再卸一次 + 短等，避免窗口因显存缺口失败（曾 free=5676）。
            _unload_tts()
            time.sleep(2)
            SING_STATE["step"] = "唱窗：暂停 LLM 与看护"
            win = gpu_window.open_window()
            if not win.get("ok"):
                _unload_tts()
                time.sleep(5)
                win = gpu_window.open_window()
            if not win.get("ok"):
                raise RuntimeError(f"显存不足（free={win.get('free_mb')}MB）")
            SING_STATE["step"] = "翻唱中（SVC 只换干声，约 2 分钟）"
            out = SING_DIR / "out"
            out.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(
                ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash",
                 _wsl_path(_PROJECT_ROOT / "tools" / "wsl_soulx_svc.sh"),
                 _wsl_path(out), voice],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=1800)
            tail = (r.stdout or "")[-1200:] + (r.stderr or "")[-600:]
            SING_STATE["log"] = tail[-900:]
            gen = out / "generated.wav"
            if r.returncode != 0 or not gen.is_file():
                raise RuntimeError(f"SVC 失败 exit={r.returncode}")
            # v2 定版 (2026-10-10, ledger 0740): 清晰增强 — 把（去混响）干声
            # >6kHz 的齿音/气息叠回 AI 干声（老爹选定 V2b：步数64 + ×0.65）
            SING_STATE["step"] = "清晰增强（叠回原声齿音）"
            enh = out / "enhanced.wav"
            r2b = subprocess.run(
                ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash",
                 _wsl_path(_PROJECT_ROOT / "tools" / "wsl_clarity_enhance.sh"),
                 _wsl_path(gen), _wsl_path(lead_dry),
                 _wsl_path(enh), "--gain", "0.65"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=600)
            if r2b.returncode != 0 or not enh.is_file():
                raise RuntimeError(f"清晰增强失败 exit={r2b.returncode}")
            # v3 定版 (2026-10-11, ledger 0746): 柔化 DSP（轻压缩+动态去齿+
            # 轻饱和 = 群听评/老爹验收的 V3-e 配方），等响对齐。
            SING_STATE["step"] = "柔化 DSP（v3 定版：轻压缩+动态去齿+轻饱和）"
            dsp_out = out / "dsp_soft.wav"
            # daemon 实际服务进程可能不是 .venv python（曾见系统 python 子进程
            # 服务、无 numpy）——固定用 .venv python 跑 DSP（2026-10-11 修复）。
            _dsp_py = _PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
            r2c = subprocess.run(
                [str(_dsp_py if _dsp_py.exists() else sys.executable),
                 str(_PROJECT_ROOT / "tools" / "cover_v3_dsp.py"),
                 str(enh), str(dsp_out), "--preset", "e"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=1200)
            if r2c.returncode != 0 or not dsp_out.is_file():
                raise RuntimeError(
                    f"柔化 DSP 失败 exit={r2c.returncode}: "
                    f"{(r2c.stderr or '')[-200:]}")
            # rule 2026-10-09: mix the AI lead back with ORIGINAL harmony/bgm
            # (v3 定版：伴奏 +3dB → 1.13，群听评验收的 BGM 修正)
            SING_STATE["step"] = "三轨混回（AI干声 + 原声和声/伴奏）"
            mixed = out / "mixed.wav"
            r3 = subprocess.run(
                ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash",
                 _wsl_path(_PROJECT_ROOT / "tools" / "wsl_mix3.sh"),
                 _wsl_path(dsp_out), _wsl_path(stem_dir / "backing.wav"),
                 _wsl_path(stem_dir / "bgm.wav"), _wsl_path(mixed),
                 "--lead-gain", "1.4", "--backing-gain", "0.8",
                 "--bgm-gain", "1.13"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=600)
            if r3.returncode != 0 or not mixed.is_file():
                raise RuntimeError(f"三轨混回失败 exit={r3.returncode}")
            # ledger 0464/0476: one folder per production inside
            # 音频素材/翻唱产出/ (type-first names, layers kept for
            # error-hunting); the library references the final mixed wav.
            SING_OUT_DIR.mkdir(parents=True, exist_ok=True)
            stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_",
                          Path(tgt).stem)[:40] or "cover"
            vtag = "清亮嗓" if voice == "bright" else "Xiaoyi嗓"
            run_dir = SING_OUT_DIR / (
                f"{time.strftime('%Y%m%d-%H%M%S')}_{stem}")
            run_dir.mkdir(parents=True, exist_ok=True)
            for type_name, src, tag in (
                    ("干声", stem_dir / "lead.wav", ""),
                    ("干声_去混响", lead_dry, ""),
                    ("和声", stem_dir / "backing.wav", ""),
                    ("伴奏", stem_dir / "bgm.wav", ""),
                    ("AI主唱", gen, f"_{vtag}"),
                    ("AI主唱_增强", enh, f"_{vtag}"),
                    ("AI主唱_柔化", dsp_out, f"_{vtag}")):
                try:
                    shutil.copy2(src, run_dir / f"{type_name}_{stem}{tag}.wav")
                except Exception:
                    pass  # layers are diagnostics; do not fail the job
            final = run_dir / f"成品_{stem}_{vtag}_三轨.wav"
            shutil.copy2(mixed, final)
            (run_dir / "说明.txt").write_text(
                f"元亨翻唱 · 生产档案（工作台·v3 定版）\n源曲：{tgt}\n"
                f"流程：demucs 分轨 → MDX 卡拉OK（干声/和声）→ MSST 去混响"
                f"（anvuew）→ F0 → SoulX-SVC 只换干声（原调+fp16+步数64）→ "
                f"清晰增强（去混响干声>6kHz×0.65）→ 柔化 DSP（轻压缩+动态去齿"
                f"+轻饱和）→ 三轨混回（主唱1.4/和声0.8/伴奏1.13）\n"
                f"嗓：{vtag}（{voice}）；和声与伴奏保留原声\n",
                encoding="utf-8")
            # finished songs are saved locally; QQ/main chain may only use
            # library items — here the library references the materials file
            sid = ""
            try:
                from backend import song_library

                item = song_library.save_ref(
                    title=f"{stem}（元亨翻唱·{vtag}·三轨）", wav_path=final,
                    source="workbench-cover", target=str(tgt),
                    tags=["翻唱", "三轨"])
                sid = str(item.get("id") or "")
            except Exception:
                sid = ""
            SING_STATE.update(status="done", step="完成", result=str(mixed),
                              output=str(final), song_id=sid)
        except Exception as exc:  # noqa: BLE001
            SING_STATE.update(status="error", step="失败",
                              error=f"{type(exc).__name__}: {exc}"[:280])
        finally:
            SING_STATE["step"] = "恢复 LLM 与看护"
            try:
                gpu_window.close_window()
            except Exception:
                pass
            try:
                gpu_lock.release_sing()
            except Exception:
                pass
            SING_STATE["finished"] = time.time()
            try:
                _sing_lock.release()
            except Exception:
                pass

    threading.Thread(target=_job, daemon=True, name="sing-job").start()
    return {"ok": True, "status": "running"}


class _StreamingSpeaker:
    """Streaming TTS (ledger 0309): synthesize+play sentences as the LLM emits
    them, so the first audio no longer waits for the whole reply. One resident
    InputStream; barge-in (or turn cancel) stops playback."""

    def __init__(self, speaker: str, device: int, model_key: str,
                 should_stop=None, on_trace=None) -> None:
        import queue as _q
        import threading as _th

        self._q: "_q.Queue" = _q.Queue()
        self._speaker = str(speaker or "Vivian")
        self._device = int(device or 1)
        self._key = str(model_key or "0.6B")
        self._should_stop = should_stop
        self._on_trace = on_trace
        self._trace_seen: set[str] = set()
        self._interrupted = False
        self._thread = _th.Thread(target=self._run, daemon=True)

    def _trace(self, event: str, detail: str = "") -> None:
        if event in self._trace_seen:
            return
        self._trace_seen.add(event)
        if self._on_trace is not None:
            try:
                self._on_trace(event, detail)
            except Exception:
                pass

    def start(self) -> None:
        self._thread.start()

    def feed(self, sentence: str) -> None:
        s = str(sentence or "").strip()
        if s and not self._interrupted:
            self._q.put(s)

    def finish(self) -> str:
        self._q.put(None)
        self._thread.join(timeout=180)
        if self._interrupted:
            return "interrupted"
        if self._should_stop is not None and self._should_stop():
            return "cancelled"
        return "done"

    def _run(self) -> None:
        import numpy as np
        import sounddevice as sd

        try:
            _get_engine(self._key)
        except Exception:
            _log("voice", "stream tts load fail")
            return
        _log("voice", "stream tts ready")

        def loop(inp) -> None:
            while True:
                s = self._q.get()
                if s is None:
                    break
                if self._interrupted:
                    continue
                if self._should_stop is not None and self._should_stop():
                    self._interrupted = True
                    continue
                try:
                    audio, sr = _synth(self._key, s, self._speaker)
                    samples = np.asarray(audio, dtype="float32")
                    self._trace("tts_first_synth", str(len(samples)))
                except Exception:
                    continue
                rms = float(np.sqrt(np.mean(samples * samples)) + 1e-9)
                thr = max(0.03, rms * 1.5)
                try:
                    sd.play(samples, int(sr))
                    self._trace("playback_start", str(len(samples)))
                    _log("voice", f"stream tts play {len(samples)}")
                except Exception:
                    continue
                dur = len(samples) / float(sr)
                t0 = time.time()
                hot = 0
                while time.time() - t0 < dur + 0.3:
                    if self._should_stop is not None and self._should_stop():
                        self._interrupted = True
                        break
                    if inp is None:
                        time.sleep(0.05)
                        continue
                    try:
                        data, _ = inp.read(1600)
                    except Exception:
                        break
                    mono = np.asarray(
                        data[:, 0] if getattr(data, "ndim", 1) > 1 else data,
                        dtype="float32")
                    r = float(np.sqrt(np.mean(mono * mono)) + 1e-9)
                    if r > thr:
                        hot += 1
                        if hot >= 2:
                            self._interrupted = True
                            self._trace("barge_in", "input_rms")
                            break
                    else:
                        hot = 0
                if self._interrupted:
                    break

        try:
            with sd.InputStream(device=self._device, samplerate=16000,
                                channels=1, dtype="float32", blocksize=1600,
                                latency="low") as inp:
                loop(inp)
        except Exception:
            loop(None)
        try:
            sd.stop()
        except Exception:
            pass
        finally:
            self._trace("playback_stop")


def _settings_load() -> dict:
    d = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.exists():
            import json as _j

            d.update(_j.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return d


def _settings_save(patch: dict) -> dict:
    import json as _j

    cur = _settings_load()
    for k in list(DEFAULT_SETTINGS):
        if k in patch:
            try:
                if isinstance(DEFAULT_SETTINGS[k], bool):
                    cur[k] = str(patch[k]).lower() in ("1", "true", "yes", "on")
                elif isinstance(DEFAULT_SETTINGS[k], float):
                    cur[k] = float(patch[k])
                elif isinstance(DEFAULT_SETTINGS[k], int):
                    cur[k] = int(patch[k])
                else:
                    cur[k] = str(patch[k])
            except Exception:
                pass
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(_j.dumps(cur, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    _log("settings", ",".join(k for k in patch if k in DEFAULT_SETTINGS))
    return cur


def _audio_devices() -> list[dict]:
    try:
        import sounddevice as sd

        return [
            {"index": i, "name": d["name"]}
            for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0
        ]
    except Exception:
        return []


def _log(event: str, detail: str = "") -> None:
    _LOG_RING.append({"t": time.time(), "event": event, "detail": detail[:160]})


def _bring_qq_front(delay: float = 8.0) -> None:
    """After NapCat starts, bring the QQ/NapCat login window to the foreground."""
    import threading

    def _go() -> None:
        time.sleep(delay)
        try:
            import subprocess

            ps = (
                "Add-Type -Namespace N -Name W -MemberDefinition "
                "'[DllImport(\"user32.dll\")] public static extern bool "
                "ShowWindow(IntPtr h,int n); "
                "[DllImport(\"user32.dll\")] public static extern bool "
                "SetForegroundWindow(IntPtr h);'; "
                "Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and ("
                "$_.MainWindowTitle -like '*launcher-user*' -or "
                "$_.MainWindowTitle -like '*NapCat*' -or "
                "$_.ProcessName -like 'QQ*' -or $_.ProcessName -like '*NapCat*') } | "
                "ForEach-Object { [N.W]::ShowWindow($_.MainWindowHandle,9); "
                "[N.W]::SetForegroundWindow($_.MainWindowHandle) }"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=20)
        except Exception:
            pass

    threading.Thread(target=_go, daemon=True).start()


_SHERPA = {"m": None, "tried": False}


def _get_sherpa():
    """Lazy singleton streaming ASR (sherpa zh-en) for live partials."""
    if not _SHERPA["tried"]:
        _SHERPA["tried"] = True
        try:
            from backend.target_sherpa_asr import (
                SherpaOnlineASRConfig,
                SherpaOnlineASRProvider,
            )

            _SHERPA["m"] = SherpaOnlineASRProvider(
                SherpaOnlineASRConfig(min_available_memory_bytes=256 * 1024 * 1024))
            _SHERPA["m"].start()
        except Exception:
            _SHERPA["m"] = None
    return _SHERPA["m"]


def _tcp_open(host: str, port: int, timeout: float = 0.8) -> bool:
    import socket

    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


# ---- 启动入口（台账 0792）：NapCat 面板 / 翻唱链路官方 UI ----
NAPCAT_WEBUI_DEFAULT_PORT = 6099


def _napcat_webui() -> tuple[int, str]:
    """NapCat 管理面板地址；端口读 webui.json，兜底 6099（QQ技术台账）。"""
    port = NAPCAT_WEBUI_DEFAULT_PORT
    try:
        d = json.loads(NAPCAT_WEBUI.read_text(encoding="utf-8"))
        port = int(d.get("port") or port)
    except Exception:
        pass
    return port, f"http://127.0.0.1:{port}/webui"


def _napcat_procs_alive() -> bool:
    """NapCat 活着 == OneBot 端口在听。

    2026-10-29：原来按进程名（NapCatWinBootMain.exe / QQ.exe）判断，但
    NapCatWinBootMain 注入完就退出、卡住时又一直挂着——两种情况都会误判，
    工作台因此要么说"已运行"挡住重启，要么把卡死的窗口当成健康。
    """
    try:
        from backend.napcat_launcher import onebot_online

        return onebot_online()
    except Exception:
        pass
    return False


def _sse(data: dict) -> bytes:
    return ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode("utf-8")


GET_UI = {"/", "/index.html", "/console.css", "/console.js", "/state",
          "/history", "/monitor", "/settings", "/devices", "/logs",
          "/ledger", "/mem", "/favicon.png", "/loading.webp", "/sessions",
          "/avatar.html", "/avatar.js", "/avatar-models", "/chat_popup.html",
          "/emotion", "/qq-qrcode", "/growth", "/devmode",
          "/official-ui/status"}
MODEL_DIR = _PROJECT_ROOT / "角色皮套"
VENDOR_DIR = _PROJECT_ROOT / "assets" / "vendor" / "live2d"
POST_UI = {"/talk", "/voice", "/reset", "/settings", "/control", "/session",
           "/tap", "/devmode"}


class ConsoleHandler(BaseHTTPRequestHandler):
    runtime = None

    # ---------- plumbing ----------
    def log_message(self, fmt, *args):  # quieter
        pass

    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, name: str) -> None:
        path = (STATIC_DIR / name).resolve()
        if not path.is_file() or STATIC_DIR not in path.parents:
            self.send_error(404)
            return
        body = path.read_bytes()
        ctype = ("text/html; charset=utf-8" if name.endswith(".html")
                 else "text/css; charset=utf-8" if name.endswith(".css")
                 else "application/javascript; charset=utf-8"
                 if name.endswith(".js") else "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _qq_qrcode(self) -> None:
        """Serve NapCat's login QR (saved to qrcode.png) so the workbench can
        show it directly — NapCat is headless (no console/QQ window needed)."""
        qr = NAPCAT_QR
        try:
            if qr.exists() and (time.time() - qr.stat().st_mtime) < 300:
                body = qr.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        except Exception:
            pass
        self.send_response(404)
        self.end_headers()

    # ---------- routing (shared with daemon _Handler via inheritance) ----------
    def _serve_under(self, route_prefix: str, base_dir) -> None:
        from urllib.parse import unquote

        p = self.path.split("?", 1)[0]
        if not p.startswith(route_prefix):
            self._send_json(404, {"error": "未找到"})
            return
        rel = unquote(p[len(route_prefix):]).lstrip("/")
        target = (base_dir / rel).resolve()
        try:
            if not str(target).startswith(str(base_dir.resolve())) or \
                    not target.is_file():
                self._send_json(404, {"error": "未找到"})
                return
        except Exception:
            self._send_json(404, {"error": "未找到"})
            return
        ext = target.suffix.lower()
        ctype = ("image/png" if ext == ".png"
                 else "application/json" if ext == ".json"
                 else "image/webp" if ext == ".webp"
                 else "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _tap(self, body: dict) -> dict:
        """Pet tap/greet: Yuanheng answers a short impromptu line."""
        speak = str(body.get("speak", "0")) not in ("0", "false", "off")
        text = ("（有人轻轻碰了你一下）用一两句自然、有你自己味道的话回应，"
                "别太长的总结，说点什么心里话。")
        try:
            info = self.runtime.console_turn_stream(
                text, lambda _c: None)
            answer = str(info.get("answer", "") or "").strip()
        except Exception as exc:  # noqa: BLE001
            answer = ""
            return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        if speak and answer:
            st = _settings_load()
            try:
                import threading as _th

                _th.Thread(target=self._speak,
                           args=(answer, st.get("tts_speaker", "Vivian")),
                           daemon=True).start()
            except Exception:
                pass
        _log("tap", answer[:60])
        return {"ok": True, "answer": answer}

    def console_do_GET(self):
        p = self.path.split("?", 1)[0]
        if p == "/talk_result":
            # 段5（0635）：断连后按 request_id **取结果**（不重放副作用）
            import urllib.parse as _up

            rid = (_up.parse_qs(_up.urlparse(self.path).query).get("request_id") or [""])[0]
            from backend import talk_results as _tr

            r = _tr.load(rid)
            if r is None:
                self._send_json(404, {"ok": False, "error": "unknown request_id",
                                      "request_id": rid})
            else:
                self._send_json(200, {"ok": True, "request_id": rid, **r})
            return
        if p.startswith("/live2d/"):
            self._serve_under("/live2d/", VENDOR_DIR)
            return
        if p.startswith("/live2d-models/"):
            self._serve_under("/live2d-models/", MODEL_DIR)
            return
        if p in ("/", "/index.html"):
            self._serve_file("index.html")
        elif p == "/avatar.html":
            self._serve_file("avatar.html")
        elif p == "/chat_popup.html":
            self._serve_file("chat_popup.html")
        elif p == "/avatar.js":
            self._serve_file("avatar.js")
        elif p == "/favicon.png":
            self._serve_file("favicon.png")
        elif p == "/qq-qrcode":
            self._qq_qrcode()
        elif p == "/loading.webp":
            self._serve_file("loading.webp")
        elif p == "/console.css":
            self._serve_file("console.css")
        elif p == "/console.js":
            self._serve_file("console.js")
        elif p == "/state":
            self._send_json(200, self._state())
        elif p == "/history":
            self._send_json(200, self._history())
        elif p == "/monitor":
            self._send_json(200, self._monitor())
        elif p == "/ledger":
            self._send_json(200, self._ledger())
        elif p == "/growth":
            try:
                from backend import growth_log

                self._send_json(200, {"items": growth_log.recent(30)})
            except Exception as exc:
                self._send_json(200, {"items": [], "error": type(exc).__name__})
        elif p == "/mem":
            self._send_json(200, self._mem())
        elif p == "/sessions":
            self._send_json(200, self._sessions())
        elif p == "/avatar-models":
            self._send_json(200, self._avatar_models())
        elif p == "/emotion":
            from urllib.parse import parse_qs, urlparse

            q = (parse_qs(urlparse(self.path).query).get("text", [""])[0]).strip()
            try:
                from backend.emotion_classifier import classify_emotion

                self._send_json(200, {"ok": True,
                                      "emotion": classify_emotion(q)})
            except Exception as exc:
                self._send_json(200, {"ok": False,
                                      "error": type(exc).__name__})
        elif p == "/logs":
            self._send_json(200, {"ok": True, "logs": list(_LOG_RING)})
        elif p == "/settings":
            self._send_json(200, {"ok": True, "settings": _settings_load()})
        elif p == "/devmode":
            self._send_json(200, {"ok": True, **devmode_state()})
        elif p == "/devices":
            self._send_json(200, {"ok": True, "devices": _audio_devices()})
        elif p == "/sing/status":
            self._send_json(200, sing_status())
        elif p == "/songs":
            from backend import song_library

            self._send_json(200, {"ok": True,
                                  "items": song_library.list_songs()})
        elif p == "/songs/audio":
            from urllib.parse import parse_qs, urlparse

            from backend import song_library

            sid = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            f = song_library.song_path(sid)
            if f is None:
                self._send_json(404, {"error": "歌曲不存在"})
            else:
                data = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
        elif p == "/sing/result":
            # final product is the 3-stem mix (fallback: raw SVC output)
            gen = SING_DIR / "out" / "mixed.wav"
            if not gen.is_file():
                gen = SING_DIR / "out" / "generated.wav"
            if not gen.is_file():
                self._send_json(404, {"error": "还没有翻唱结果"})
            else:
                data = gen.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
        elif p == "/official-ui/status":
            # 启动入口（0792）：翻唱链路官方 UI 状态（含外部实例的自动收尾）
            from backend import official_ui

            try:
                self._send_json(200, official_ui.status())
            except Exception as exc:  # noqa: BLE001
                self._send_json(200, {"ok": False,
                                      "error": type(exc).__name__})
        else:
            self._send_json(404, {"error": "未找到"})

    def do_GET(self):
        self.console_do_GET()

    def console_do_POST(self):
        p = self.path.split("?", 1)[0]
        if p == "/talk":
            from backend import gpu_lock

            if not gpu_lock.chat_enter():
                self._send_json(409, {"ok": False, "busy": True,
                                      "error": "元亨正在唱歌（GPU 互锁），"
                                               "唱完再聊~"})
                return
            try:
                self._do_talk()
            finally:
                gpu_lock.chat_exit()
            return
        if p == "/tap":
            from backend import gpu_lock

            if not gpu_lock.chat_enter():
                self._send_json(409, {"ok": False, "busy": True,
                                      "error": "元亨正在唱歌（GPU 互锁）"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                gpu_lock.chat_exit()
                self._send_json(400, {"error": "请求格式错误"})
                return
            try:
                self._send_json(200, self._tap(body))
            finally:
                gpu_lock.chat_exit()
            return
        if p == "/voice":
            from backend import gpu_lock

            if not gpu_lock.chat_enter():
                self._send_json(409, {"ok": False, "busy": True,
                                      "error": "元亨正在唱歌（GPU 互锁），"
                                               "唱完再聊~"})
                return
            try:
                self._do_voice()
            finally:
                gpu_lock.chat_exit()
            return
        if p == "/reset":
            self._do_reset()
            return
        if p == "/settings":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._send_json(400, {"error": "请求格式错误"})
                return
            self._send_json(200, {"ok": True,
                                  "settings": _settings_save(body)})
            return
        if p == "/devmode":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._send_json(400, {"error": "请求格式错误"})
                return
            self._send_json(200, devmode_set(bool(body.get("qq_silent"))))
            return
        if p == "/control":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._send_json(400, {"error": "请求格式错误"})
                return
            self._send_json(200, self._control(body))
            return
        if p == "/tts":
            from backend import gpu_lock

            if not gpu_lock.chat_enter():
                self._send_json(409, {"ok": False, "busy": True,
                                      "error": "元亨正在唱歌（GPU 互锁）"})
                return
            try:
                self._do_tts()
            finally:
                gpu_lock.chat_exit()
            return
        if p == "/sing":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._send_json(400, {"error": "请求格式错误"})
                return
            self._send_json(200, sing_start(str(body.get("target", "")),
                                            str(body.get("prompt", "")),
                                            str(body.get("voice", "bright"))))
            return
        if p == "/sing/upload":
            from urllib.parse import parse_qs, urlparse

            name = (parse_qs(urlparse(self.path).query).get("name", [""])[0]
                    or "upload.wav")
            safe = "".join(c for c in Path(name).name
                           if c.isalnum() or c in "._-")
            if not safe:
                safe = "upload.wav"
            up = SING_DIR / "uploads"
            up.mkdir(parents=True, exist_ok=True)
            dst = up / safe
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = self.rfile.read(length) if length > 0 else b""
                if len(data) < 100:
                    raise ValueError("empty upload")
                dst.write_bytes(data)
            except Exception as exc:  # noqa: BLE001
                self._send_json(400, {"ok": False,
                                      "error": type(exc).__name__})
                return
            self._send_json(200, {"ok": True, "path": str(dst)})
            return
        if p in ("/songs/play", "/songs/send"):
            from backend import gpu_lock, song_library

            if not gpu_lock.chat_enter():
                self._send_json(409, {"ok": False, "busy": True,
                                      "error": "元亨正在唱歌（GPU 互锁）"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                gpu_lock.chat_exit()
                self._send_json(400, {"error": "请求格式错误"})
                return
            try:
                sid = str(body.get("id", "")).strip()
                msg = (song_library.play(sid) if p.endswith("play")
                       else song_library.send_qq(sid))
                self._send_json(200, {"ok": True, "message": msg})
            finally:
                gpu_lock.chat_exit()
            return
        if p == "/session":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._send_json(400, {"error": "请求格式错误"})
                return
            self._send_json(200, self._session_load(body))
            return
        self._send_json(404, {"error": "未找到"})

    def do_POST(self):
        self.console_do_POST()

    def _do_tts(self):
        """A4b (ledger 0454): synthesize one line -> WAV bytes.

        Lets the QQ bridge use the Edge-clone voice without loading torch in
        its own process. Body: {"text", "speaker"?, "model"?: "clone"|"0.6B"}.
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send_json(400, {"error": "请求格式错误"})
            return
        text = str(body.get("text", "")).strip()[:200]
        if not text:
            self._send_json(400, {"error": "text 为空"})
            return
        st = _settings_load()
        model = str(body.get("model") or st.get("tts_model", "clone"))
        speaker = str(body.get("speaker") or st.get("tts_speaker", "Vivian"))
        try:
            audio, sr = _synth(model, text, speaker)
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": type(exc).__name__})
            return
        data = _wav_bytes(audio, sr)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _do_reset(self):
        """Clear the console conversation (new chat)."""
        try:
            s = self.runtime._session("console")
            s.history = []
            try:
                s.memory._turns = []
            except Exception:
                pass
            s.save_session("console")
            _log("reset", "新对话")
            self._send_json(200, {"ok": True})
        except Exception as exc:
            self._send_json(500, {"ok": False,
                                  "error": f"{type(exc).__name__}: {str(exc)[:120]}"})

    def _monitor(self) -> dict:
        out = {"ok": True, "now": time.time()}
        try:
            import psutil
            import subprocess

            out["cpu"] = psutil.cpu_percent(interval=None)
            vm = psutil.virtual_memory()
            out["ram"] = {"used_gb": round(vm.used / 1e9, 2),
                          "total_gb": round(vm.total / 1e9, 2)}
            du = psutil.disk_usage(str(_PROJECT_ROOT))
            out["disk"] = {"used_gb": round(du.used / 1e9, 1),
                           "total_gb": round(du.total / 1e9, 1)}
            try:
                g = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,"
                                    "memory.total",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=8)
                parts = g.stdout.strip().split(",")
                if len(parts) == 3:
                    out["gpu"] = {"util": float(parts[0]),
                                  "used_gb": round(float(parts[1]) / 1024, 1),
                                  "total_gb": round(float(parts[2]) / 1024, 1)}
            except Exception:
                out["gpu"] = None
            out["services"] = self._state()
            out["procs"] = len(psutil.pids())
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
        return out

    def _listen_wav(self, path, on_segment=None, on_chunk=None) -> dict:
        """Test-only: feed a wav file as if it were live mic audio (16k mono)."""
        import subprocess
        import tempfile
        import wave

        import numpy as np

        try:
            import imageio_ffmpeg

            exe = imageio_ffmpeg.get_ffmpeg_exe()
            out = Path(tempfile.mkdtemp()) / "a16.wav"
            subprocess.run([exe, "-y", "-i", str(path), "-ac", "1", "-ar",
                            "16000", str(out)], capture_output=True)
            with wave.open(str(out), "rb") as w:
                audio = np.frombuffer(w.readframes(w.getnframes()),
                                      dtype="<i2").astype("float32") / 32768.0
        except Exception:
            return {"started": False, "audio": None}
        for i in range(0, len(audio), 1600):
            if on_chunk is not None:
                try:
                    on_chunk(audio[i:i + 1600])
                except Exception:
                    pass
        if on_segment is not None and len(audio) > 0:
            try:
                on_segment(audio)
            except Exception:
                pass
        return {"started": True, "audio": audio}

    def _do_voice(self):
        """One voice turn over SSE: listen(gated 3s) -> SenseVoice -> LLM
        stream -> TTS speak. {text} present => mock mode (skip mic, use text)."""
        from backend.voice_trace import VoiceTrace

        vt = None
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send_json(400, {"error": "请求格式错误"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        import threading

        alive = {"ok": True}
        _emit_lock = threading.Lock()

        def emit(data: dict) -> None:
            if not alive["ok"]:
                return
            with _emit_lock:
                try:
                    self.wfile.write(_sse(data))
                    self.wfile.flush()
                except Exception:
                    alive["ok"] = False  # client gone -> stop the loop

        import time as _t

        try:
            st = _settings_load()
            mock_text = str(body.get("text", "") or "").strip()
            continuous = str(body.get("continuous", "")).lower() in (
                "1", "true", "yes", "on")
            _log("voice", ("mock:" + mock_text) if mock_text
                 else ("continuous" if continuous else "listen"))
            speak_default = "1" if st.get("tts_speak", True) else "0"
            speak = str(body.get("speak", speak_default)) not in ("0", "false", "off")
            if mock_text:
                emit({"type": "state", "value": "thinking"})
                info = self.runtime.console_turn_stream(
                    mock_text, lambda c: emit({"type": "delta", "delta": c}))
                answer = str(info.get("answer", ""))
                emit({"type": "turn_done", "text": answer,
                      "tool_uses": len(info.get("tool_uses") or [])})
                if speak and answer.strip():
                    emit({"type": "state", "value": "speaking"})
                    self._speak(answer, st.get("tts_speaker", "Vivian"),
                                st.get("tts_model", "0.6B"))
                emit({"type": "state", "value": "idle"})
                emit({"type": "voice_done", "status": "ok"})
                return
            from tools.tts_test_start import _get_sv, release_sv

            rounds = 0
            idle = 0
            while alive["ok"] and rounds < (999 if continuous else 4):
                rounds += 1
                vt = VoiceTrace(session_id="console", turn_id=rounds)
                vt.mark("capture_start")
                capture_seen = {"speech_start": False}

                def _mark_speech_start(*_args):
                    if not capture_seen["speech_start"]:
                        capture_seen["speech_start"] = True
                        vt.mark("speech_start")
                emit({"type": "state", "value": "listening"})
                # streaming recognition worker: transcribe each segment as it
                # closes, accumulate text, and speculatively prefetch memory
                # while the user is still speaking (ledger 0226)
                import queue as _queue
                import threading as _th

                seg_q: "_queue.Queue" = _queue.Queue()
                _stop = object()
                parts: list[str] = []
                pre: list[str] = []

                # V3: streaming ASR for live partial (sherpa zh-en), fed by chunks
                _sherpa = _get_sherpa()
                _log("voice_sherpa", "ok" if _sherpa is not None else "none")
                sherpa_q: "_queue.Queue" = _queue.Queue()
                if _sherpa is not None:
                    _sid = f"cap{rounds}"  # unique per round (avoid open conflict)

                    def _sherpa_worker():
                        from backend.target_chain import CancellationSignal

                        sig = CancellationSignal()
                        try:
                            _sherpa.open_stream(_sid, 1, 16000, 1, sig)
                            _log("voice_sherpa", "stream ready")
                        except Exception as e:  # noqa: BLE001
                            _log("voice_sherpa", "open fail " + type(e).__name__)
                            return
                        last = ""
                        while True:
                            it = sherpa_q.get()
                            if it is _stop:
                                break
                            try:
                                for u in _sherpa.push_audio(_sid, it, 16000, sig):
                                    t = str(getattr(u, "text", "") or "")
                                    if t and t != last:
                                        last = t
                                        vt.mark("first_partial", t[:60])
                                        emit({"type": "partial", "text": t})
                                        _log("voice_partial", t[:30])
                            except Exception:
                                pass
                        try:
                            _sherpa.finish_stream(_sid, sig)
                        except Exception:
                            pass

                    _th.Thread(target=_sherpa_worker, daemon=True).start()

                def _worker():
                    import re as _re2

                    try:
                        sv = _get_sv()
                    except Exception:
                        sv = None
                    acc = ""
                    last_pre = 0.0
                    while True:
                        item = seg_q.get()
                        if item is _stop:
                            break
                        if sv is None:
                            continue
                        try:
                            res = sv.generate(input=item, language="zh",
                                              use_itn=True, batch_size_s=60)
                            raw = str((res[0] or {}).get("text") or "")
                            t = _re2.sub(r"<\|[^|]+\|>", "", raw).strip()
                        except Exception:
                            t = ""
                        if t:
                            parts.append(t)
                            acc = "".join(parts)
                            if _sherpa is None:  # fallback: segment-based partial
                                vt.mark("first_partial", acc[:60])
                                emit({"type": "partial", "text": acc})
                            if len(acc) >= 6 and time.time() - last_pre > 2.0:
                                last_pre = time.time()
                                try:
                                    s = self.runtime._session("console")
                                    pre[:] = [str(h.get("summary", ""))[:150]
                                              for h in s.memory.contextual_recall(
                                                  acc, limit=3)]
                                except Exception:
                                    pass

                wt = _th.Thread(target=_worker, daemon=True)
                wt.start()
                def _on_chunk(chunk):
                    # WAV replay has no VAD callback; first delivered frame is
                    # the best available speech-start mark for that path.
                    _mark_speech_start()
                    if _sherpa is not None:
                        sherpa_q.put(chunk)

                r = self._listen(body, st, on_segment=seg_q.put,
                                 on_chunk=_on_chunk,
                                 on_level=lambda _level, is_speech:
                                 _mark_speech_start() if is_speech else None)
                vt.mark("speech_end")
                seg_q.put(_stop)
                sherpa_q.put(_stop)
                wt.join(timeout=8)
                if not r.get("started"):
                    if continuous:
                        idle += 1
                        if idle >= 3 or not alive["ok"]:
                            break
                        continue
                    if rounds == 1:
                        emit({"type": "state", "value": "idle"})
                        emit({"type": "voice_done", "status": "no-speech"})
                        return
                    break
                idle = 0
                text = "".join(parts).strip()
                vt.mark("asr_final", text[:60])
                if not text:
                    # fallback: whole-segment transcribe (worker produced none)
                    emit({"type": "state", "value": "asr"})
                    try:
                        sv = _get_sv()
                        res = sv.generate(input=r["audio"], language="zh",
                                          use_itn=True, batch_size_s=60)
                        raw = str((res[0] or {}).get("text") or "") if res else ""
                        import re as _re3

                        text = _re3.sub(r"<\|[^|]+\|>", "", raw).strip()
                    except Exception:
                        text = ""
                release_sv()
                emit({"type": "voice_text", "kind": "user", "text": text})
                if not text:
                    break
                emit({"type": "state", "value": "thinking"})
                _spk = None
                _spoke = {"on": False}
                if speak:
                    try:
                        _spk = _StreamingSpeaker(
                            st.get("tts_speaker", "Vivian"),
                            int(st.get("device", 1) or 1),
                            st.get("tts_model", "0.6B"),
                            should_stop=lambda: _tc.cancelled("console"),
                            on_trace=vt.mark)
                        _spk.start()
                    except Exception:
                        _spk = None
                _buf = {"t": ""}

                def _on_delta(c, _b=_buf, _s=_spk, _sp=_spoke, _vt=vt):
                    if not _sp["on"]:
                        _sp["on"] = True
                        _vt.mark("llm_first_delta")
                    emit({"type": "delta", "delta": c})
                    if _s is None:
                        return
                    if not _sp["on"]:
                        _sp["on"] = True
                        emit({"type": "state", "value": "speaking"})
                    _b["t"] += c
                    while True:
                        sent, rest = self._pop_sentence(_b["t"])
                        if not sent:
                            break
                        _vt.mark("sentence_ready", sent[:30])
                        _s.feed(sent)
                        _b["t"] = rest

                vt.mark("llm_start")
                info = self.runtime.console_turn_stream(
                    text, _on_delta, pre_recall=pre or None)
                answer = str(info.get("answer", ""))
                vt.mark("turn_done", answer[:60])
                emit({"type": "turn_done", "text": answer,
                      "tool_uses": len(info.get("tool_uses") or [])})
                if _spk is not None:
                    if _buf["t"].strip():
                        _spk.feed(_buf["t"])
                        _buf["t"] = ""
                    rr = _spk.finish()
                    if rr in ("interrupted", "cancelled"):
                        emit({"type": "interrupted"})
                        try:
                            vt.flush()
                        except Exception:
                            pass
                        if rr == "cancelled":
                            break
                        continue  # back to listening (barge-in)
                try:
                    vt.flush()
                except Exception:
                    pass
                if not continuous:
                    break
                # continuous: keep listening for the next turn
            emit({"type": "state", "value": "idle"})
            emit({"type": "voice_done", "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            vt.mark("turn_done", f"error:{type(exc).__name__}")
            import traceback

            _log("voice_error", f"{type(exc).__name__}: {str(exc)[:160]}")
            try:
                _d = _PROJECT_ROOT / "cache" / "tmp"
                _d.mkdir(parents=True, exist_ok=True)
                with (_d / "voice_error.log").open("a", encoding="utf-8") as f:
                    f.write(f"\n=== {time.strftime('%H:%M:%S')} ===\n")
                    f.write(traceback.format_exc())
            except Exception:
                pass
            emit({"type": "error", "message": f"{type(exc).__name__}: "
                                              f"{str(exc)[:200]}"})
            emit({"type": "state", "value": "idle"})
        finally:
            try:
                if vt is not None:
                    vt.flush()
            except Exception:
                pass

    # ---------- voice helpers ----------
    def _control(self, body: dict) -> dict:
        action = str(body.get("action", ""))
        if action == "release_vram":
            try:
                from tools.tts_test_start import release_sv

                release_sv()
                import gc
                import torch

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                _log("control", "release_vram")
                return {"ok": True, "note": "ASR/TTS cuda 已释放"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}"}
        if action == "reload_settings":
            return {"ok": True, "settings": _settings_load()}
        if action in ("drives_add", "drives_reinforce", "drives_fade"):
            try:
                from backend import intrinsic_drives

                if action == "drives_add":
                    name = str(body.get("name", "")).strip()
                    if not name:
                        return {"ok": False, "error": "name required"}
                    intrinsic_drives.add(
                        name, str(body.get("category", "其他") or "其他"),
                        float(body.get("strength", 0.6) or 0.6),
                        evidence="老爹在工作台添加", channel="老爹")
                elif action == "drives_reinforce":
                    intrinsic_drives.reinforce(str(body.get("id", "")))
                else:
                    # 淡出（软，不删除）
                    ds = intrinsic_drives.load()
                    for d in ds:
                        if d.get("id") == str(body.get("id", "")):
                            d["status"] = "faded"
                    intrinsic_drives.save(ds)
                _log("control", action)
                return {"ok": True, "drives": _drives_list()}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        if action in ("napcat_login", "qq_switch"):
            try:
                from backend.napcat_launcher import launch_napcat

                uin = str(body.get("uin", "") or BOT_UIN)
                if action == "napcat_login" and _napcat_procs_alive():
                    return {"ok": True, "note": "QQ/NapCat 已运行，请在现有登录窗口或 NapCat 面板继续登录"}
                if action == "qq_switch":
                    from tools.qq_bridge_control import stop_napcat

                    stopped = stop_napcat(_PROJECT_ROOT / "cache" / "qq_bridge" / "lite")
                    if not stopped.get("stopped"):
                        return {"ok": False, "error": "旧 NapCat 尚未退出，未启动第二个实例"}
                res = launch_napcat(uin)
                _log("control", f"napcat_login {uin}")
                _tag = "（元亨号）" if uin == BOT_UIN else "（老爹主号，导出用）"
                note = str(res.get("note") or "已唤起 NapCat")
                return {"ok": True, "note": f"{note}{_tag}"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        if action in ("qq_bridge_start", "qq_bridge_restart", "qq_bridge_stop"):
            # 工作台一键控制 QQ 桥 Lite（2026-10-09）：走官方 control 脚本。
            try:
                import subprocess as _sp

                py = _PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
                control = _PROJECT_ROOT / "tools" / "qq_bridge_control.py"
                cfg = _PROJECT_ROOT / "config" / "qq_bridge_lite.json"
                if not control.exists():
                    return {"ok": False, "error": "找不到 qq_bridge_control.py"}
                sub = {"qq_bridge_start": "start",
                       "qq_bridge_restart": "restart",
                       "qq_bridge_stop": "stop"}[action]
                cmd = [str(py if py.exists() else sys.executable), "-B",
                       str(control), sub, "--profile", "lite",
                       "--config", str(cfg)]
                if sub in ("stop", "restart"):
                    cmd.append("--no-napcat")   # 停桥不动 QQ 登录
                flags = getattr(_sp, "CREATE_NO_WINDOW", 0)
                _sp.Popen(cmd, cwd=str(_PROJECT_ROOT), close_fds=True,
                          creationflags=flags,
                          stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                _log("control", action)
                note = {
                    "start": "QQ 桥启动中（约 10~30 秒），稍后看“桥接/状态”刷新",
                    "restart": "QQ 桥重启中（约 10~30 秒），NapCat 登录保持不动",
                    "stop": "QQ 桥停止请求已下发（NapCat 保持登录）",
                }[sub]
                return {"ok": True, "note": note}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False,
                        "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        if action == "launch_pet":
            try:
                import subprocess

                desktop = _PROJECT_ROOT / "desktop"
                exe = desktop / "node_modules" / ".bin" / "electron.cmd"
                if not exe.exists():
                    return {"ok": False, "error": "未找到 electron（desktop/node_modules）"}
                subprocess.Popen(["cmd", "/c", str(exe), "."],
                                 cwd=str(desktop), close_fds=True)
                _log("control", "launch_pet")
                return {"ok": True, "note": "已启动桌宠"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        if action == "launch_all":
            try:
                import subprocess

                bat = _PROJECT_ROOT / "YHLZ_全家桶.bat"
                if not bat.exists():
                    return {"ok": False, "error": "找不到 YHLZ_全家桶.bat"}
                subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(_PROJECT_ROOT),
                                 close_fds=True)
                _log("control", "launch_all")
                return {"ok": True, "note": "已启动全家桶"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        if action in ("official_ui_start", "official_ui_stop"):
            # 2026-10-21（台账 0935）：旧 SoulX 官方 UI 退出生产，仅保留 stop。
            if action == "official_ui_start":
                return {"ok": False,
                        "error": "旧 SoulX 链路已退出生产；请用工作台「开始翻唱」"
                                 "（Seed-VC 44k + 柔化 e）"}
            try:
                from backend import official_ui

                out = official_ui.stop(reason="workbench")
                _log("control", action)
                return out
            except Exception as exc:  # noqa: BLE001
                return {"ok": False,
                        "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        if action == "napcat_ui":
            # 启动入口（0792）：NapCat 管理面板（6099）。
            # 已在跑 → 直接给地址；没在跑 → 拉起（自动登录）并提示稍后打开。
            try:
                import subprocess as _sp

                port, url = _napcat_webui()
                if _tcp_open("127.0.0.1", port):
                    _log("control", "napcat_ui open")
                    return {"ok": True, "up": True, "url": url,
                            "note": "NapCat 面板在线（若提示登录，token 见 "
                                    "qqwatch\\shell\\config\\webui.json）"}
                if _napcat_procs_alive():
                    return {"ok": True, "up": False, "url": url,
                            "note": "NapCat 进程在，但面板未就绪：稍候再点；"
                                    "仍不行可用「唤起登录」重启"}
                from backend.napcat_launcher import launch_napcat

                launch_napcat(BOT_UIN)
                _log("control", "napcat_ui start")
                return {"ok": True, "up": False, "url": url,
                        "note": "NapCat 未运行 → 已拉起（自动登录中）；"
                                "约 1 分钟后点此按钮打开面板"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False,
                        "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        if action == "cancel_turn":
            try:
                from backend import turn_control

                turn_control.request(str(body.get("channel", "console")))
                _log("control", "cancel_turn")
                return {"ok": True, "note": "已请求停止"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}"}
        return {"ok": False, "error": "未知操作：" + action}

    def _listen(self, body, st: dict, on_segment=None, on_chunk=None,
                on_level=None) -> dict:
        from tools.tts_test_start import _capture_loop

        # offline test path: feed a wav file instead of the mic
        wav = str(body.get("wav", "") or "")
        if wav and Path(wav).exists():
            return self._listen_wav(wav, on_segment, on_chunk)

        device = int(body.get("device", st.get("device", 1)))
        dur = float(body.get("duration", st.get("duration", 60.0)))
        denoise = str(body.get("denoise", st.get("denoise", "rnnoise")))
        emit = self._emit_level

        def _on_level(level, is_speech):
            try:
                emit(level, is_speech)
            except Exception:
                pass
            if on_level is not None:
                try:
                    on_level(level, is_speech)
                except Exception:
                    pass

        return _capture_loop(device, 1.0, dur, denoise, None, False, False,
                             on_level=_on_level, on_segment=on_segment,
                             on_chunk=on_chunk)

    def _emit_level(self, level, is_speech):
        self.wfile.write(_sse({"type": "level", "value": round(float(level), 4),
                               "speech": bool(is_speech)}))
        self.wfile.flush()

    @staticmethod
    def _sentences(text: str, maxlen: int = 60) -> list[str]:
        import re as _re

        t = str(text or "").strip()
        if not t:
            return []
        parts = [p for p in _re.split(r"(?<=[。！？!?；;…])", t) if p.strip()]
        out, cur = [], ""
        for p in parts:
            if len(cur) + len(p) <= maxlen:
                cur += p
            else:
                if cur:
                    out.append(cur)
                cur = p if len(p) <= maxlen else p[:maxlen]
        if cur:
            out.append(cur)
        return out[:6] or [t[:maxlen]]

    @staticmethod
    def _pop_sentence(buf: str, maxlen: int = 48) -> tuple[str, str]:
        """Pop one speakable sentence from the head of `buf` for streaming TTS.
        Returns ('', buf) while no complete sentence is ready yet."""
        t = str(buf or "")
        for i, ch in enumerate(t):
            if ch in "。！？!?…\n":
                return t[:i + 1].strip(), t[i + 1:]
        if len(t) >= maxlen:
            cut = max([t.rfind(ch, 0, maxlen) for ch in "，,、;； "] or [-1])
            if cut > 8:
                return t[:cut + 1].strip(), t[cut + 1:]
            return t[:maxlen].strip(), t[maxlen:]
        return "", t

    def _speak_interruptible(self, text: str, speaker: str = "Vivian",
                             device: int = 1, model_key: str = "0.6B",
                             should_stop=None) -> str:
        """Sentence-by-sentence resident TTS with barge-in (echo-masked).
        First sentence is synthesized+played immediately (faster first sound);
        if the user speaks over it, stop and return 'interrupted'."""
        import numpy as np
        import sounddevice as sd

        try:
            _get_engine(model_key)
        except Exception:
            return "done"
        chunks = self._sentences(text)
        try:
            with sd.InputStream(device=int(device), samplerate=16000,
                                channels=1, dtype="float32",
                                blocksize=1600, latency="low") as inp:
                for chunk in chunks:
                    try:
                        audio, sr = _synth(model_key, chunk, speaker)
                        samples = np.asarray(audio, dtype="float32")
                    except Exception:
                        continue
                    play_rms = float(np.sqrt(np.mean(samples * samples)) + 1e-9)
                    thr = max(0.05, play_rms * 1.5)
                    sd.play(samples, int(sr))
                    dur = len(samples) / float(sr)
                    t0 = time.time()
                    hot = 0
                    while time.time() - t0 < dur + 0.3:
                        if should_stop is not None and should_stop():
                            sd.stop()
                            _log("voice", "tts cancelled")
                            return "cancelled"
                        data, _ = inp.read(1600)
                        mono = np.asarray(
                            data[:, 0] if data.ndim > 1 else data,
                            dtype="float32")
                        rms = float(np.sqrt(np.mean(mono * mono)) + 1e-9)
                        if rms > thr:
                            hot += 1
                            if hot >= 2:
                                sd.stop()
                                _log("voice", f"tts interrupted (rms={rms:.3f} "
                                              f"thr={thr:.3f})")
                                return "interrupted"
                        else:
                            hot = 0
        except Exception:
            pass
        try:
            sd.stop()
        except Exception:
            pass
        _log("voice", "tts done")
        return "done"

    def _speak(self, text: str, speaker: str = "Vivian",
               model_key: str = "0.6B") -> None:
        import numpy as np
        import sounddevice as sd

        try:
            _get_engine(model_key)
        except Exception:
            return
        for chunk in self._sentences(text):
            try:
                audio, sr = _synth(model_key, chunk, speaker)
                sd.play(np.asarray(audio, dtype="float32"), int(sr))
                sd.wait()
            except Exception:
                continue

    # ---------- logic ----------
    def _history(self) -> dict:
        """Console session dialogue history (persisted per turn in cache/sessions/
        console.json) so a page refresh restores the conversation."""
        try:
            s = self.runtime._session("console")
            msgs = [
                {"role": m.get("role"), "content": str(m.get("content", ""))}
                for m in (s.history or [])
            ]
            return {"ok": True, "messages": msgs}
        except Exception as exc:
            return {"ok": False, "messages": [],
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    def _sessions(self) -> dict:
        from backend.target_entry import ConversationSession

        try:
            rows = ConversationSession.recent_sessions(14)
            return {"ok": True, "items": rows}
        except Exception as exc:
            return {"ok": False, "items": [],
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    def _session_load(self, body: dict) -> dict:
        name = str(body.get("name", "")).strip()
        if not name or "/" in name or "\\" in name:
            return {"ok": False, "error": "bad name"}
        try:
            s = self.runtime._session("console")
            # archive current console first if it has content
            if s.history:
                try:
                    import time as _t

                    s.save_session(f"archive_{int(_t.time())}")
                except Exception:
                    pass
            n = s.load_session(name)
            s.save_session("console")
            _log("session", "load " + name)
            return {"ok": True, "loaded": name, "messages": n}
        except Exception as exc:
            return {"ok": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    def _avatar_models(self) -> dict:
        items = []
        try:
            for p in sorted(MODEL_DIR.rglob("*.model3.json")):
                rel = p.relative_to(MODEL_DIR).as_posix()
                name = p.parent.name
                items.append({"name": name, "rel": rel})
        except Exception as exc:
            return {"ok": False, "items": [],
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        return {"ok": True, "items": items}

    def _ledger(self) -> dict:
        from urllib.parse import parse_qs, urlparse

        q = (parse_qs(urlparse(self.path).query).get("q", [""])[0]).strip()
        if not q or not LEDGER_FILE.exists():
            return {"ok": bool(q), "query": q, "items": []}
        import re

        lines = LEDGER_FILE.read_text(encoding="utf-8").splitlines()
        recs: list[tuple[str, list[str]]] = []
        cur: list[str] | None = None
        title = ""
        for ln in lines:
            m = re.match(r"^## 记录 (\d+)[:：]?\s*(.*)", ln)
            if m:
                if cur is not None:
                    recs.append((title, cur))
                title = f"记录 {m.group(1)}：{m.group(2).strip()}"
                cur = []
            elif cur is not None:
                cur.append(ln)
        if cur is not None:
            recs.append((title, cur))
        low = q.lower()
        out = []
        for title, body in recs:
            hit = low in title.lower() or any(low in b.lower() for b in body[:60])
            if not hit:
                continue
            first = next((b.strip()[:150] for b in body
                          if low in b.lower() and b.strip()), body[0].strip()[:150]
                         if body else "")
            out.append({"id": title, "text": first})
            if len(out) >= 10:
                break
        out.reverse()  # newest first
        return {"ok": True, "query": q, "items": out}

    def _mem(self) -> dict:
        from urllib.parse import parse_qs, urlparse

        q = (parse_qs(urlparse(self.path).query).get("q", [""])[0]).strip()
        limit = int(parse_qs(urlparse(self.path).query).get("limit", ["8"])[0])
        if not q:
            return {"ok": True, "query": q, "items": []}
        try:
            s = self.runtime._session("console")
            hits = s.memory.recall(q, limit=min(limit, 20))
            items = [{"id": h.get("id"), "type": h.get("type"),
                      "importance": h.get("importance"),
                      "status": h.get("status"),
                      "summary": str(h.get("summary", ""))[:180]}
                     for h in (hits or [])]
            return {"ok": True, "query": q, "items": items}
        except Exception as exc:
            return {"ok": False, "query": q,
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    def _state(self) -> dict:
        out = {"ok": True, "now": time.time()}
        try:
            # 启动入口（0792）：官方 UI 若被外部停掉，这里顺手收尾（释放互锁）
            try:
                from backend import official_ui

                official_ui.reap()
            except Exception:
                pass
            import urllib.request

            try:
                g = json.loads(urllib.request.urlopen(
                    "http://127.0.0.1:8081/health", timeout=3).read())
                out["gemma"] = "ok" if g.get("status") == "ok" else "down"
            except Exception:
                out["gemma"] = "down"
            out["daemon"] = "ok"
            out["ollama"] = _ollama_state()
            out["qq"] = _qq_status()
            try:
                # 0831：工作台显示的也是唯一任务库（Lite job store），
                # 不再读旧的 cache/dev/state.json。
                from backend.target_dev_bridge import dev_status

                out["dev"] = dev_status()
            except Exception:
                out["dev"] = {"status": "idle", "task": ""}
            out["drives"] = _drives_list()
            st = self.runtime.health() if hasattr(self.runtime, "health") else None
            out["turns"] = 0
            if st:
                try:
                    counts = {k: v for k, v in (st.get("turns") or {}).items()}
                    out["turns"] = counts
                except Exception:
                    pass
            try:
                s = self.runtime._session("console")
                out["history"] = len(s.history) // 2
                out["l2"] = s.memory.health().get("l2_items", 0)
            except Exception:
                pass
        except Exception:
            out["daemon"] = "down"
        return out

    def _do_talk(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            text = str(body.get("text", "")).strip()
            request_id = str(body.get("request_id", "") or "")
        except Exception:
            self._send_json(400, {"error": "请求格式错误"})
            return
        if not text:
            self._send_json(400, {"error": "empty text"})
            return
        if not request_id:  # 段5（0635）：客户端未带则服务端生成，供断连后取结果
            import uuid as _uuid
            request_id = _uuid.uuid4().hex[:16]
        _log("talk", text[:80])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(_sse({"type": "state", "value": "thinking",
                                   "request_id": request_id}))
            self.wfile.flush()

            def on_delta(chunk: str) -> None:
                try:
                    self.wfile.write(_sse({"type": "delta", "delta": chunk}))
                    self.wfile.flush()
                except Exception:
                    pass

            info = self.runtime.console_turn_stream(text, on_delta)
            answer = str(info.get("answer", ""))
            n_tools = len(info.get("tool_uses") or [])
            # 段5：工具答复=**核验后发布**；普通回答=流式发布
            published = "after_verification" if n_tools else "streamed"
            try:
                from backend import talk_results as _tr

                _tr.store(request_id, {"answer": answer, "tool_uses": n_tools,
                                       "published": published, "text": text[:200]})
            except Exception:
                pass
            self.wfile.write(_sse({"type": "turn_done", "text": answer,
                                   "tool_uses": n_tools, "request_id": request_id,
                                   "published": published}))
            self.wfile.write(_sse({"type": "state", "value": "idle"}))
            self.wfile.flush()
        except Exception as exc:
            try:
                self.wfile.write(_sse({"type": "error",
                                       "message": f"{type(exc).__name__}: "
                                                  f"{str(exc)[:160]}"}))
                self.wfile.write(_sse({"type": "state", "value": "idle"}))
                self.wfile.flush()
            except Exception:
                pass


def make_console_server(port: int, host: str, runtime) -> ThreadingHTTPServer:
    ConsoleHandler.runtime = runtime
    return ThreadingHTTPServer((host, port), ConsoleHandler)


def serve_in_thread(port: int = 8322, host: str = "127.0.0.1",
                    runtime=None) -> threading.Thread:
    server = make_console_server(port, host, runtime)
    t = threading.Thread(target=server.serve_forever, daemon=True,
                         name="console-web")
    t.start()
    print(f"[console] workbench http://{host}:{port}", flush=True)
    return t
