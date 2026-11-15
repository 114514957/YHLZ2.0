# -*- coding: utf-8 -*-
"""把 v9t10 接进工作台：起实例 → 等就绪 → 发一句试聊 → 报状态。"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
WB = "http://127.0.0.1:8090"
LLM = "http://127.0.0.1:8091"
VID = "gguf:yuanheng-v9t10-lora.gguf"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url, t=30):
    with OPENER.open(url, timeout=t) as r:
        return json.loads(r.read().decode("utf-8"))


def post(url, body, t=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=t) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace"))


print("[1] 起实例 %s（ngl=0 CPU）" % VID)
code, r = post(WB + "/api/server/start", {"version_id": VID, "port": 8091, "ngl": 0})
print("    HTTP %s %s" % (code, json.dumps(r, ensure_ascii=False)[:160]))
if code != 200:
    sys.exit(1)

t0 = time.time()
while True:
    time.sleep(2)
    st = get(WB + "/api/server/status")
    if not (st.get("starting") or {}).get("running"):
        break
    if time.time() - t0 > 300:
        sys.exit("起服务超时")
own = st.get("own") or {}
print("    就绪 %.1fs｜running=%s healthy=%s version=%s pid=%s"
      % (time.time() - t0, own.get("running"), own.get("healthy"),
         own.get("version"), own.get("pid")))

print("\n[2] 试聊一句")
try:
    body = {"messages": [{"role": "user", "content": "在吗"}],
            "temperature": 0.0, "max_tokens": 60}
    req = urllib.request.Request(LLM + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=180) as resp:
        m = json.loads(resp.read().decode())["choices"][0]["message"]
    print("    答：%s" % (m.get("content") or "").replace("\n", " ")[:80])
except Exception as ex:  # noqa: BLE001
    print("    ✗ %s: %s" % (type(ex).__name__, ex))

print("\n[3] 工作台状态")
st = get(WB + "/api/state")
reg = st.get("registry") or {}
vs = reg.get("versions") or []
print("    版本 %d 个，当前实例：%s" % (len(vs), (st.get("server") or {}).get("own", {}).get("version")))
print("    打开：http://127.0.0.1:8090   （「对话测试」标签直接说话即可）")
