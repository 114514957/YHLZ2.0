"""S5 TTS 桥：把回复句段送入本机 live 音频服务（/control say 入队 + 回执）。

不直接播放、不打开设备；是否出声由 live 服务的 arm/lease 决定：
未武装时只排队并 TTL 过期，桥本身永不回落到扬声器。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from backend.live.conversation import split_for_tts

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LIVE_JSON = ROOT / "config" / "live.json"
DEFAULT_LOCAL_JSON = ROOT / "config" / "live.local.json"


@dataclass
class LiveTTSBridgeConfig:
    base_url: str = "http://127.0.0.1:8377"
    token: str = ""
    timeout_s: float = 300.0
    max_chars: int = 48
    max_segment_duration_s: float = 20.0


class LiveTTSBridge:
    def __init__(self, config: Optional[LiveTTSBridgeConfig] = None):
        self.config = config or LiveTTSBridgeConfig()
        self.cap_tripped = False

    @classmethod
    def from_config(cls, live_json: Path = DEFAULT_LIVE_JSON,
                    local_json: Path = DEFAULT_LOCAL_JSON) -> "LiveTTSBridge":
        host, port, token = "127.0.0.1", 8377, ""
        try:
            data = json.loads(Path(live_json).read_text(encoding="utf-8"))
            host = str(data.get("host") or host)
            port = int(data.get("port") or port)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        try:
            token = str(json.loads(Path(local_json).read_text(encoding="utf-8"))
                        .get("lease_token") or "")
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return cls(LiveTTSBridgeConfig(base_url=f"http://{host}:{port}", token=token))

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.config.base_url.rstrip("/") + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read()[:300].decode("utf-8", "replace")
            try:
                return {"ok": False, "error": json.loads(body).get("error", body),
                        "_http_status": exc.code}
            except json.JSONDecodeError:
                return {"ok": False, "error": body, "_http_status": exc.code}
        except (urllib.error.URLError, TimeoutError) as exc:
            return {"ok": False, "error": f"live-service-unreachable:{exc}"}

    def synth_segment(self, text: str) -> dict[str, Any]:
        response = self._post("/control", {
            "token": self.config.token, "action": "say",
            "text": text, "client_id": "s5-bridge",
        })
        inner = response.get("result") if isinstance(response.get("result"), dict) else response
        duration = inner.get("duration_s")
        ok = bool(inner.get("segment_id"))
        error = response.get("error") or inner.get("error")
        if ok and duration and float(duration) > self.config.max_segment_duration_s:
            ok = False
            self.cap_tripped = True
            error = f"duration-cap-exceeded:{duration}s"
        return {
            "ok": ok,
            "segment_id": inner.get("segment_id"),
            "synth_ms": inner.get("synth_ms"),
            "duration_s": duration,
            "error": error,
        }

    def speak(self, text: str) -> dict[str, Any]:
        segments = [self.synth_segment(part)
                    for part in split_for_tts(text, self.config.max_chars)]
        result = {
            "text": text,
            "count": len(segments),
            "segments": segments,
            "total_synth_ms": sum(int(s.get("synth_ms") or 0) for s in segments),
            "ok": all(s["ok"] for s in segments) if segments else False,
        }
        if self.cap_tripped:
            result["cap_cleared"] = bool(self.clear().get("ok"))
            self.cap_tripped = False
        return result

    def clear(self) -> dict[str, Any]:
        return self._post("/control", {
            "token": self.config.token, "action": "stop", "reason": "s5-chain-clear",
        })
