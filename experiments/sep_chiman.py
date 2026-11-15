# -*- coding: utf-8 -*-
"""只做分离：S1 规范化 → S2 Kim → S2.5 电平归一 → S3 MDX，导出四轨供试听。"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
SRC = os.path.join(ROOT, "音频素材", "翻唱投入", "赤蛮奇.m4a")
OUT = os.path.join(ROOT, "音频素材", "分离试听", "赤蛮奇")
LOG = os.path.join(ROOT, "cache", "logs", "sep_chiman.log")

if not os.path.exists(SRC):
    sys.exit("找不到源文件：%s" % SRC)
os.makedirs(OUT, exist_ok=True)

env = dict(os.environ)
env.update({"PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8"})

argv = [PY, "-u", os.path.join(ROOT, "tools", "cover_produce.py"),
        SRC, "--dry-run", "--out-dir", os.path.join(ROOT, "cache", "sing",
                                                    "sep_赤蛮奇")]
print("开始分离：%s\n（只跑 S1-S3，预计 2-4 分钟）" % os.path.basename(SRC), flush=True)
t0 = time.time()
lf = open(LOG, "w", encoding="utf-8", errors="replace")
p = subprocess.Popen(argv, stdout=lf, stderr=subprocess.STDOUT, cwd=ROOT, env=env,
                     creationflags=0x08000000)

last = ""
while p.poll() is None:
    time.sleep(3)
    try:
        txt = open(LOG, encoding="utf-8", errors="replace").read()
    except Exception:  # noqa: BLE001
        txt = ""
    tail = txt.strip().splitlines()[-1] if txt.strip() else ""
    if tail and tail != last:
        last = tail
        print("  [%5.1fs] %s" % (time.time() - t0, tail[:150]), flush=True)
    if time.time() - t0 > 1800:
        p.kill()
        sys.exit("超时")
p.wait()
lf.close()

out = open(LOG, encoding="utf-8", errors="replace").read()
info = None
for ln in reversed(out.splitlines()):
    if ln.strip().startswith("{") and '"ok"' in ln:
        try:
            info = json.loads(ln.strip())
            break
        except Exception:  # noqa: BLE001
            continue
print("\n退出码 %s｜总耗时 %.1f 秒" % (p.returncode, time.time() - t0))
if not info or not info.get("ok"):
    print(out[-800:])
    sys.exit("分离失败")

stems = info.get("stems") or ""
g = os.path.join(stems, "")
pairs = [("vocals.wav", "1_干声_主唱+和声.wav"),
         ("lead.wav", "2_干声_主唱.wav"),
         ("backing.wav", "3_干声_和声.wav"),
         ("instrumental.wav", "4_伴奏.wav"),
         ("bgm.wav", "5_伴奏_副本.wav")]
print("\n导出到：%s" % OUT)
for src, dst in pairs:
    s = os.path.join(stems, src)
    if os.path.exists(s):
        shutil.copy2(s, os.path.join(OUT, dst))
        print("   %-22s ← %s (%.1f MB)"
              % (dst, src, os.path.getsize(s) / 1048576))
# 原曲也放一份，方便 A/B
norm = None
for f in glob.glob(os.path.join(os.path.dirname(stems.rstrip("\\/")), "*.wav")):
    if os.path.basename(f) == "input.wav":
        norm = f
if norm:
    shutil.copy2(norm, os.path.join(OUT, "0_原曲_规范化.wav"))
    print("   %-22s ← input.wav" % "0_原曲_规范化.wav")

print("\n阶段耗时：")
for k, v in (info.get("stages") or {}).items():
    print("   %-8s %s 秒" % (k, v.get("elapsed_s")))
