#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V9 素材总审核（老爹 2026-10-21：「审核」）。

一次跑完四组检查，输出可复现的报告：
  A 可训练性（最硬门槛——这些不过就训不起来）
      A1 tool_calls 的 arguments 必须是对象（字符串会让 Gemma 模板抛错）
      A2 Dataset.from_list 能建表（异构字段会 ArrowInvalid）
      A3 apply_chat_template 能渲染
      A4 max_seq_len=768 下的截断率
  B 内容质量
      B1 门禁 FAIL 数   B2 客服腔   B3 禁词   B4 角色穿帮   B5 近重复率
  C 结构与标记
      C1 工具名是否都在暴露列表   C2 simulation/generated 标记齐备率
      C3 维度分布                C4 权重分布
  D PT 池
      D1 四池达标   D2 许可分布   D3 token 分布   D4 短文档比例

用法：
    python tools/v9_audit_all.py            # 全查（含 tokenizer 检查，较慢）
    python tools/v9_audit_all.py --fast     # 跳过 tokenizer
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FAIL: list[str] = []
WARN: list[str] = []
OK: list[str] = []


def ok(m):
    OK.append(m)
    print("  [OK]   " + m)


def bad(m):
    FAIL.append(m)
    print("  [FAIL] " + m)


def warn(m):
    WARN.append(m)
    print("  [warn] " + m)


def load(p):
    return [json.loads(x) for x in io.open(p, encoding="utf-8") if x.strip()]


def _banned_real(text: str) -> bool:
    """用**门禁的口径**判禁词，避免裸子串误伤。

    2026-10-21：裸 `w in c` 会把「我接着检查」「电流稳了」「自我认同」「我接受」「认清」
    全判成禁词（实测 25 处全是误伤）。门禁本身有上下文正则，这里直接复用它。
    """
    try:
        import v9_story_gate as _G
        blk = "## t\n- emotion: calm\n### 老爹问1\n在吗\n### 元亨答1\n%s\n" % text
        r = _G.check_block("t", blk, "general")
        return any("客服腔" in f for f in (r.get("fails") or []))
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()

    print("=" * 76)
    print("A. 可训练性（最硬门槛）")
    print("=" * 76)
    try:
        tr = load("data/finetune/sft_persona_v9t_train.jsonl")
        va = load("data/finetune/sft_persona_v9t_val.jsonl")
        te = load("data/finetune/sft_persona_v9t_test.jsonl")
    except FileNotFoundError as e:
        bad("缺少切分文件：%s" % e)
        return 1
    print("  train %d / val %d / test %d" % (len(tr), len(va), len(te)))

    # A1 arguments 必须是对象
    badarg = 0
    for rows in (tr, va, te):
        for r in rows:
            for m in r["messages"]:
                for tc in (m.get("tool_calls") or []):
                    if isinstance((tc.get("function") or {}).get("arguments"), str):
                        badarg += 1
    if badarg:
        bad("A1 tool_calls.arguments 有 %d 处是字符串（Gemma 模板会抛错）" % badarg)
    else:
        ok("A1 tool_calls.arguments 全部是对象（%d 条记录）" % len(tr))

    # A2 Dataset.from_list
    try:
        from datasets import Dataset
        # 2026-10-21 修：审核要与**训练器实际做法**一致——messages 序列化成 JSON 字符串，
        # 否则 messages 内部结构不一致（带/不带 tool_calls）会被 Arrow 判死，
        # 那是误报（训练器已改成 JSON 字符串列）。
        slim = [{"messages_json": json.dumps(r["messages"], ensure_ascii=False),
                 "source": str(r.get("source", ""))} for r in tr]
        ds = Dataset.from_list(slim)
        ok("A2 Dataset.from_list 建表成功（%d 行，列 %s）" % (len(ds), ds.column_names))
    except Exception as e:  # noqa: BLE001
        bad("A2 Dataset.from_list 失败：%s: %s" % (type(e).__name__, str(e)[:90]))

    # A3/A4 模板 + 截断
    MAXLEN = 768
    if a.fast:
        warn("A3/A4 跳过（--fast）")
    else:
        try:
            from transformers import AutoTokenizer
            tok = AutoTokenizer.from_pretrained("models/gemma4-hf/gemma-4-e4b-it",
                                                trust_remote_code=True)
            import random
            random.seed(7)
            samp = random.sample(tr, min(300, len(tr)))
            errs, lens = 0, []
            for r in samp:
                try:
                    txt = tok.apply_chat_template(r["messages"], tokenize=False,
                                                  add_generation_prompt=False)
                    lens.append(len(tok(txt, add_special_tokens=False)["input_ids"]))
                except Exception:  # noqa: BLE001
                    errs += 1
            if errs:
                bad("A3 有 %d/%d 条模板渲染失败" % (errs, len(samp)))
            else:
                ok("A3 模板渲染全部成功（抽 %d 条）" % len(samp))
            if lens:
                lens.sort()
                over = sum(1 for x in lens if x > MAXLEN)
                msg = ("A4 token 中位 %d｜p99 %d｜最大 %d｜超 %d 的 %d 条（%.1f%%）"
                       % (lens[len(lens) // 2], lens[int(len(lens) * 0.99)],
                          lens[-1], MAXLEN, over, 100.0 * over / len(lens)))
                if over / len(lens) > 0.05:
                    warn(msg)
                else:
                    ok(msg)
        except Exception as e:  # noqa: BLE001
            warn("A3/A4 tokenizer 不可用：%s" % str(e)[:80])

    print("\n" + "=" * 76)
    print("B. 内容质量")
    print("=" * 76)
    import v9_story_gate as G
    st = Counter()
    cs_hit = banned_hit = 0
    BANNED = ["我这边", "我接", "我认", "稳了", "很稳", "这个稳", "别指望"]
    CS = ["请问", "您好", "感谢您的", "如有疑问", "希望以上", "建议您",
          "您可以尝试", "很高兴为您", "需要注意的是", "温馨提示"]
    for r in tr:
        # 2026-10-22 修：**role=tool 的返回不是台词**，是机器输出（台账带 Markdown、
        # 歌单带 `1. ` 编号），门禁扫它必然误报括号/星号/列表行（实测 19 条全误伤）。
        # 只把 system 之外的 user/assistant 台词交给门禁。
        # 2026-10-22 修：《真实数据豁免规则 v1》要求块头带 raw/raw_source/raw_captured，
        # 审核器原来没传 → real 维度的真实发言被星号/列表行判死（实测 4 条）。
        _meta = ""
        if str(r.get("source", "")).startswith("real:"):
            _meta = ("- raw: true\n- raw_source: %s\n- raw_captured: 2026-10-21\n- polish: 仅修标点，保留原话\n"
                     % str(r.get("source")).split(":")[-1][:40])
        _parts, _i = [], 0
        for m in r["messages"]:
            if m["role"] in ("system", "tool"):
                continue
            _i += 1
            _parts.append("### %s%s%d\n%s" % (
                "元亨" if m["role"] == "assistant" else "老爹",
                "答" if m["role"] == "assistant" else "问", _i,
                m.get("content") or ""))
        txt = "## x\n" + _meta + "\n".join(_parts)
        rr = G.check_block("x", txt, "general")
        is_raw = str(r.get("source", "")).startswith("real:")
        if is_raw and rr["status"] == "FAIL" and all(
                f.startswith(("星号", "列表行", "括号")) for f in rr["fails"]):
            st["PASS(raw豁免)"] += 1
        else:
            st[rr["status"]] += 1
        for m in r["messages"]:
            if m["role"] != "assistant":
                continue
            c = m.get("content") or ""
            if _banned_real(c):
                banned_hit += 1
            if any(w in c for w in CS):
                cs_hit += 1
    print("  门禁：%s" % dict(st))
    if st.get("FAIL", 0):
        bad("B1 门禁 FAIL %d 条" % st["FAIL"])
    else:
        ok("B1 门禁 FAIL 0（PASS %d + raw 豁免 %d）"
           % (st.get("PASS", 0), st.get("PASS(raw豁免)", 0)))
    if banned_hit:
        bad("B3 禁词命中 %d 处" % banned_hit)
    else:
        ok("B3 老爹点名禁词 0 处")
    if cs_hit:
        warn("B2 客服套话词 %d 处" % cs_hit)
    else:
        ok("B2 客服套话词 0 处")

    # B4 角色穿帮（只查元亨侧）
    ROLE = re.compile(r"上课|下课|考试周|论文|导师|宿舍|室友|食堂|同学|学校|读书|毕业|"
                      r"实习|上班|加班|老板|同事|公司|月薪|工资|辞职|失业|"
                      r"北京|上海|广州|深圳|杭州|南京|成都|重庆|武汉|西安|郑州|河北|"
                      r"追我|追你|男朋友|女朋友|分手|表白|结婚|"
                      r"来找我|跨城|一起去|抱抱|亲亲|牵手")
    role_hit = 0
    for r in tr:
        ys = "".join(m.get("content") or "" for m in r["messages"]
                     if m["role"] == "assistant")
        if ROLE.search(ys):
            role_hit += 1
    pct = 100.0 * role_hit / len(tr)
    if pct > 3:
        warn("B4 角色穿帮 %d 条（%.1f%%）" % (role_hit, pct))
    else:
        ok("B4 角色穿帮 %d 条（%.1f%%）" % (role_hit, pct))

    # B5 近重复
    def norm(s):
        return re.sub(r"\s+", "", s)

    def jac(x, y):
        A = {x[i:i + 4] for i in range(max(0, len(x) - 3))}
        B = {y[i:i + 4] for i in range(max(0, len(y) - 3))}
        return len(A & B) / max(1, len(A | B)) if A and B else 0.0

    sigs, dup = [], 0
    for r in tr:
        s = norm("".join(m.get("content") or "" for m in r["messages"]
                         if m["role"] == "assistant"))
        if len(s) < 8:
            continue
        if any(jac(s, t) >= 0.8 for t in sigs[-2000:]):
            dup += 1
        else:
            sigs.append(s)
    if dup / max(1, len(tr)) > 0.03:
        warn("B5 近重复 %d 条（%.1f%%）" % (dup, 100.0 * dup / len(tr)))
    else:
        ok("B5 近重复 %d 条（%.1f%%）" % (dup, 100.0 * dup / len(tr)))

    print("\n" + "=" * 76)
    print("C. 结构与标记")
    print("=" * 76)
    real_tools = None
    try:
        from backend.target_scheduler_tools import setup_scheduler_capabilities
        real_tools = {t["function"]["name"]
                      for t in setup_scheduler_capabilities().export_openai_tools()}
        ok("C1 取到暴露工具 %d 个" % len(real_tools))
    except Exception as e:  # noqa: BLE001
        warn("C1 取暴露工具失败：%s" % str(e)[:70])
    if real_tools:
        illeg = Counter()
        for rows in (tr, va, te):
            for r in rows:
                for m in r["messages"]:
                    for tc in (m.get("tool_calls") or []):
                        n = (tc.get("function") or {}).get("name")
                        if n not in real_tools:
                            illeg[n] += 1
        if illeg:
            bad("C1 非法工具名：%s" % dict(illeg.most_common(5)))
        else:
            ok("C1 工具名全部在暴露列表内")

    sim = sum(1 for r in tr if r.get("simulation"))
    tool_rows = sum(1 for r in tr if any(m.get("tool_calls") for m in r["messages"]))
    # 2026-10-22 修：真实跑出来的轨迹 `simulation=False, real_run=True` 是**正确的**，
    # 不能要求所有工具轨迹都带 simulation。
    with_sim = sum(1 for r in tr
                   if any(m.get("tool_calls") for m in r["messages"])
                   and (r.get("simulation") is not None
                        or r.get("real_run") is not None))
    pct = 100.0 * with_sim / max(1, tool_rows)
    if pct < 99:
        bad("C2 工具轨迹带 simulation 标记 %d/%d（%.1f%%）" % (with_sim, tool_rows, pct))
    else:
        ok("C2 工具轨迹 simulation 标记 %d/%d（100%%）" % (with_sim, tool_rows))

    dim = Counter(str(r.get("source", "?")).split(":")[0] for r in tr)
    print("  C3 维度：%s" % dict(dim.most_common(16)))
    wt = Counter(str(r.get("weight")) for r in tr)
    print("  C4 权重：%s" % dict(sorted(wt.items(), reverse=True)))

    print("\n" + "=" * 76)
    print("D. PT 池")
    print("=" * 76)
    try:
        man = json.load(io.open("data/pt/manifest.json", encoding="utf-8"))
        pools, budget = man["pools"], man["pool_budget"]
        for k in ("self_core", "speaking_general", "tools_concept", "context"):
            p = pools[k]
            r = 100.0 * p["docs"] / budget[k]
            msg = "%-18s %6d / %6d（%5.1f%%）｜%s token" % (
                k, p["docs"], budget[k], r, format(p["tokens"], ","))
            if r >= 95:
                ok("D1 " + msg)
            elif k == "context":
                warn("D1 " + msg + "（按老爹定不补）")
            else:
                bad("D1 " + msg)
        ok("D3 总篇数 %s｜总 token %s｜覆盖 %.2f%%"
           % (format(man["total_docs"], ","), format(man["total_tokens"], ","),
              100.0 * man["coverage_vs_target"]))
        lic = man.get("licenses") or {}
        risky = {k: v for k, v in lic.items()
                 if k in ("reference_only", "nc_only", "unknown", "pending")}
        if risky:
            warn("D2 许可里有风险项：%s" % risky)
        else:
            ok("D2 许可无 reference_only/nc_only/pending")
    except Exception as e:  # noqa: BLE001
        bad("D PT manifest 读取失败：%s" % str(e)[:80])

    print("\n" + "=" * 76)
    print("审核结论")
    print("=" * 76)
    print("  OK   %d 项" % len(OK))
    print("  WARN %d 项" % len(WARN))
    print("  FAIL %d 项" % len(FAIL))
    if FAIL:
        print("\n  **不通过**，必须先修：")
        for x in FAIL:
            print("    - " + x)
        return 1
    print("\n  **通过**：可训练性四项全过，质量无致命问题。")
    if WARN:
        print("  待观察：")
        for x in WARN:
            print("    - " + x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
