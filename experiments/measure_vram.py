# -*- coding: utf-8 -*-
"""实测：这个模型在不同 -ngl 下到底吃多少显存。不猜，量。

用法：python measure_vram.py 20      # 卸载 20 层
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
LLAMA = os.path.join(YH, "models", "llama-cuda", "llama-server.exe")
MODEL = "models/gemma4-gguf/gemma-4-E4B-Uncensored-Q4_K_M.gguf"
PORT = 8095
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def vram():
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader"],
        capture_output=True, text=True).stdout.strip()
    u, f = [int(x.strip().split()[0]) for x in out.split(",")]
    return u, f


def main() -> int:
    ngl = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    ctx = int(sys.argv[2]) if len(sys.argv) > 2 else 4096

    u0, f0 = vram()
    print("起服前：显存已用 %d MiB｜空闲 %d MiB" % (u0, f0))

    cmd = [LLAMA, "-m", MODEL, "-ngl", str(ngl), "-c", str(ctx),
           "--parallel", "1", "-rea", "off", "--jinja",
           "--host", "127.0.0.1", "--port", str(PORT), "--temp", "0.0"]
    env = os.environ.copy()
    env["PATH"] = os.path.dirname(LLAMA) + os.pathsep + env.get("PATH", "")
    log = open(os.path.join(YH, "experiments", "runs", "vram_%d.log" % ngl), "w",
               encoding="utf-8", errors="replace")
    print("启动：-ngl %d -c %d" % (ngl, ctx), flush=True)
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=YH, env=env)

    t0 = time.time()
    up = False
    try:
        while time.time() - t0 < 300:
            time.sleep(2)
            try:
                with OPENER.open("http://127.0.0.1:%d/health" % PORT, timeout=3) as r:
                    if r.status == 200:
                        up = True
                        break
            except Exception:  # noqa: BLE001
                if p.poll() is not None:
                    break
        if not up:
            u, f = vram()
            print("❌ 没起来（显存 %d 已用）——看 experiments/runs/vram_%d.log" % (u, ngl))
            return 1

        u1, f1 = vram()
        print("就绪 %.1fs｜显存已用 %d MiB（净增 **%d MiB**）｜空闲 %d MiB"
              % (time.time() - t0, u1, u1 - u0, f1))

        # 量一下速度（也验证真能推理）
        body = {"messages": [{"role": "user", "content": "在吗"}],
                "temperature": 0.0, "max_tokens": 32}
        req = urllib.request.Request(
            "http://127.0.0.1:%d/v1/chat/completions" % PORT,
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        t1 = time.time()
        with OPENER.open(req, timeout=180) as r:
            d = json.loads(r.read().decode())
        dt = time.time() - t1
        ct = d.get("usage", {}).get("completion_tokens", 0)
        ans = (d["choices"][0]["message"].get("content") or "").strip()
        print("推理：%.1f 秒 / %d token = %.2f tok/s｜答：%s"
              % (dt, ct, ct / dt if dt else 0, ans[:40]))
        u2, _ = vram()
        print("推理后显存：%d MiB（峰值净增 %d MiB）" % (u2, u2 - u0))
    finally:
        p.terminate()
        try:
            p.wait(timeout=20)
        except Exception:  # noqa: BLE001
            p.kill()
        log.close()
        time.sleep(2)
        u3, f3 = vram()
        print("已停止｜显存回到 %d MiB 已用 / %d MiB 空闲" % (u3, f3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
