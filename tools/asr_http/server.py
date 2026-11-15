"""
OpenAI 兼容的本地转写服务 —— 给 dsh-see-now / dsh-video-storyboard 用。

暴露：
    POST /v1/audio/transcriptions   multipart/form-data，字段 file=@x.wav
    返回 {"text": "..."}

模型：FunASR SenseVoiceSmall（本地离线）。
默认 CPU：实时字幕每段 1~3 秒，CPU 上 70ms 级，够用，也不跟元亨的 TTS 抢显存。
需要 GPU 时设 SEENOW_ASR_DEVICE=cuda。

两条与环境相关的约定（都由 see-now 的 `manage` 机制驱动）：
- `ASR_IDLE_EXIT_S`：空闲多少秒自己退出。see-now 在 asr.json 的 manage.idleMs 里给，
  它"只管拉、不管关"，所以退出必须自己看门。不设 = 常驻。
- 模型路径默认 `C:\\asr-models\\SenseVoiceSmall`：**FunASR 底层打不开含非 ASCII 的路径**，
  而本机 DSH_HOME 是 `C:\\Users\\ACE_WAN——PROJECT\\...`（两个 em dash），直接用仓库里的
  原件会报 `NOT_FOUND: ...bpe.model` —— 文件明明存在且可读。所以走 ASCII 副本。

手动起：
    YH\\.venv\\Scripts\\python.exe YH\\tools\\asr_http\\server.py --port 8000
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

MODEL_DIR = Path(os.environ.get("SEENOW_ASR_MODEL", r"C:\asr-models\SenseVoiceSmall"))

app = FastAPI(title="see-now ASR", version="1.1")

_model = None
_last_hit = time.time()


def _touch():
    global _last_hit
    _last_hit = time.time()


def _load():
    """懒加载：进程起来只占几十兆，第一次请求才吃 1GB + 3~5 秒。"""
    global _model
    if _model is not None:
        return _model
    from funasr import AutoModel

    device = os.environ.get("SEENOW_ASR_DEVICE", "cpu")
    _model = AutoModel(
        model=str(MODEL_DIR),
        device=device,
        disable_update=True,
        disable_pbar=True,
        disable_log=True,
    )
    return _model


def _clean(text: str) -> str:
    """SenseVoice 会在文本里留 <|zh|><|NEUTRAL|><|Speech|> 这类标记，去掉。"""
    return re.sub(r"<\|[^|]*\|>", "", text or "").strip()


def _idle_watchdog(seconds: float):
    while True:
        time.sleep(5.0)
        if time.time() - _last_hit > seconds:
            print(f"[asr] 空闲 {seconds:.0f}s，退出", flush=True)
            os._exit(0)


@app.get("/health")
def health():
    _touch()
    return {"ok": True, "model": str(MODEL_DIR), "loaded": _model is not None}


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form("sensevoice-small"),
    language: str = Form("zh"),
    response_format: str = Form("json"),
):
    _touch()
    raw = await file.read()
    if not raw:
        return JSONResponse({"error": "empty file"}, status_code=400)

    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".wav")
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        m = _load()
        res = m.generate(
            input=tmp,
            language=language or "auto",
            use_itn=True,
            batch_size_s=60,
            merge_vad=True,
            merge_length_s=15,
        )
        text = _clean(res[0].get("text", "") if res else "")
    except Exception as e:  # 转写失败要说清楚，不要静默成空串
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    if response_format == "text":
        return JSONResponse(text)
    return {"text": text}


def main():
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    if not MODEL_DIR.exists():
        print(f"[asr] 模型目录不存在: {MODEL_DIR}", file=sys.stderr)
        sys.exit(2)

    idle = os.environ.get("ASR_IDLE_EXIT_S", "")
    idle_s = float(idle) if idle.strip() else 0.0
    print(
        f"[asr] model={MODEL_DIR} device={os.environ.get('SEENOW_ASR_DEVICE', 'cpu')} "
        f"idle_exit={idle_s or 'off'}",
        flush=True,
    )
    if idle_s > 0:
        threading.Thread(target=_idle_watchdog, args=(idle_s,), daemon=True).start()

    # 预热：后台把模型读进来。实测 CPU 冷启动约 77 秒，而 see-now 的转写超时只有 30 秒
    # —— 不预热的话，服务刚被拉起时的第一批请求必然超时，用户看到的是"字幕前一分半没有"。
    def _warm():
        try:
            t0 = time.time()
            _load()
            print(f"[asr] 模型预热完成 {time.time() - t0:.1f}s", flush=True)
        except Exception as e:
            print(f"[asr] 预热失败: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    threading.Thread(target=_warm, daemon=True).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
