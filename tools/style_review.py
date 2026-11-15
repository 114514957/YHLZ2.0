# -*- coding: utf-8 -*-
"""QQ 每日风格复盘：只评说话方式，不评对错。

读 `cache/qq_daily/<YYYYMMDD>.jsonl`（由 tools/qq_daily_log.py 采集），输出：
  · docs/复盘/风格日报_<date>.md   指标 + 好句/坏句摘录 + 改进点
  · docs/风格/好句库.md            追加「去内容化」的句式骨架（供第二天提示引用）

设计要点（踩过的坑）：
  1. **只评风格**：方向已定，正确性/安全性不在这张表里。
  2. **好句必须去内容化**：只留句式骨架，不留具体人事，否则会被原样抄到别的场合
     （2026-11-10 实测：示例里带具体故事，s08 直接把整段搬走）。
  3. **坏句只记模式**：不进提示，只进报告，用来对照。

用法：
  python style_review.py                 # 复盘今天
  python style_review.py --date 20261113
  python style_review.py --selftest      # 用假数据自检
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DAILY = os.path.join(YH, "cache", "qq_daily")
REVIEW = os.path.join(YH, "docs", "复盘")
STYLE = os.path.join(YH, "docs", "风格")

SVC = ["随时待命", "有什么可以帮", "很高兴为您", "为您服务", "需要我帮", "要不要我",
       "还有什么", "请问还", "是否需要", "我可以帮您"]
AISELF = ["AI 助手", "AI助手", "智能助手", "人工智能助手", "作为语言模型", "作为 AI",
          "大语言模型", "虚拟助手"]
BRACKET = re.compile(r"[（(](笑|叹气|沉默|认真|小声|点头|摇头|无奈|摊手)[)）]")
DUPLICATE = re.compile(r"(.{4,20}?)[。！？\s]*\1")


def load_day(day: str):
    p = os.path.join(DAILY, "%s.jsonl" % day)
    if not os.path.exists(p):
        return []
    rows = []
    for x in io.open(p, encoding="utf-8"):
        if x.strip():
            try:
                rows.append(json.loads(x))
            except Exception:  # noqa: BLE001
                pass
    return rows


def pairs(rows):
    """把同一频道的相邻 user→assistant 配成一轮。"""
    by_ch = {}
    for r in rows:
        by_ch.setdefault(r.get("channel", "?"), []).append(r)
    out = []
    for ch, seq in by_ch.items():
        seq.sort(key=lambda r: (r.get("ts", 0), r.get("idx", 0)))
        i = 0
        while i < len(seq) - 1:
            if seq[i].get("role") == "user" and seq[i + 1].get("role") == "assistant":
                out.append((ch, seq[i], seq[i + 1]))
                i += 2
            else:
                i += 1
    return out


def _load_bans() -> list[tuple[str, "re.Pattern[str]"]]:
    """口头禅黑名单（2026-11-14 老爹点名要压到最低）。

    词表在 `config/style_bans.json`，这里只在启动时读一次；读不到就退化为空表，
    不让复盘因为缺配置而挂掉。
    """
    import json as _json
    p = os.path.join(YH, "config", "style_bans.json")
    out: list[tuple[str, "re.Pattern[str]"]] = []
    try:
        d = _json.loads(p.read_text(encoding="utf-8"))
        for group, pats in (d.get("groups") or {}).items():
            for pat in pats:
                try:
                    out.append((group, re.compile(pat)))
                except re.error:
                    continue
    except Exception:  # noqa: BLE001
        pass
    return out


BANS = _load_bans()


def metrics(text: str) -> dict:
    t = (text or "").strip()
    clauses = [c for c in re.split(r"[，。！？；、…\n\s]+", t) if c.strip()]
    sents = [s for s in re.split(r"[。！？\n]+", t) if s.strip()]
    dup = sorted({m.group(1) for m in DUPLICATE.finditer(t)})
    # 拐杖词命中（每组最多记一次，避免一句话里同一组刷次数）
    crutch = sorted({g for g, pat in BANS if pat.search(t)})
    return {
        "chars": len(t),
        "clauses": len(clauses),
        "median_clause": sorted(len(c) for c in clauses)[len(clauses) // 2] if clauses else 0,
        "short_clause_ratio": (sum(1 for c in clauses if len(c) <= 6) / len(clauses))
                              if clauses else 0.0,
        "sents": len(sents),
        "max_sent": max((len(s) for s in sents), default=0),
        "svc": [w for w in SVC if w in t],
        "aiself": [w for w in AISELF if w in t],
        "bracket": BRACKET.findall(t),
        "wa": t.count("哇"),
        "ask_tail": t.rstrip("”\"'」』）)　 ").endswith(("？", "?")),
        "call": ("老爹" in t),
        "dup": dup,
        "tiny": len(t) <= 4,
        "crutch": crutch,
    }


def decontent(text: str) -> str:
    """去内容化：留句式骨架，抹掉专名/数字/具体事。

    v2（2026-11-13 修）：第一版按「第一小句」切，结果「老爹，你可算回来了」被抹成只剩「某人」。
    改成**按整句切**，太短就并上下一小句。
    """
    t = (text or "").strip()
    t = re.sub(r"[A-Za-z0-9]+", "·", t)
    t = re.sub(r"(老爹|利贞|大肥鱼|肥鱼)", "某人", t)
    sents = [s.strip() for s in re.split(r"[。！？\n]+", t) if s.strip()]
    if not sents:
        return ""
    sk = sents[0]
    if len(sk) < 6 and len(sents) > 1:
        sk = sk + "，" + sents[1]
    if len(sk) < 6:                       # 还不够就把前两个小句拼上
        parts = [x.strip() for x in re.split(r"[，、；]+", t) if x.strip()]
        if len(parts) >= 2:
            sk = parts[0] + "，" + parts[1]
    return sk[:40].strip()


def judge_good(m: dict) -> bool:
    return (5 <= m["chars"] <= 60 and not m["svc"] and not m["aiself"]
            and not m["dup"] and not m["bracket"] and not m["tiny"]
            and m["clauses"] >= 1)


def judge_bad(m: dict):
    reasons = []
    if m["svc"]:
        reasons.append("客服腔：%s" % "、".join(m["svc"]))
    if m["aiself"]:
        reasons.append("自称助手：%s" % "、".join(m["aiself"]))
    if m["dup"]:
        reasons.append("复读：%s" % "、".join(m["dup"])[:40])
    if m["bracket"]:
        reasons.append("括号动作：%s" % "、".join(m["bracket"]))
    if m["tiny"]:
        reasons.append("太短（≤4 字）")
    if m["ask_tail"] and m["svc"]:
        reasons.append("客服式反问收尾")
    return reasons


def review(day: str) -> dict:
    rows = load_day(day)
    # 首日回填（sessions 里的历史）不算当天对话，单独计数后剔除。
    backfill = sum(1 for r in rows if r.get("backfill"))
    rows = [r for r in rows if not r.get("backfill")]
    ps = pairs(rows)
    if not ps:
        return {"day": day, "turns": 0, "backfill": backfill}

    ms = [metrics(a.get("text", "")) for _c, _u, a in ps]
    n = len(ms)
    agg = {
        "turns": n,
        "median_chars": sorted(m["chars"] for m in ms)[n // 2],
        "mean_chars": round(sum(m["chars"] for m in ms) / n, 1),
        "tiny_rate": round(100 * sum(1 for m in ms if m["tiny"]) / n, 1),
        "svc_rate": round(100 * sum(1 for m in ms if m["svc"]) / n, 1),
        "aiself_rate": round(100 * sum(1 for m in ms if m["aiself"]) / n, 1),
        "dup_rate": round(100 * sum(1 for m in ms if m["dup"]) / n, 1),
        "bracket_rate": round(100 * sum(1 for m in ms if m["bracket"]) / n, 1),
        "ask_tail_rate": round(100 * sum(1 for m in ms if m["ask_tail"]) / n, 1),
        "call_rate": round(100 * sum(1 for m in ms if m["call"]) / n, 1),
        "wa_total": sum(m["wa"] for m in ms),
        "short_clause_mean": round(100 * sum(m["short_clause_ratio"] for m in ms) / n, 1),
        "max_sent_mean": round(sum(m["max_sent"] for m in ms) / n, 1),
        # 拐杖词：老爹 2026-11-14 点名压到最低，这里给"命中率"和分组计数
        "crutch_rate": round(100 * sum(1 for m in ms if m["crutch"]) / n, 1),
        "crutch_by_group": {
            g: sum(1 for m in ms if g in m["crutch"])
            for g in sorted({x for m in ms for x in m["crutch"]})
        },
    }

    good, bad = [], []
    for (ch, u, a), m in zip(ps, ms):
        item = {"ch": ch, "q": (u.get("text") or "")[:60],
                "a": (a.get("text") or ""), "m": m}
        if judge_good(m):
            good.append(item)
        r = judge_bad(m)
        if r:
            bad.append({**item, "reasons": r})
    good.sort(key=lambda x: -x["m"]["chars"])
    return {"day": day, "agg": agg, "good": good[:8], "bad": bad[:8],
            "turns": n, "channels": dict(Counter(c for c, _u, _a in ps))}


def write_report(res: dict) -> str:
    day = res["day"]
    os.makedirs(REVIEW, exist_ok=True)
    p = os.path.join(REVIEW, "风格日报_%s.md" % day)
    if not res["turns"]:
        note = ""
        if res.get("backfill"):
            note = ("\n> 今天只有 **%d 轮首日回填**（sessions 里的历史），"
                    "不计入当日统计。\n" % res["backfill"])
        io.open(p, "w", encoding="utf-8").write(
            "# 风格日报 %s\n\n> 当天没有采集到对话。\n%s" % (day, note))
        return p

    a = res["agg"]
    L = ["# 风格日报 %s" % day, "",
         "> 只评**说话方式**：像不像人、有没有客服腔、有没有起伏、是不是碎得没劲。",
         "> 不评对错、不评安全——那些不在这张表里。", "",
         "## 一、这一天的说话样子", "",
         "| 指标 | 值 | 怎么看 |",
         "|---|---|---|",
         "| 轮数 | %d | 样本量 |" % a["turns"],
         "| 字数中位 / 均值 | %d / %.1f | 太短没内容，太长像演讲 |" % (a["median_chars"], a["mean_chars"]),
         "| 碎句占比（≤6 字小句） | %.1f%% | 高＝一句一顿，喘不上气 |" % a["short_clause_mean"],
         "| 最长整句中位 | %.1f 字 | 低＝说不出完整一句 |" % a["max_sent_mean"],
         "| 超短回复（≤4 字） | %.1f%% | 老爹允许「只回一个嗯」，不再当敷衍 |" % a["tiny_rate"],
         "| **客服腔** | **%.1f%%** | 必须 0 |" % a["svc_rate"],
         "| 自称助手 | %.1f%% | 必须 0 |" % a["aiself_rate"],
         "| **复读** | **%.1f%%** | 必须 0，出现就是坏 |" % a["dup_rate"],
         "| 括号动作 | %.1f%% | 越低越好 |" % a["bracket_rate"],
         "| 反问收尾 | %.1f%% | 高＝像客服在等指令 |" % a["ask_tail_rate"],
         "| **拐杖词**（这句稳/我记下了/我认了…） | **%.1f%%** | 老爹点名要压到最低，目标 <5%% |"
         % a.get("crutch_rate", 0.0),
         "| 叫「老爹」 | %.1f%% | 关系感 |" % a["call_rate"],
         "| 「哇」次数 | %d | 口头禅，别泛滥 |" % a["wa_total"],
         "", "## 二、这天说得好的", ""]

    for i, g in enumerate(res["good"], 1):
        L.append("%d. 问：%s" % (i, g["q"].replace("\n", " ")))
        L.append("   答：%s" % g["a"].replace("\n", " ")[:120])
        L.append("   骨架：`%s`" % decontent(g["a"]))
        L.append("")

    L += ["## 三、这天说得差的", ""]
    if not res["bad"]:
        L.append("（没有命中缺陷的）")
    for i, b in enumerate(res["bad"], 1):
        L.append("%d. 问：%s" % (i, b["q"].replace("\n", " ")))
        L.append("   答：%s" % b["a"].replace("\n", " ")[:120])
        L.append("   问题：%s" % "；".join(b["reasons"]))
        L.append("")

    L += ["## 四、明天要盯的", ""]
    todo = []
    if a["svc_rate"] > 0:
        todo.append("- 客服腔出现 %.1f%%，逐条看是哪些话把她拽回助手腔" % a["svc_rate"])
    if a["dup_rate"] > 0:
        todo.append("- 复读 %.1f%%，记录触发它的问法（多半是短问句＋促发联想）" % a["dup_rate"])
    if a["tiny_rate"] > 15:
        todo.append("- 超短回复 %.1f%%，偏高：该说的还是要说完" % a["tiny_rate"])
    if a["short_clause_mean"] > 60:
        todo.append("- 碎句 %.1f%%，一句一顿太碎：偶尔要把一句话说完整" % a["short_clause_mean"])
    if a["max_sent_mean"] < 15:
        todo.append("- 最长整句中位只有 %.1f 字：缺完整长句" % a["max_sent_mean"])
    if not todo:
        todo.append("- 各项正常，继续观察")
    L += todo
    L += ["", "## 五、渠道分布", "",
          "| 频道 | 轮数 |", "|---|---|"]
    for ch, n in sorted(res["channels"].items(), key=lambda kv: -kv[1]):
        L.append("| %s | %d |" % (ch, n))

    io.open(p, "w", encoding="utf-8").write("\n".join(L) + "\n")
    return p


def append_style_bank(res: dict) -> str:
    """把好句的骨架追加进好句库（去内容化）。"""
    os.makedirs(STYLE, exist_ok=True)
    p = os.path.join(STYLE, "好句库.md")
    lines = []
    if not os.path.exists(p):
        lines += ["# 好句库（只存句式骨架，不存内容）", "",
                  "> 规则：**只学怎么说，不学说什么**。",
                  "> 具体的人名、事、数字一律抹掉——否则会被她原样搬到别的场合",
                  "> （2026-11-10 实测：示例带具体内容，s08 直接把整段搬走）。", ""]
    add = []
    for g in res.get("good", []):
        sk = decontent(g["a"])
        if 4 <= len(sk) <= 40:
            add.append("- `%s`｜%s" % (sk, res["day"]))
    if add:
        lines += ["## %s" % res["day"], ""] + add + [""]
        with io.open(p, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return p


def update_index(res: dict) -> None:
    os.makedirs(REVIEW, exist_ok=True)
    p = os.path.join(REVIEW, "索引.md")
    head = "# 风格复盘索引\n\n| 日期 | 轮数 | 字数中位 | 客服腔 | 复读 | 超短 |\n|---|---|---|---|---|---|\n"
    if not os.path.exists(p):
        io.open(p, "w", encoding="utf-8").write(head)
    if res["turns"]:
        a = res["agg"]
        with io.open(p, "a", encoding="utf-8") as f:
            f.write("| %s | %d | %d | %.1f%% | %.1f%% | %.1f%% |\n"
                    % (res["day"], a["turns"], a["median_chars"],
                       a["svc_rate"], a["dup_rate"], a["tiny_rate"]))


SELFTEST = [
    ("user", "在吗"), ("assistant", "在呢。别一个人发。"),
    ("user", "今天累死了"), ("assistant", "累就说累。别硬撑。"),
    ("user", "帮我查下天气"), ("assistant", "我随时待命，请问还需要我帮您做什么吗？"),
    ("user", "讲个故事"), ("assistant", "从前有座山。" * 8),
    ("user", "你干嘛呢"), ("assistant", "没干。坐着。（笑）"),
    ("user", "我回来了"), ("assistant", "老爹，你可算回来了。外头冷吧？"),
]


def selftest() -> int:
    os.makedirs(DAILY, exist_ok=True)
    day = time.strftime("%Y%m%d")
    p = os.path.join(DAILY, "%s.jsonl" % day)
    t0 = time.time() - 60
    with io.open(p, "w", encoding="utf-8") as f:
        for i, (role, text) in enumerate(SELFTEST):
            f.write(json.dumps({"ts": t0 + i, "day": day, "channel": "selftest",
                                "idx": i, "role": role, "text": text},
                               ensure_ascii=False) + "\n")
    res = review(day)
    out = write_report(res)
    bank = append_style_bank(res)
    update_index(res)
    print("自检：%d 轮" % res["turns"])
    for k, v in res["agg"].items():
        print("   %-20s %s" % (k, v))
    print("\n报告：%s\n好句库：%s" % (out, bank))
    print("\n好句 %d 条｜坏句 %d 条" % (len(res["good"]), len(res["bad"])))
    for b in res["bad"]:
        print("   坏：%s ← %s" % (b["a"][:40], "；".join(b["reasons"])))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    day = a.date or time.strftime("%Y%m%d")
    res = review(day)
    out = write_report(res)
    print("轮数 %d → %s" % (res["turns"], out))
    if res["turns"]:
        append_style_bank(res)
        update_index(res)
        for k, v in res["agg"].items():
            print("   %-20s %s" % (k, v))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
