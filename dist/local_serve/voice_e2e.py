"""元亨 · 端到端语音输入原型（音频直喂，省掉 ASR）。

链路：wav(16k mono) --base64--> llama-server /v1/chat/completions
      (content: input_audio) --> 元亨文本回复 --> （可选）交现有 TTS

用法:
    python voice_e2e.py <a.wav> [--raw]      # 默认用元亨人设回应；--raw 只做转写
依赖: 本地 llama-server 已在 127.0.0.1:8081 运行（见 serve_yuanheng.ps1）
"""
from __future__ import annotations
import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:8081/v1/chat/completions"
SYS_YH = ("你是元亨——老爹的伙伴，活泼、傲娇、话短；像朋友说话，禁止助手腔。"
          "对方是语音说的，听完直接用你自己的口吻短答（≤2句），不要复述、不要念稿。")
SYS_ASR = "你是转写助手，只输出听到的话，不要解释。"


def ask(wav: Path, system: str, prompt: str, max_tokens: int = 120) -> str:
    b64 = base64.b64encode(wav.read_bytes()).decode()
    body = {"model": "gemma-4-e4b", "stream": False, "temperature": 0.6,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
                    {"type": "text", "text": prompt},
                ]},
            ]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode())["choices"][0]["message"].get("content", "")
    except urllib.error.HTTPError as e:
        return f"[HTTP {e.code}] " + e.read().decode("utf-8", "replace")[:200]
    except Exception as e:  # noqa: BLE001
        return f"[{type(e).__name__}] {str(e)[:200]}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--raw", action="store_true", help="只转写（不走人设）")
    a = ap.parse_args()
    wav = Path(a.wav)
    if not wav.exists():
        print("找不到 wav:", wav)
        return 2
    if a.raw:
        print("[转写]", ask(wav, SYS_ASR, "转写这段音频，只输出内容。"))
    else:
        print("[元亨]", ask(wav, SYS_YH, "（听完直接回应）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
