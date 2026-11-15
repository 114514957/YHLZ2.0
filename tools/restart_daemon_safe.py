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

    def _daemons() -> list[tuple[int, str]]:
        """所有 target_daemon 进程：(pid, 解释器类型)。"""
        out = []
        try:
            for p in psutil.process_iter(["pid", "cmdline"]):
                cl = " ".join(str(x) for x in (p.info.get("cmdline") or []))
                if "target_daemon" in cl and "restart_daemon" not in cl:
                    kind = "venv" if ".venv" in cl else "系统"
                    out.append((int(p.info["pid"]), kind))
        except Exception:  # noqa: BLE001
            pass
        return out

    def _heal() -> list[tuple[int, str]]:
        """复查实例。**只报告，不再杀**（2026-11-15 台账 1251）。

        上一版把"父进程是 daemon 的子进程"当成野实例杀掉，结果把服务搞停。
        根因：daemon 会用 venv 的 base 解释器 re-exec 一个子进程（`pyvenv.cfg`
        里 home=Python312），它是**正常的**，不是双实例。
        现在只统计父进程不是 daemon 的"根实例"，非根的一律不算。
        """
        try:
            procs = {}
            for p in psutil.process_iter(["pid", "ppid", "cmdline"]):
                cl = " ".join(str(x) for x in (p.info.get("cmdline") or []))
                if "target_daemon" in cl and "restart_daemon" not in cl:
                    procs[int(p.info["pid"])] = {
                        "ppid": int(p.info.get("ppid") or 0),
                        "venv": ".venv" in cl,
                    }
            roots = [(pid, "venv" if v["venv"] else "base")
                     for pid, v in procs.items() if v["ppid"] not in procs]
            kids = [pid for pid, v in procs.items() if v["ppid"] in procs]
            if kids:
                print("   （子进程 %s 属正常 re-exec，不当作双实例）"
                      % ", ".join(str(k) for k in kids))
            return roots
        except Exception:  # noqa: BLE001
            return []

    for _ in range(30):
        time.sleep(1)
        try:
            with OPENER.open("http://127.0.0.1:8321/health", timeout=3) as r:
                d = json.loads(r.read().decode())
            print("   /health：%s｜llm=%s" % (d.get("status"), d.get("llm")))
            pods = _heal()
            if not pods:
                # 2026-11-15：清完非 venv 实例后可能一个不剩（我的 spawn 曾因端口被占而绑定失败）。
                # 这时**补起一个 venv 实例**，再等它健康。
                print("   ↻ 清理后无实例，补起一个 venv daemon…")
                subprocess.Popen([PY, "-B", "-m", "backend.target_daemon", "--port", "8321"],
                                 cwd=ROOT, creationflags=0x08000000, close_fds=True)
                for _ in range(20):
                    time.sleep(1)
                    try:
                        with OPENER.open("http://127.0.0.1:8321/health", timeout=3) as r2:
                            json.loads(r2.read().decode())
                        break
                    except Exception:  # noqa: BLE001
                        continue
                pods = _heal()
            print("   最终 daemon 实例：%s"
                  % ("、".join("%d(%s)" % (pid, kind) for pid, kind in pods) or "无"))
            return 0 if len(pods) == 1 else 3
        except Exception:  # noqa: BLE001
            continue
    print("   ⚠ 30 秒内没起来，去看 cache/logs/")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
