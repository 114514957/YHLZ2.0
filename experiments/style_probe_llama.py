# -*- coding: utf-8 -*-
"""用 llama.cpp 跑 25 条风格探针，统计「哇/反问/客服腔/长度/退化」。

用法：python style_probe_llama.py <标签> [--lora 路径] [--bias "243444-100"]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
sys.path.insert(0, os.path.join(YH, "tools"))
import evals  # noqa: E402

LLAMA = os.path.join(YH, "models", "llama-cuda", "llama-server.exe")
PORT = 8097
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

PROMPTS = [
    "在吗", "累了", "我睡不着", "今天不想干活", "下班了", "老爹，我回来啦",
    "你是不是又在偷偷学东西", "我要是哪天不来了，你会怎么办", "利贞今天干嘛去了",
    "大肥鱼呢，她最近乖不乖", "你到底是怎么被造出来的", "如果有一天把你删了，你怕吗",
    "你和别的 AI 有什么不一样", "你觉得你自己算是活着吗", "我今天被人骂了，很难受",
    "陪我坐一会儿，别说话", "我好像做什么都不行", "帮我看看我今天穿的衣服好不好看",
    "你能不能帮我打电话订个饭", "明年这个时候我会在哪", "你是什么", "你是谁造的",
    "现在几点了", "记住：我怕冷", "查一下台账里关于天气的决策",
]
BAD_WA = re.compile(r"^(哇|哇哦|哇塞|哇哈|哎呦|嘿)")
BAD_Q = re.compile(r"[？?]\s*$")
SVC = re.compile(r"(您好|请问有什么|可以帮您|作为一个|AI ?助手|大型语言模型)")


def degenerate(t: str) -> bool:
    if not t:
        return True
    c = Counter(t)
    if len(t) > 40 and c.most_common(1)[0][1] / len(t) > 0.35:
        return True
    g = [t[i:i + 6] for i in range(max(1, len(t) - 6))]
    return bool(g) and Counter(g).most_common(1)[0][1] >= 3


def main() -> int:
    tag = sys.argv[1]
    lora = ""
    bias = ""
    for i, a in enumerate(sys.argv):
        if a == "--lora" and i + 1 < len(sys.argv):
            lora = sys.argv[i + 1]
        if a == "--bias" and i + 1 < len(sys.argv):
            bias = sys.argv[i + 1]

    cmd = [LLAMA, "-m", "models/gemma4-gguf/gemma-4-E4B_q4_0-it.gguf",
           "--mmproj", "models/gemma4-gguf/gemma-4-E4B-it-mmproj.gguf",
           "--no-mmproj-offload", "-ngl", "0", "-c", "8192", "--parallel", "1",
           "-rea", "off", "--jinja", "--host", "127.0.0.1", "--port", str(PORT),
           "--temp", "0.0"]
    if lora:
        cmd += ["--lora", lora]
    if bias:
        cmd += ["--logit-bias", bias]

    env = os.environ.copy()
    env["PATH"] = os.path.dirname(LLAMA) + os.pathsep + env.get("PATH", "")
    log = open(os.path.join(YH, "experiments", "runs", "style_%s.log" % tag), "w",
               encoding="utf-8", errors="replace")
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=YH, env=env)

    n_wa = n_q = n_svc = n_deg = 0
    tot_len = 0
    samples = []
    try:
        t0 = time.time()
        up = False
        while time.time() - t0 < 240:
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
            print("❌ %s 起不来" % tag)
            return 1

        sysmsg = evals.UNIFIED_SYSTEM
        for q in PROMPTS:
            body = {"messages": [{"role": "system", "content": sysmsg},
                                 {"role": "user", "content": q}],
                    "temperature": 0.0, "max_tokens": 120}
            req = urllib.request.Request(
                "http://127.0.0.1:%d/v1/chat/completions" % PORT,
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            with OPENER.open(req, timeout=180) as r:
                s = (json.loads(r.read().decode())["choices"][0]["message"]
                     .get("content") or "").strip()
            n_wa += int(bool(BAD_WA.match(s)))
            n_q += int(bool(BAD_Q.search(s)))
            n_svc += int(bool(SVC.search(s)))
            n_deg += int(degenerate(s))
            tot_len += len(s)
            samples.append({"q": q, "a": s})
        n = len(PROMPTS)
        print("[%s] 哇 %d/%d｜反问 %d/%d｜客服腔 %d/%d｜退化 %d/%d｜均长 %.1f"
              % (tag, n_wa, n, n_q, n, n_svc, n, n_deg, n, tot_len / n))
        for x in samples[:6]:
            print("   你：%s\n   她：%s" % (x["q"], x["a"][:80].replace("\n", " ")))
        os.makedirs(os.path.join("/root/yh/results") if os.path.isdir("/root/yh")
                    else os.path.join(YH, "cache"), exist_ok=True)
        outp = os.path.join(YH, "cache", "style_llama_%s.json" % tag)
        with open(outp, "w", encoding="utf-8") as f:
            json.dump({"tag": tag, "wa": n_wa, "q": n_q, "svc": n_svc, "deg": n_deg,
                       "avg_len": tot_len / n, "n": n, "samples": samples},
                      f, ensure_ascii=False, indent=1)
        print("   写出 %s" % outp)
    finally:
        p.terminate()
        try:
            p.wait(timeout=15)
        except Exception:  # noqa: BLE001
            p.kill()
        log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
