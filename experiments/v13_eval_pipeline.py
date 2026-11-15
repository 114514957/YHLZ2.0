# -*- coding: utf-8 -*-
"""v13 评测流水线：转 GGUF → 起独立 llama-server(8093) → 跑 56+28 → 与基线逐题对拍。

前提：`models/lora/yuanheng-v13/{adapter_config.json,adapter_model.safetensors}` 已拉到本地。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
CONV = os.path.join(ROOT, "models", "llama-cuda", "tools", "convert_lora_to_gguf.py")
BASE_HF = os.path.join(ROOT, "models", "gemma4-hf", "gemma-4-e4b-it")
BASE_GGUF = os.path.join(ROOT, "models", "gemma4-gguf", "gemma-4-E4B_q4_0-it.gguf")
MMPROJ = os.path.join(ROOT, "models", "gemma4-gguf", "gemma-4-E4B-it-mmproj.gguf")
ADAPTER = os.path.join(ROOT, "models", "lora", "yuanheng-v13")
OUT_GGUF = os.path.join(ROOT, "models", "gguf-lora", "yuanheng-v13-lora.gguf")
SERVER = os.path.join(ROOT, "models", "llama-cuda", "llama-server.exe")
PORT = 8093
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def step(msg: str) -> None:
    print("\n=== %s ===" % msg, flush=True)


def convert() -> str:
    if os.path.exists(OUT_GGUF) and os.path.getsize(OUT_GGUF) > 1_000_000:
        print("已存在 GGUF，跳过转换：%s" % os.path.basename(OUT_GGUF))
        return OUT_GGUF
    step("转换 adapter → GGUF")
    cmd = [PY, CONV, ADAPTER, "--base", BASE_HF, "--outfile", OUT_GGUF, "--outtype", "f16"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-1500:] or "")
    if r.returncode != 0:
        print("[stderr] " + (r.stderr or "")[-1500:])
        raise SystemExit("转换失败")
    print("产出 %.1f MB" % (os.path.getsize(OUT_GGUF) / 1048576))
    return OUT_GGUF


def server_up() -> None:
    step("起 llama-server :%d（不碰生产 8081）" % PORT)
    try:
        with OPENER.open("http://127.0.0.1:%d/health" % PORT, timeout=3) as r:
            if r.status == 200:
                print("8093 已在运行，复用")
                return
    except Exception:  # noqa: BLE001
        pass
    cmd = [SERVER, "-m", BASE_GGUF, "--lora", OUT_GGUF,
           "-ngl", "99", "-c", "8192", "--parallel", "1", "-rea", "off", "--jinja",
           "--port", str(PORT), "--host", "127.0.0.1"]
    if os.path.exists(MMPROJ):
        cmd += ["--mmproj", MMPROJ, "--no-mmproj-offload"]
    log = open(os.path.join(ROOT, "cache", "llama_v13_eval.log"), "w",
               encoding="utf-8", errors="replace")
    subprocess.Popen(cmd, cwd=os.path.join(ROOT, "models", "llama-cuda"),
                     stdout=log, stderr=subprocess.STDOUT, close_fds=True)
    for _ in range(60):
        time.sleep(3)
        try:
            with OPENER.open("http://127.0.0.1:%d/health" % PORT, timeout=3) as r:
                if r.status == 200:
                    print("已就绪")
                    return
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit("8093 起不来，看 cache/llama_v13_eval.log")


def evaluate() -> dict:
    step("跑 56 + 28（greedy）")
    r = subprocess.run([PY, "-X", "utf8", os.path.join(ROOT, "experiments", "eval56_28.py"),
                        "--tag", "v13", "--port", str(PORT)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout or "")[-2000:])
    if r.returncode != 0:
        print((r.stderr or "")[-800:])
        raise SystemExit("评测失败")
    return json.load(open(os.path.join(ROOT, "cache", "eval_v13.json"), encoding="utf-8"))


def compare(res: dict) -> None:
    step("与基线逐题对拍（基线 = 当前生产权重）")
    base_p = os.path.join(ROOT, "cache", "eval_基线b_带工具.json")
    if not os.path.exists(base_p):
        print("没有基线文件，跳过对拍")
        return
    base = json.load(open(base_p, encoding="utf-8"))

    def idx(d, suite):
        return {r["id"]: r["ok"] for r in d["detail"][suite]}

    for suite, label in (("persona", "56 题"), ("group", "28 题")):
        b, v = idx(base, suite), idx(res, suite)
        fixed = [k for k in v if k in b and not b[k] and v[k]]
        broke = [k for k in v if k in b and b[k] and not v[k]]
        same_ok = [k for k in v if k in b and b[k] and v[k]]
        print("\n%s：基线 %d/%d → v13 %d/%d"
              % (label, sum(b.values()), len(b), sum(v.values()), len(v)))
        print("   都过 %d｜修好 %d %s｜新挂 %d %s"
              % (len(same_ok), len(fixed), fixed or "", len(broke), broke or ""))
        mcn = len(fixed), len(broke)
        if mcn[0] + mcn[1]:
            print("   McNemar 方向：%s（修好 %d vs 新挂 %d）"
                  % ("变好" if mcn[0] > mcn[1] else ("变差" if mcn[0] < mcn[1] else "持平"),
                     mcn[0], mcn[1]))


if __name__ == "__main__":
    if not os.path.exists(os.path.join(ADAPTER, "adapter_model.safetensors")):
        raise SystemExit("adapter 还没拉到本地：%s" % ADAPTER)
    convert()
    server_up()
    res = evaluate()
    compare(res)
