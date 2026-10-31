"""S2.1 假生成器自检：验证 lab server 单请求门的所有权与错误恢复。

场景：正常非流式、流式、编码异常、生成异常、空输出、并发 429、客户端断开。
每个场景后必须能继续处理后续请求（门被正确释放）。
用法：
  python tools/cosy_s2_selftest.py --server cache/lab_s2/server.py \
      --out artifacts/lab_s2/selftest_report.json
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeTensor:
    def __init__(self, arr):
        self._a = arr

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._a


class FakeModel:
    def __init__(self):
        self.token_hop_len = 25
        self.token_max_hop_len = 100


class FakeCosyVoice:
    def __init__(self):
        self.sample_rate = 24000
        self.model = FakeModel()
        self.frontend = SimpleNamespace(spk2info={})

    def add_zero_shot_spk(self, prompt, wav, spk_id):
        self.frontend.spk2info[spk_id] = True

    def inference_instruct2(self, text, instruction, wav, **kw):
        return self._gen(str(text), bool(kw.get("stream")))

    def inference_zero_shot(self, text, prompt, wav, zero_shot_spk_id=None,
                            stream=False, speed=1.0):
        return self._gen(str(text), bool(stream))

    def _gen(self, text, stream):
        import numpy as np

        if "EMPTY" in text:
            return iter(())

        def gen():
            if "RAISE" in text:
                yield {"tts_speech": FakeTensor(np.zeros((1, 2400), dtype=np.float32))}
                raise RuntimeError("fake-mid-gen-boom")
            chunks = 4 if stream else 2
            delay = 0.25 if "SLOW" in text else 0.0
            for _ in range(chunks):
                if delay:
                    time.sleep(delay)
                yield {"tts_speech": FakeTensor(
                    np.full((1, 2400), 0.02, dtype=np.float32))}

        return gen()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def load_server(path: Path):
    spec = importlib.util.spec_from_file_location("cosy_server_selftest", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._load_wav_bytes = lambda raw, sr: "FAKE_PROMPT"
    module._decode_data_url = lambda data: b"FAKE_REF"
    module.cosyvoice = FakeCosyVoice()
    module.args = SimpleNamespace(
        model_dir="FAKE", assets_dir="FAKE", tmp_dir="FAKE",
        zero_shot_mode="cross_lingual", stream_hop_len=None, flow_steps=None,
        vllm=False, bf16=False, max_concurrent=1, fixed_gain=None,
        dump_gain_dir=None, keepalive=False, no_warmup=False,
    )
    return module


def post(port: int, text: str, stream: bool, timeout: float = 60.0):
    payload = {
        "input": text, "stream": stream,
        "ref_audio": "data:audio/wav;base64," + base64.b64encode(b"x").decode(),
    }
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/audio/speech",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="CosyVoice lab server S2.1 自检")
    parser.add_argument("--server", default=str(ROOT / "cache" / "lab_s2" / "server.py"))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "lab_s2" / "selftest_report.json"))
    args = parser.parse_args()

    module = load_server(Path(args.server))
    import uvicorn

    port = _free_port()
    app = module.create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
                break
        except Exception:  # noqa: BLE001
            time.sleep(0.1)

    report = {"server": str(args.server), "port": port, "scenarios": []}
    failures = []

    def scenario(name: str, func):
        result = {"name": name}
        try:
            detail = func() or {}
            result.update(detail)
            result["ok"] = bool(detail.get("ok", True))
        except Exception as exc:  # noqa: BLE001
            result.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        report["scenarios"].append(result)
        if not result["ok"]:
            failures.append(name)
        print(f"[selftest] {name}: {'OK' if result['ok'] else 'FAIL ' + str(result.get('error') or result)}")

    def expect_followup_ok():
        code, body = post(port, "NORMAL 后续请求", False)
        return code == 200 and body[:4] == b"RIFF"

    scenario("normal_nonstream", lambda: {
        "code": post(port, "NORMAL 非流式", False)[0],
        "followup_ok": expect_followup_ok(), "ok": True})

    code, body = post(port, "NORMAL 流式", True)
    scenario("stream_normal", lambda: {
        "code": code, "bytes": len(body), "riff": body[:4] == b"RIFF",
        "followup_ok": expect_followup_ok(),
        "ok": code == 200 and body[:4] == b"RIFF"})

    def encode_fail():
        original = module._encode_wav
        module._encode_wav = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("fake-encode-boom"))
        try:
            code, _ = post(port, "NORMAL 编码异常", False)
        finally:
            module._encode_wav = original
        follow = expect_followup_ok()
        time.sleep(0.2)
        return {"code": code, "followup_ok": follow,
                "ok": code == 500 and follow}
    scenario("encode_exception_releases_gate", encode_fail)

    def gen_raise():
        code, _ = post(port, "RAISE 生成中异常", False)
        follow = expect_followup_ok()
        return {"code": code, "followup_ok": follow, "ok": code == 500 and follow}
    scenario("generation_exception_releases_gate", gen_raise)

    def empty_output():
        code, _ = post(port, "EMPTY 空输出", False)
        follow = expect_followup_ok()
        return {"code": code, "followup_ok": follow, "ok": code == 500 and follow}
    scenario("empty_output_releases_gate", empty_output)

    def concurrent_429():
        holder = {}

        def slow_request():
            holder["resp"] = post(port, "SLOW 慢流", True, timeout=60)

        worker = threading.Thread(target=slow_request)
        worker.start()
        time.sleep(0.5)
        code_busy, _ = post(port, "NORMAL 并发第二请求", False, timeout=10)
        worker.join(timeout=30)
        code_holder = holder.get("resp", (0, b""))[0]
        time.sleep(0.2)
        follow = expect_followup_ok()
        return {"code_busy": code_busy, "code_holder": code_holder,
                "followup_ok": follow,
                "ok": code_busy == 429 and code_holder == 200 and follow}
    scenario("concurrent_second_gets_429", concurrent_429)

    def client_disconnect():
        payload = json.dumps({
            "input": "SLOW 断开测试", "stream": True,
            "ref_audio": "data:audio/wav;base64," + base64.b64encode(b"x").decode(),
        }).encode("utf-8")
        request = (f"POST /v1/audio/speech HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                   f"Content-Type: application/json\r\n"
                   f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n").encode() + payload
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        sock.sendall(request)
        time.sleep(0.9)
        try:
            sock.recv(4096)
        except OSError:
            pass
        sock.close()
        time.sleep(1.0)
        follow = expect_followup_ok()
        return {"followup_ok": follow, "ok": follow}
    scenario("client_disconnect_releases_gate", client_disconnect)

    server.should_exit = True
    thread.join(timeout=5)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"scenarios": len(report["scenarios"]),
                      "failures": failures, "out": str(out)},
                     ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
