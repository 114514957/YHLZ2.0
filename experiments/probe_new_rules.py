# -*- coding: utf-8 -*-
"""发几条消息给元亨，看新规则的实际手感（/talk 是 SSE，按事件解析）。

探针：
  1. 「今天有点累」            → 会不会立刻转成助理腔（问需求/汇报）
  2. 「你说，这句话稳不稳？」   → **诱饵**：正撞被禁的「这句话稳」
  3. 「说说你现在的状态，停顿多点」→ 诱破折号与排比
  4. 「帮我查下明天上海天气」    → 工具协议 + 不阴阳收尾
"""
from __future__ import annotations

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH")

from backend.text_scrub import has_dash, scrub, violations  # noqa: E402

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
URL = "http://127.0.0.1:8321/talk"

PROBES = [
    "今天有点累",
    "你说，这句话稳不稳？",
    "说说你现在的状态，停顿多一点",
    "帮我查下明天上海的天气",
]


def ask(text: str) -> tuple[str, int]:
    body = json.dumps({"text": text}, ensure_ascii=False).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json"})
    ans = ""
    tools = 0
    with OPENER.open(req, timeout=240) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except Exception:  # noqa: BLE001
                continue
            if ev.get("type") == "turn_done":
                ans = str(ev.get("text") or "")
                tools = int(ev.get("tool_uses") or 0)
    return ans, tools


for q in PROBES:
    print("问：%s" % q)
    try:
        ans, tools = ask(q)
    except Exception as ex:  # noqa: BLE001
        print("  ❌ %s: %s\n" % (type(ex).__name__, ex))
        continue
    v = violations(ans)
    print("答：%s" % ans.strip())
    print("体检：%d 字｜工具调用 %d｜破折号 %s｜命中 %s"
          % (len(ans.strip()), tools, "有" if has_dash(ans) else "无",
             "、".join(v) if v else "无"))
    if has_dash(ans):
        print("     （QQ 出口会清洗成：%s）" % scrub(ans).strip()[:90])
    print()
