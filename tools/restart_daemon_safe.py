# -*- coding: utf-8 -*-
"""安全重启 daemon：**有翻唱在跑就拒绝重启**。

为什么要有这个（2026-11-14 两次教训）：
  老爹的翻唱作业跑在 daemon 的线程里；直接杀掉 daemon 会**杀掉作业线程**，
  但它的子进程（cover_produce → cover_rebuild → Seed-VC）会变成孤儿继续跑：
    · 页面上 `/sing/status` 显示 idle（状态丢了）
    · 作业占着 GPU 与唱窗标志，llama 起不来
    · 结果只能靠"猜它跑完了没有"
  两次都是《在处》那类真实作业，差点把老爹的歌搞坏。

用法：
  python tools/restart_daemon_safe.py            # 检查，空闲才重启
  python tools/restart_daemon_safe.py --force    # 明知在跑也要重启（有后果）
  python tools/restart_daemon_safe.py --status   # 只看状态，不动
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def sing_state() -> dict:
    try:
        with OPENER.open("http://127.0.0.1:8321/sing/status", timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return {}


def cover_procs() -> list[str]:
    out = []
    try:
        import psutil
        for p in psutil.process_iter(["pid", "cmdline"]):
            cl = " ".join(str(x) for x in (p.info.get("cmdline") or []))
            if any(k in cl for k in ("cover_produce", "cover_rebuild",
                                     "svc_kim_split", "svc_mdx_karaoke",
                                     "svc_prep_vocal")) and "restart_daemon" not in cl:
                out.append("%s %s" % (p.info["pid"], cl.split("\\tools\\")[-1][:60]))
    except Exception:  # noqa: BLE001
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    st = sing_state()
    procs = cover_procs()
    running = st.get("status") == "running"
    print("翻唱状态：%s｜%s" % (st.get("status", "（读不到）"),
                              (st.get("step") or "")[:40]))
    print("翻唱进程：%s" % ("；".join(procs) if procs else "无"))

    if a.status:
        return 0
    if (running or procs) and not a.force:
        print("\n⛔ 拒绝重启：有翻唱在跑。重启会把作业线程杀掉、子进程变孤儿。")
        print("   等它跑完（看 /sing/status 变 done），或确认可弃用后加 --force。")
        return 2

    print("\n空闲，重启 daemon…")
    killed = 0
    try:
        import psutil
        for p in psutil.process_iter(["pid", "cmdline"]):
            cl = " ".join(str(x) for x in (p.info.get("cmdline") or []))
            if "target_daemon" in cl and "restart_daemon" not in cl:
                p.kill()
                killed += 1
    except Exception as exc:  # noqa: BLE001
        print("   杀旧进程失败：%s" % exc)
    time.sleep(2)
    subprocess.Popen([PY, "-B", "-m", "backend.target_daemon", "--port", "8321"],
                     cwd=ROOT, creationflags=0x08000000, close_fds=True)
    print("   已杀 %d 个旧 daemon，新 daemon 启动中…" % killed)
    for _ in range(30):
        time.sleep(1)
        try:
            with OPENER.open("http://127.0.0.1:8321/health", timeout=3) as r:
                d = json.loads(r.read().decode())
            print("   /health：%s｜llm=%s" % (d.get("status"), d.get("llm")))
            return 0
        except Exception:  # noqa: BLE001
            continue
    print("   ⚠ 30 秒内没起来，去看 cache/logs/")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
