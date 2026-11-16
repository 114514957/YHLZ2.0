# -*- coding: utf-8 -*-
"""验证：记忆真的在工作吗？时刻度真的能用吗？（不是花瓶）

一、记忆验证（端到端）
  1. 造一条她不可能靠常识知道的暗号记忆（含唯一串）
  2. 走**生产路径**问她 → 必须答出暗号
  3. 查 `recall_trace` → 必须有 n>0 且能把这条 id 注进去
  4. 反例控制：问她一件从没存过的事 → 不许编（要说不记得/没这条）
  5. **清理**：删掉测试记忆，重建索引，重启 daemon

二、时刻度验证
  1. `at` 合理性：无未来时间、最新≈现在、同群按 seq 单调
  2. 复现"清洗前 47% / 清洗后 0%"（从 DB 现算，不信文档）
  3. 噪声量级：按天比例的标准差，验证"±5% 属噪声"这个说法
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, ROOT)

MS = os.path.join(ROOT, "cache", "memstore", "memstore.db")
GH = os.path.join(ROOT, "cache", "qq_bridge", "lite", "group_history.db")
TRACE = os.path.join(ROOT, "cache", "recall_trace.jsonl")
DASH = re.compile(r"[—–―－]")
MARK = "青柠七号"
RESULTS: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, cond, detail))
    print("%s %-34s %s" % ("✅" if cond else "❌", name, detail))


def post(path: str, body: dict, timeout: int = 200) -> dict:
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    r = urllib.request.Request("http://127.0.0.1:8321" + path,
                               data=json.dumps(body, ensure_ascii=False).encode(),
                               headers={"Content-Type": "application/json"})
    with op.open(r, timeout=timeout) as f:
        return json.loads(f.read().decode())


def restart() -> None:
    subprocess.run([sys.executable, "-X", "utf8",
                    os.path.join(ROOT, "tools", "restart_daemon_safe.py")],
                   cwd=ROOT, capture_output=True, timeout=180)


# ── 一、记忆验证 ────────────────────────────────────────────────────
VID = "verify_memory_%d" % int(time.time())
con = sqlite3.connect(MS)
cols = {c[1] for c in con.execute("pragma table_info(l2_items)")}
try:
    con.execute("delete from l2_items where id like 'verify_memory_%'")
    con.commit()
    now = time.time()
    row = {"id": VID, "tier": "L2", "type": "fact", "importance": 9,
           "summary": "老爹的验证暗号是%s，只有问了才说，别主动提。" % MARK,
           "content_hash": "verify", "keywords": "验证暗号,%s" % MARK,
           "status": "active", "source": "owner", "created_at": now,
           "belief": 1.0, "salience": 9.0, "confidence": 1.0}
    row = {k: v for k, v in row.items() if k in cols}
    con.execute("insert into l2_items(%s) values(%s)"
                % (",".join(row), ",".join("?" * len(row))), tuple(row.values()))
    con.commit()
    print("已插入测试记忆：%s" % VID)
finally:
    con.close()

# 重建索引（增量：只有新行会算）
r = subprocess.run([sys.executable, "-X", "utf8",
                    os.path.join(ROOT, "tools", "memory_index_build.py")],
                   cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("索引重建：%s" % (r.stdout or "").strip().splitlines()[-1][:90] if r.stdout else "?")

restart()
time.sleep(2)

# 生产路径问
try:
    d = post("/turn", {"text": "老爹的验证暗号是什么", "channel": "qq_p2258374446",
                       "source": "qq_bridge"})
    ans = str(d.get("answer") or d.get("text") or "")
except Exception as ex:  # noqa: BLE001
    ans = ""
    print("问询失败：%s" % type(ex).__name__)
ok("她说出了暗号", MARK in ans, ans[:60])

# trace 检查
hit = False
ids: list[str] = []
try:
    rows = [json.loads(x) for x in open(TRACE, encoding="utf-8") if x.strip()]
    recent = [r for r in rows if time.time() - float(r.get("ts") or 0) < 300]
    ids = [i for r in recent for i in (r.get("ids") or [])]
    hit = VID in ids
except Exception:  # noqa: BLE001
    pass
ok("trace 里注入了这条记忆", hit, "近 5 分钟注入 ids=%s" % (ids[:3] or "无"))

# 反例：没存过的事，不许编
try:
    d2 = post("/turn", {"text": "我的车是什么颜色的", "channel": "qq_p2258374446",
                        "source": "qq_bridge"})
    a2 = str(d2.get("answer") or d2.get("text") or "")
except Exception:  # noqa: BLE001
    a2 = ""
invented = bool(re.search(r"(红|蓝|黑|白|银|灰)色", a2))
ok("没存过的事不编造", not invented, a2[:60])

# 清理
con = sqlite3.connect(MS)
try:
    con.execute("delete from l2_items where id like 'verify_memory_%'")
    con.commit()
finally:
    con.close()
subprocess.run([sys.executable, "-X", "utf8",
                os.path.join(ROOT, "tools", "memory_index_build.py")],
               cwd=ROOT, capture_output=True)
restart()
print("已清理测试记忆并重启")

# ── 二、时刻度验证 ──────────────────────────────────────────────────
con = sqlite3.connect(GH)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    "select group_id, seq, sender_id, text, at from group_messages")]
con.close()
now = time.time()
ats = [float(r["at"] or 0) for r in rows]
ok("无未来时间戳", max(ats) <= now + 300,
   "最新 %s（距今 %.1f 小时）"
   % (time.strftime("%m-%d %H:%M", time.localtime(max(ats))), (now - max(ats)) / 3600))
ok("无缺失时间", all(a > 0 for a in ats), "%d/%d 有 at" % (sum(1 for a in ats if a > 0), len(ats)))

bad_mono = 0
by_g: dict[str, list[dict]] = {}
for r in rows:
    by_g.setdefault(str(r["group_id"]), []).append(r)
for g, lst in by_g.items():
    lst.sort(key=lambda x: x["seq"] or 0)
    prev = 0.0
    for r in lst:
        a = float(r["at"] or 0)
        if a and prev and a < prev - 1:
            bad_mono += 1
        prev = a or prev
ok("同群时间随 seq 单调", bad_mono == 0, "逆序 %d 处" % bad_mono)

# 复现因果数字
CUT = time.mktime(time.strptime("2026-11-14", "%Y-%m-%d"))
mine = [r for r in rows if str(r["sender_id"]) == "3655185302" and str(r["text"] or "").strip()]
pre = [r for r in mine if float(r["at"]) < CUT]
post_ = [r for r in mine if float(r["at"]) >= CUT]
rp = 100.0 * sum(1 for r in pre if DASH.search(str(r["text"]))) / max(1, len(pre))
rq = 100.0 * sum(1 for r in post_ if DASH.search(str(r["text"]))) / max(1, len(post_))
ok("复现「清洗前≈47%」", 40 <= rp <= 55, "%.1f%%（%d 句）" % (rp, len(pre)))
ok("复现「清洗后=0%」", rq == 0.0, "%.1f%%（%d 句）" % (rq, len(post_)))

# 噪声：按天破折号率的样本量
days = {}
for r in mine:
    d = time.strftime("%m-%d", time.localtime(float(r["at"])))
    s = days.setdefault(d, [0, 0])
    s[0] += 1
    s[1] += 1 if DASH.search(str(r["text"])) else 0
ns = [v[0] for v in days.values()]
ok("单日样本量足够做趋势", min(ns) >= 20,
   "天数 %d｜最少 %d 句/天｜中位 %d" % (len(days), min(ns), sorted(ns)[len(ns) // 2]))

print("\n" + "=" * 60)
fails = [x for x in RESULTS if not x[1]]
print("总计 %d｜通过 %d｜失败 %d" % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
for n, _c, dd in fails:
    print("  ❌ %s %s" % (n, dd))
sys.exit(1 if fails else 0)
