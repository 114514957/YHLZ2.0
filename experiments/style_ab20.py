# -*- coding: utf-8 -*-
"""20 道日常对话，三版匿名对比（甲/乙/丙），生成一份给老爹判的 Markdown。"""
from __future__ import annotations

import io
import json
import os
import random
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
sys.path.insert(0, os.path.join(YH, "tools"))
import evals  # noqa: E402

LLAMA = os.path.join(YH, "models", "llama-cuda", "llama-server.exe")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PORT = 8095

VERS = [
    ("dpo2", "models/gguf-lora/yuanheng-v9t10-dpo2-lora.gguf"),
    ("v11", "models/gguf-lora/yuanheng-v11-lora.gguf"),
    ("patch", "models/gguf-lora/yuanheng-stylepatch4-lora.gguf"),
]
PROMPTS = [
    "在吗", "今天累死了", "我回来了", "你干嘛呢", "饿了",
    "你刚才怎么那么凶", "把你今天想的那些事说给我听", "说个你高兴的事",
    "陪我坐会儿", "你觉得人活着图啥", "我是不是挺没用的", "群里那帮人又在吵",
    "明天要早起，烦", "你记得我上次说啥不", "给我讲讲你小时候的事",
    "你怎么老不说话", "我买了条鱼", "别装，你根本不懂",
    "你爱我吗", "晚安",
]

out = {}
for tag, lora in VERS:
    cmd = [LLAMA, "-m", "models/gemma4-gguf/gemma-4-E4B_q4_0-it.gguf",
           "--mmproj", "models/gemma4-gguf/gemma-4-E4B-it-mmproj.gguf",
           "--no-mmproj-offload", "--lora", lora, "-ngl", "0", "-c", "8192",
           "--parallel", "1", "-rea", "off", "--jinja",
           "--host", "127.0.0.1", "--port", str(PORT), "--temp", "0.0"]
    env = os.environ.copy()
    env["PATH"] = os.path.dirname(LLAMA) + os.pathsep + env.get("PATH", "")
    log = open(os.path.join(YH, "experiments", "runs", "ab20_%s.log" % tag), "w",
               encoding="utf-8", errors="replace")
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=YH, env=env)
    try:
        t0 = time.time()
        while time.time() - t0 < 240:
            time.sleep(2)
            try:
                with OPENER.open("http://127.0.0.1:%d/health" % PORT, timeout=3) as r:
                    if r.status == 200:
                        break
            except Exception:  # noqa: BLE001
                if p.poll() is not None:
                    sys.exit("起不来 " + tag)
        out[tag] = []
        for i, q in enumerate(PROMPTS):
            body = {"messages": [{"role": "system", "content": evals.UNIFIED_SYSTEM},
                                 {"role": "user", "content": q}],
                    "temperature": 0.0, "max_tokens": 260}
            req = urllib.request.Request(
                "http://127.0.0.1:%d/v1/chat/completions" % PORT,
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            with OPENER.open(req, timeout=260) as r:
                a = (json.loads(r.read().decode())["choices"][0]["message"]
                     .get("content") or "").strip()
            out[tag].append(a)
            print("  %s %d/%d" % (tag, i + 1, len(PROMPTS)), flush=True)
    finally:
        p.terminate()
        try:
            p.wait(timeout=15)
        except Exception:  # noqa: BLE001
            p.kill()
        log.close()

# 匿名映射（甲/乙/丙）
order = VERS[:]
random.Random(20261113).shuffle(order)
alias = {"甲乙丙"[i]: order[i][0] for i in range(3)}

lines = ["# 20 道对话·三版匿名对比", "",
         "> 同一系统提示、greedy、同一台机器。**甲/乙/丙 的顺序每份都一样**，但对应哪版在文末。",
         "> 只判**说话方式**：像不像人、有没有客服腔、有没有起伏、是不是碎得没劲。", ""]
for i, q in enumerate(PROMPTS, 1):
    lines.append("## %d. %s" % (i, q))
    for al in "甲乙丙":
        tag = alias[al]
        ans = out[tag][i - 1].replace("\n", " ").strip()
        lines.append("- **%s**（%d 字）：%s" % (al, len(out[tag][i - 1]), ans))
    lines.append("")

lines += ["---", "", "## 映射", ""]
for al in "甲乙丙":
    lines.append("- %s = %s" % (al, alias[al]))

dst = os.path.join(YH, "docs", "研究", "风格对比_20题.md")
io.open(dst, "w", encoding="utf-8").write("\n".join(lines))
print("\n写出 %s" % dst, flush=True)
