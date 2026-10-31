#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 tool_use_v8.jsonl 里失效的 qq_* 工具映射到现行注册表。

2026-10-20 老爹选「重新映射」。
背景：backend/target_scheduler_tools.py 于今日 20:01 删掉 8 个 qq_* 工具，
      QQ 链操作降为**技能**（docs/技能库/QQ知识捕获工作流.md），
      现行 35 个工具里只剩 report_qq_weekly。

两类分别处理：
  A. 真调用了旧工具的 103 条 → 按语义映射，并改写参数与返回值形状
  B. 只声明了旧工具、调用合法的 380 条 → **只清理声明列表**，调用一律不动

映射表（语义依据见 docs 报告）：
  qq_status                        → runtime_status      （都是只读查状态）
  qq_digest / qq_summarize         → report_qq_weekly    （都是汇总成文档）
  qq_process                       → kb_add              （都是把抽取的知识入库）
  qq_bootstrap/qq_shutdown/
  qq_export/qq_runbatch            → skill_search        （链操作已降为技能，先查流程）

用法：
    python tools/v9_remap_qq_tools.py --dry-run
    python tools/v9_remap_qq_tools.py --apply
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

MAP = {
    # 2026-10-20 老爹定「qq导出就是工具，要做」之后，先恢复了 export，
    # 又恢复 status/process/digest/summarize（它们只读本地文件与知识库，
    # Lite 模式下同样能跑）→ 这 5 个**工具名不变**，原记录本来就对，
    # 只需清理参数里已不存在的字段，不用改名、不用改答案、不用改返回值。
    # 只剩真依赖 NapCat/QCE 链的 3 个映射到 skill_search。
    "qq_bootstrap": "skill_search",
    "qq_shutdown": "skill_search",
    "qq_runbatch": "skill_search",
}

# 工具名没变、语义没变 → 调用与答案原样保留，只清洗参数
RESTORED = {"qq_export", "qq_status", "qq_process", "qq_digest", "qq_summarize"}

# 这些映射后**回答不需要重写**：工具语义没变，原答案仍然成立。
KEEP_ANSWER = set()

# 旧工具 → skill_search 的检索词
QUERY = {
    "qq_bootstrap": "启动QQ知识捕获链路",
    "qq_shutdown": "关闭QQ知识捕获链路",
    "qq_export": "导出QQ群历史",
    "qq_runbatch": "批量处理QQ知识候选",
}

# 新工具的返回值形状（结构化、可信、与该工具真实语义一致）
RESULT = {
    "runtime_status": {"ok": True, "model_service": "online", "adapter": "online",
                       "trained": "unknown", "note": "无法核对的字段一律 unknown"},
    "report_qq_weekly": {"ok": True, "doc": "docs/报告/QQ技术周报.md", "days": 7},
    "kb_add": {"ok": True, "id": "kb-auto", "category": "tech"},
    "skill_search": {"ok": True, "skills": [{"name": "QQ知识捕获工作流",
                                              "trigger": "导出QQ群历史/启动捕获链",
                                              "path": "docs/技能库/QQ知识捕获工作流.md"}]},
    # qq.export 恢复为真工具后，返回 Lite 历史库导出的真实结构
    "qq_export": {"ok": True, "source": "lite_group_history",
                  "messages": 1234, "groups": 1,
                  "files": [{"group_id": "auto", "messages": 1234,
                             "file": "cache/qq_export/qq_export_auto.jsonl"}]},
}


def load_real_tools():
    from backend.target_scheduler_tools import openai_tools_view
    return {t["function"]["name"]: t for t in openai_tools_view()}


def adapt_result(old: str, oldres: dict) -> str:
    """把旧工具的结果改写成**恢复后工具的**真实输出形状，数字一律保留。

    2026-10-20：export/status/process/digest/summarize 已恢复成真工具，
    但它们的真实返回形状与旧记录不同（如 status 返回字符串、process 用 stored 不是 saved）。
    结果必须是新形状，否则同样是在教模型认错格式。
    """
    g = oldres or {}

    def num(*keys, default=0):
        for k in keys:
            v = g.get(k)
            if isinstance(v, (int, float)):
                return int(v)
        return default

    if old == "qq_status":
        return ("QQ 数据状态：白名单 %d 群｜候选 %d 条（待处理 %d）｜知识库 %d 条"
                % (num("whitelist_groups", "groups"),
                   num("candidates", "lines"),
                   num("pending"),
                   num("kb_count", "kb")))
    if old == "qq_process":
        return json.dumps({"processed": num("processed"),
                           "stored": num("saved", "stored", "stored_items"),
                           "lines": num("lines")}, ensure_ascii=False)
    if old == "qq_digest":
        p = g.get("path") or "docs/知识汇编/%s.md" % g.get("date", "")
        return "已生成日汇编：%s" % p
    if old == "qq_summarize":
        return json.dumps({"topics": num("topics"),
                           "source_items": num("source_items", "items"),
                           "file": g.get("file") or "docs/知识汇编/QQ-主题总结.md"},
                          ensure_ascii=False)
    if old == "qq_export":
        n = num("messages", "exported", "exported_msgs")
        return json.dumps({"ok": True, "source": "lite_group_history",
                           "messages": n, "groups": 1,
                           "files": [{"group_id": "resolved", "messages": n,
                                      "file": "cache/qq_export/qq_export.jsonl"}]},
                          ensure_ascii=False)
    return json.dumps(g, ensure_ascii=False)


def adapt_args(old: str, args, user_text: str):
    """按新工具 schema 造参数。"""
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except Exception:
            args = {}
    args = args or {}
    # qq.export 恢复为真工具：保留原 group_id，丢掉已不存在的 session_name，
    # 新 schema 是 group_id + limit（都可选）。
    if old == "qq_export":
        keep = {}
        if str(args.get("group_id") or "").strip().isdigit():
            keep["group_id"] = str(args["group_id"]).strip()
        return keep
    if old in QUERY:
        return {"query": QUERY[old], "limit": 5}
    if old == "qq_digest":
        return {"days": 7}
    if old == "qq_summarize":
        return {"days": 30}
    if old == "qq_process":
        return {"summary": "群聊里抽出来的技术要点",
                "detail": "从待处理候选里筛选并抽取的技术知识条目",
                "category": "tech", "source": "qq_group"}
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="data/finetune/tool_use_v8_remapped.jsonl")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    real = load_real_tools()
    rows = [json.loads(x) for x in io.open("data/finetune/tool_use_v8.jsonl",
                                           encoding="utf-8") if x.strip()]
    print("读入 %d 条，注册表 %d 个工具" % (len(rows), len(real)))

    stat = {"A_mapped": 0, "R_restored": 0, "B_declfix": 0, "C_clean": 0,
            "D_still_bad": 0}
    out = []
    for r in rows:
        r = json.loads(json.dumps(r))  # 深拷贝
        # 1) 先清声明：只留现行工具
        decl = r.get("tools") or []
        new_decl = [t for t in decl if (t.get("function") or {}).get("name") in real]
        had_stale_decl = len(new_decl) != len(decl)
        if new_decl:
            r["tools"] = new_decl
        else:
            r.pop("tools", None)

        # 2) 处理真实调用
        mapped = False
        for m in r.get("messages") or []:
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                old = fn.get("name")
                # 2a) 已恢复的工具：名字不变，只清洗新 schema 里不存在的参数
                if old in RESTORED:
                    raw = fn.get("arguments")
                    if isinstance(raw, dict):
                        args = dict(raw)
                    else:
                        try:
                            args = json.loads(raw or "{}")
                        except Exception:
                            args = {}
                    if not isinstance(args, dict):
                        args = {}
                    # 新 schema 没有 session_name 等旧键；顺手清掉多余键
                    changed = False
                    for k in list(args.keys()):
                        if k not in ("group_id", "hashed_id", "limit",
                                     "max_items", "date"):
                            args.pop(k)
                            changed = True
                    if changed:
                        fn["arguments"] = json.dumps(args, ensure_ascii=False)
                    # 结果形状按恢复后工具的真实输出改写（数字保留）
                    for mm in r.get("messages") or []:
                        if mm.get("role") == "tool" and mm.get("name") == old:
                            try:
                                ores = json.loads(mm.get("content") or "{}")
                            except Exception:
                                ores = {}
                            mm["content"] = adapt_result(old, ores)
                    r.setdefault("restored_tool", old)
                    continue
                # 2b) 仍被隐藏的 3 个 → skill_search
                if old not in MAP:
                    continue
                new = MAP[old]
                if new not in real:
                    stat["D_still_bad"] += 1
                    continue
                user_text = next((x.get("content") or "" for x in r["messages"]
                                  if x.get("role") == "user"), "")
                fn["name"] = new
                fn["arguments"] = json.dumps(adapt_args(old, fn.get("arguments"), user_text),
                                             ensure_ascii=False)
                # 打标记，供"改写收尾话"只处理真正映射过的记录。
                r["remapped_from"] = old
                mapped = True
            if m.get("role") == "tool" and m.get("name") not in RESTORED:
                nm = m.get("name")
                if nm in MAP:
                    new_nm = MAP[nm]
                    if nm == "qq_export":
                        # 2026-10-20：**保留原始条数**，只换返回形状。
                        # 原记录里答案说的是"一千二百八十条/512 条"，
                        # 若硬塞固定 1234 就会与答案矛盾（实测 3/3 全对不上）。
                        try:
                            oldres = json.loads(m.get("content") or "{}")
                        except Exception:
                            oldres = {}
                        cnt = (oldres.get("messages") or oldres.get("exported")
                               or oldres.get("exported_msgs") or 0)
                        res = {"ok": True, "source": "lite_group_history",
                               "messages": cnt, "groups": 1,
                               "files": [{"group_id": "resolved", "messages": cnt,
                                          "file": "cache/qq_export/qq_export.jsonl"}]}
                    else:
                        res = RESULT[new_nm]
                    m["name"] = new_nm
                    m["content"] = json.dumps(res, ensure_ascii=False)

        if mapped:
            stat["A_mapped"] += 1
        elif r.get("restored_tool"):
            stat["R_restored"] += 1
        elif had_stale_decl:
            stat["B_declfix"] += 1
        else:
            stat["C_clean"] += 1
        out.append(r)

    # 3) 复核：所有调用/声明都必须在注册表里
    bad = 0
    for r in out:
        for m in r.get("messages") or []:
            for tc in m.get("tool_calls") or []:
                if (tc.get("function") or {}).get("name") not in real:
                    bad += 1
            if m.get("role") == "tool" and m.get("name") not in real:
                bad += 1
        for t in r.get("tools") or []:
            if (t.get("function") or {}).get("name") not in real:
                bad += 1
    print("映射: R=%d 条（工具已恢复，原样保留）｜A=%d 条（改调用→skill_search）"
          "｜B=%d 条（只清声明）｜C=%d 条（本来就干净）｜无法映射 %d"
          % (stat["R_restored"], stat["A_mapped"], stat["B_declfix"],
             stat["C_clean"], stat["D_still_bad"]))
    print("复核残留非法引用: %d（应为 0）" % bad)

    if a.apply:
        io.open(a.out, "w", encoding="utf-8").write(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n")
        print("已写 ->", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
