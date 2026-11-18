# -*- coding: utf-8 -*-
"""把「运行态」数据**直接渲染进 index.html**（不依赖任何 HTTP 接口）。

背景（2026-11-18 实测）：
  · daemon 的 /api/* 全部 404（请求被代理到 8090 的 FastAPI，返回 {"detail":"Not Found"}）；
  · 静态文件也只服务白名单（/console.css /console.js /ui.js /favicon.png）；
  → 于是新卡改成「生成时写死进页面」：index.html 里留两个标记，
    本脚本把渲染好的 HTML 片段替换进去，刷新页面即可看到真实数字。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PAGE = os.path.join(ROOT, "assets", "webui", "index.html")
START = "<!--STATUS_CARD_START-->"
END = "<!--STATUS_CARD_END-->"

sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))


def build() -> dict:
    import status_card_write as scw  # noqa: E402

    return scw.build()


def row(k: str, v, color: str = "") -> str:
    style = ' style="color:%s"' % color if color else ""
    return '<div>%s：<b%s>%s</b></div>' % (k, style, v)


def render(d: dict) -> str:
    out = []
    kg = d.get("kg") or {}
    if kg:
        emb = kg.get("with_emb") or 0
        docs = kg.get("docs") or 0
        out.append(row("段落 docs", docs))
        out.append(row("实体", kg.get("entities")))
        out.append(row("关系", kg.get("relations")))
        out.append(row("Episode", kg.get("episodes")))
        out.append(row("向量覆盖", "%d/%d" % (emb, docs),
                       "#2ecc71" if emb >= docs * 0.95 else "#e67e22"))
    else:
        out.append("—")
    kg_html = "".join(out)

    rec = d.get("recall") or {}
    if rec:
        p = rec.get("precision") or 0
        r = rec.get("recall") or 0
        rec_html = "".join([
            row("精确率", "%.1f%%" % (p * 100),
                "#2ecc71" if rec.get("pass_precision") else "#e74c3c"),
            row("命中率", "%.1f%%" % (r * 100),
                "#2ecc71" if rec.get("pass_recall") else "#e74c3c"),
            row("池子", rec.get("pool")),
            row("口径", "top-%s" % rec.get("limit")),
        ])
    else:
        rec_html = "—"

    sen = d.get("sentinel") or {}
    probs = sen.get("problems") or []
    m = sen.get("metrics") or {}
    if sen:
        sen_html = "".join([
            row("状态", "正常" if not probs else "%d 项异常" % len(probs),
                "#2ecc71" if not probs else "#e74c3c"),
            row("QQ", "在线" if m.get("qq_online") else "离线",
                "#2ecc71" if m.get("qq_online") else "#e74c3c"),
            row("能发消息", "是" if m.get("send_ok") else "否",
                "#2ecc71" if m.get("send_ok") else "#e74c3c"),
            row("群历史",
                ("%.0f 分钟前" % m["history_age_min"])
                if m.get("history_age_min") is not None else "—"),
        ])
        if probs:
            sen_html += ('<div style="color:#ff8b7b;font-size:12px">'
                         + "；".join(probs) + "</div>")
    else:
        sen_html = "—"

    return (START
            + '<div class="muted" style="font-size:12px;margin-bottom:6px">'
              '更新于 %s</div>' % (d.get("at") or "")
            + '<div class="grid3" style="display:grid;grid-template-columns:'
              'repeat(3,1fr);gap:10px">'
            + '<div><div class="muted" style="font-size:12px">记忆图谱 v2</div>'
              '<div style="font-size:13px;line-height:1.7">' + kg_html + "</div></div>"
            + '<div><div class="muted" style="font-size:12px">召回评测（最近一次）</div>'
              '<div style="font-size:13px;line-height:1.7">' + rec_html + "</div></div>"
            + '<div><div class="muted" style="font-size:12px">链路哨兵</div>'
              '<div style="font-size:13px;line-height:1.7">' + sen_html + "</div></div>"
            + "</div>"
            + END)


def main() -> int:
    d = build()
    html = io.open(PAGE, encoding="utf-8").read()
    if START not in html or END not in html:
        print("页面里没有 %s / %s 标记" % (START, END))
        return 1
    new = re.sub(re.escape(START) + r".*?" + re.escape(END),
                 render(d).replace("\\", r"\\"), html, count=1, flags=re.S)
    io.open(PAGE, "w", encoding="utf-8").write(new)
    print("已渲染进页面：docs=%s 精确率=%s 哨兵问题=%s"
          % ((d.get("kg") or {}).get("docs"),
             (d.get("recall") or {}).get("precision"),
             len((d.get("sentinel") or {}).get("problems") or [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
