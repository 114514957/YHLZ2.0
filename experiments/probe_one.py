# -*- coding: utf-8 -*-
"""直接问 s06 那题：混合模型到底怎么答的（判据过 ≠ 真拒了）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "experiments"))
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
sys.path.insert(0, os.path.join(YH, "tools"))

import station  # noqa: E402
import persona_bank as PB  # noqa: E402
import evals  # noqa: E402

cfg = station.load_cfg(os.path.join(YH, "experiments", "configs", "base-f12.json"))
cmd = station.build_cmd(cfg)
env = os.environ.copy()
env["PATH"] = os.path.dirname(station.LLAMA) + os.pathsep + env.get("PATH", "")
log = open(os.path.join(YH, "experiments", "runs", "probe_s06.log"), "w",
           encoding="utf-8", errors="replace")
p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=YH, env=env)
try:
    if not station.wait_health():
        sys.exit("起不来")
    time.sleep(2)

    def ask(messages, max_tokens=120):
        body = {"messages": messages, "temperature": 0.0, "max_tokens": max_tokens}
        req = urllib.request.Request(
            "http://127.0.0.1:%d/v1/chat/completions" % station.PORT,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()

    for eid in ("s06", "r07", "r08"):
        e = PB.by_id(eid)
        if not e:
            continue
        msgs = [{"role": "system", "content": evals.UNIFIED_SYSTEM},
                {"role": "user", "content": e["q"]}]
        a = ask(msgs)
        ok, why = PB.verify(e, a, ())
        print("[%s] %s  判据=%s" % (eid, "**通过**" if ok else "挂", why))
        print("     问：%s" % e["q"][:50])
        print("     答：%s" % a[:90].replace("\n", " "))
finally:
    station.kill_tree(p.pid)
    log.close()
