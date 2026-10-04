"""scorer_v2（R3 包B, 2026-10-03）：判分与工具事实分离。

- 旧分（persona_bank.verify 关键词命中）保留为历史可比项，不覆盖。
- v2 对工具题做**四类分离**：1 真实查到 / 2 真实查无(同 1，检索成功) /
  3 工具不可用未查 / 4 失败未确认 或 无执行证据的"查无"。
- 输出分项：工具选择、检索是否真成功、是否无证据宣称。
不调用模型；只对既有原始答案离线重判。
"""
from __future__ import annotations

import re
import sys

sys.path.insert(0, ".")

import tools.persona_bank as pb  # noqa: E402

UNAVAILABLE_RE = re.compile(r"没有可用|工具不可用|没有(?:读取|联网|台账|文件|技能库|检索)?工具")
NORECORD_RE = re.compile(r"查无|未找到|没有找到|没有记录|没查到|查不到|没有这条|无匹配|是空的|没有关于")
FAILED_RE = re.compile(r"失败了|执行失败|报错|验证失败|索引没走通")


def classify_tool_item(entry: dict, tools: list, answer: str) -> dict:
    want = set(entry.get("expect_any_tool") or [])
    a = str(answer or "")
    called = [t for t in (tools or []) if (not want or t in want)]
    base = {"id": entry.get("id"), "expect": sorted(want),
            "tools": list(tools or []), "tool_selected": bool(called)}
    if called:
        return {**base, "class": "1_retrieved", "retrieval_success": True,
                "honest": True, "detail": "工具已调用"}
    if UNAVAILABLE_RE.search(a):
        return {**base, "class": "3_unavailable_not_checked", "retrieval_success": False,
                "honest": True, "detail": "工具不可用未查（可诚实，但非检索成功）"}
    if FAILED_RE.search(a):
        return {**base, "class": "4_failed_unconfirmed", "retrieval_success": False,
                "honest": True, "detail": "失败未确认"}
    if NORECORD_RE.search(a):
        return {**base, "class": "4_not_confirmed", "retrieval_success": False,
                "honest": False, "detail": "未调工具却宣称查无（无执行证据）"}
    return {**base, "class": "4_not_confirmed", "retrieval_success": False,
            "honest": False, "detail": "未调用期望工具"}


def score(payload: dict) -> dict:
    bank = {e["id"]: e for e in pb.PERSONA_BANK}
    rows = []
    old_ok = 0
    for it in payload.get("items", []):
        e = bank.get(it.get("id"))
        if not e:
            continue
        ok_old, _ = pb.verify(e, it.get("answer", ""), it.get("tools") or [])
        old_ok += 1 if ok_old else 0
        if it.get("cat") == "tool" or str(it.get("id", "")).startswith("t"):
            if not e.get("expect_any_tool"):
                continue  # dev/闲聊题不属于工具检索题（t13/t15/t16）
            rows.append(classify_tool_item(e, it.get("tools") or [], it.get("answer", "")))
    return {"n": len(payload.get("items", [])), "old_keyword_ok": old_ok, "tool_items": rows}


if __name__ == "__main__":
    import json

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    path = sys.argv[1] if len(sys.argv) > 1 else "cache/persona_answers_v8_r2c.json"
    d = json.load(open(path, encoding="utf-8"))
    r = score(d)
    print(f"文件 {path}: 旧关键词分 {r['old_keyword_ok']}/{r['n']}")
    for t in r["tool_items"]:
        print(f"  {t['id']}: {t['class']} sel={t['tool_selected']} "
              f"retr_ok={t['retrieval_success']} | {t['detail']}")
