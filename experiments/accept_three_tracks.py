# -*- coding: utf-8 -*-
"""三条线收工验收：模型 / QQ接入+白名单 / 记忆+复盘。只报实测，不报印象。"""
from __future__ import annotations

import glob
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
OK, BAD = "✅", "❌"


def port(p, host="127.0.0.1"):
    s = socket.socket()
    s.settimeout(1.0)
    try:
        return s.connect_ex((host, p)) == 0
    finally:
        s.close()


def procs(pat):
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return []
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = " ".join(str(x) for x in (p.info.get("cmdline") or []))
        except Exception:  # noqa: BLE001
            continue
        if pat in cl:
            out.append((p.info["pid"], cl))
    return out


print("=" * 70)
print("一、模型（dpo2）")
print("=" * 70)
ll = procs("llama-server")
lora = ""
for _pid, cl in ll:
    if "--lora" in cl:
        i = cl.find("--lora")
        lora = cl[i + 6:].split('"')[0].split()[0].strip('"')
print("   llama-server 进程：%d 个" % len(ll))
print("   %s 生产 LoRA：%s" % (OK if "dpo2" in lora else BAD, os.path.basename(lora) or "无"))
try:
    with OPENER.open("http://127.0.0.1:8081/health", timeout=5) as r:
        print("   %s /health → %s" % (OK, r.read()[:40].decode()))
except Exception as ex:  # noqa: BLE001
    print("   %s /health 失败 %s" % (BAD, ex))

print()
print("=" * 70)
print("二、QQ 接入 + 群白名单")
print("=" * 70)
print("   %s NapCat 3001：%s" % (OK if port(3001) else BAD, port(3001)))
print("   daemon 8321：%s" % port(8321))
st = {}
try:
    with OPENER.open("http://127.0.0.1:8321/qq/groups", timeout=25) as r:
        st = json.loads(r.read().decode())
    print("   %s /qq/groups → %d 群｜白名单来源 %s"
          % (OK, st.get("count", 0), st.get("whitelist", {}).get("source")))
except Exception as ex:  # noqa: BLE001
    print("   %s /qq/groups 失败 %s" % (BAD, ex))
cfg = os.path.join(ROOT, "config", "qq_groups_whitelist.json")
if os.path.exists(cfg):
    d = json.load(io.open(cfg, encoding="utf-8"))
    print("   %s 白名单文件：%d 群（%s）" % (OK, len(d.get("groups", [])),
                                       d.get("updated", "?")))
else:
    print("   %s 白名单文件还没生成" % BAD)
bs = os.path.join(ROOT, "cache", "qq_bridge", "lite", "bridge_status.json")
if os.path.exists(bs):
    d = json.load(io.open(bs, encoding="utf-8"))
    print("   %s 桥：state=%s｜online=%s｜%.0f 秒前更新"
          % (OK if d.get("state") == "connected" else BAD, d.get("state"),
             d.get("account_online"), time.time() - os.path.getmtime(bs)))

print()
print("=" * 70)
print("三、记忆 + 每日复盘")
print("=" * 70)
db = os.path.join(ROOT, "cache", "memstore", "memstore.db")
c = sqlite3.connect(db)
tot = c.execute("SELECT COUNT(*) FROM l2_items").fetchone()[0]
qq = c.execute("SELECT COUNT(*) FROM l2_items WHERE source LIKE 'qq_%'").fetchone()[0]
print("   %s 本体 L2：%d 条｜QQ 来源 %d 条" % (OK if qq else BAD, tot, qq))
c.close()
for name, pat in (("采集器", "qq_daily_log.py"), ("记忆桥", "qq_memory_bridge.py")):
    ps = procs(pat)
    print("   %s %s：%d 进程｜%s" % (OK if ps else BAD, name, len(ps),
                                    pat in " ".join(x[1] for x in ps)))
dl = os.path.join(ROOT, "cache", "qq_daily", time.strftime("%Y%m%d") + ".jsonl")
if os.path.exists(dl):
    n = sum(1 for x in io.open(dl, encoding="utf-8") if x.strip())
    print("   %s 今日采集：%d 行" % (OK, n))
rep = glob.glob(os.path.join(ROOT, "docs", "复盘", "风格日报_*.md"))
print("   %s 风格日报：%d 份" % (OK if rep else "·", len(rep)))
