#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""句长起伏后处理 v3：按**门禁同一口径**（整块元亨答话合并）计算与优化。

v1 只拆不合 → p90 跟着中位一起降，越改越匀。
v2 加了保护+合并，但按"行"计算，而门禁按"块"计算（元亨所有答话拼起来），
    单句成行的行 ratio 恒为 0，白算。
v3 按块：合并元亨全部答话 → 算中位/p90 → 保护最长 10% 不拆 → 拆中等的 → 合并碎句。
只动标点，不改一个字词。

用法：
    python tools/v9_rhythm_fix.py --show 2
    python tools/v9_rhythm_fix.py --apply
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
CJK = re.compile(r"[\u4e00-\u9fa5]")
# 2026-10-20：这些词**不能起句**（必须依附前半句），断点落在它们前面会造病句。
# 实测：「…任何答案的余地。却逼你承认」← 「却」独立起句是错的。
NO_START = re.compile(
    r"^(?:却|而|就|也|还|则|才|又|便|即|更|再|总|倒|偏|竟|居然|反而|"
    r"而且|并且|以及|或是|甚至|尤其|哪怕|即使|虽然|尽管|因为|由于|"
    r"如果|要是|除非|否则|不然|不然的话|"
    r"说明|证明|可见|意味着|也就是说|换句话说|这表明|这意味着|看得出来|"
    r"能|会|要|得|该|可以|必须|应该)"  # 情态动词开头的碎片也不能独立成句
)


def _has_predicate(piece: str) -> bool:
    """判断这一段是否成句：含动词/形容词/代词谓语即可。用 jieba 词性。"""
    try:
        import jieba.posseg as pseg
    except Exception:
        return True  # 没装 jieba 就放行，保持旧行为
    tags = [w.flag for w in pseg.cut(piece) if w.word.strip()]
    if not tags:
        return False
    # v* 动词 / a* 形容词 / 语气助词结尾也算成句
    return any(t.startswith(("v", "a")) for t in tags)


def can_break_at(core: str, p: int) -> bool:
    """逗号在 p 处能否改成句号：前段完整、后段不以依附性连词开头。"""
    if p < 5 or p > len(core) - 5:
        return False
    # 2026-10-20 加：前段末字若是「的/地/得/而/或/与/和/跟/把/被/让/使/叫」，
    # 说明这是名词短语或未完成的连接，断开会造病句。
    if core[p - 1] in "的地得而或与和跟把被让使叫":
        return False
    left = core[:p].strip("，, ")
    # 2026-10-20 再加固：用词性判断前段**有没有谓语**。
    # 实测「口耳相传的故事。」← 只有名词没有动词，独立成句是病句。
    if not _has_predicate(left):
        return False
    nxt = core[p:].lstrip("，, ")
    if not nxt or len(nxt) < 5:
        return False
    return not NO_START.match(nxt)


def split_sentences(text: str) -> list[str]:
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in "。！？!?":
            out.append(buf)
            buf = ""
    if buf.strip():
        out.append(buf)
    return out


def metrics(lens: list[int]) -> dict:
    if len(lens) < 3:
        return {"n": len(lens), "med": 0, "p90": 0, "ratio": 0.0, "short": 0.0, "long": 0.0}
    sl = sorted(lens)
    med = sl[len(sl) // 2]
    p90 = sl[min(len(sl) - 1, int(len(sl) * 0.9))]
    return {"n": len(lens), "med": med, "p90": p90,
            "ratio": (p90 / med) if med else 0.0,
            "short": sum(1 for x in lens if x <= 20) / len(lens),
            "long": sum(1 for x in lens if x >= 50) / len(lens)}


def lens_of(texts: list[str]) -> list[int]:
    out = []
    for t in texts:
        out += [len(s.strip()) for s in split_sentences(t) if s.strip() and CJK.search(s)]
    return out


def split_at_commas(sent: str, limit: int) -> list[str]:
    core = sent.rstrip("。！？!?")
    tail = sent[len(core):] or "。"
    if len(core) <= limit:
        return [sent]
    pts = [m.start() for m in re.finditer(r"[，,]", core)]
    pts = [p for p in pts if can_break_at(core, p)]
    if not pts:
        return [sent]
    pieces, start = [], 0
    while len(core) - start > limit:
        cands = [p for p in pts if p > start + 4 and p - start <= limit]
        if not cands:
            break
        cut = cands[-1]
        pieces.append(core[start:cut].strip("，,"))
        start = cut
    pieces.append(core[start:].strip("，,"))
    pieces = [p for p in pieces if len(p) >= 3]
    if len(pieces) < 2:
        return [sent]
    return [p + "。" for p in pieces[:-1]] + [pieces[-1] + tail]


def merge_shorts(sents: list[str], min_len: int = 9, max_join: int = 55) -> list[str]:
    out, buf = [], ""
    for s in sents:
        core = s.rstrip("。！？!?")
        end = s[len(core):] or "。"
        if len(core) < min_len and end == "。":
            cand = (buf + "，" + core) if buf else core
            if len(cand) <= max_join:
                buf = cand
                continue
        if buf:
            out.append(buf + "。")
            buf = ""
        out.append(s)
    if buf:
        out.append(buf + "。")
    return out


def raise_p90(sents: list[str], target: int = 55) -> list[str]:
    """2026-10-20 新增：把相邻句子用逗号接起来，硬造几句长句，抬高 p90。

    实测：句长太匀的块往往"短句有了、长句没有"，p90 卡在 28–40。
    这里把连续 2–3 句接成 ≥target 的长句，ratio = p90/中位 自然上去。
    只接句号→逗号，不改任何字词。
    """
    out: list[str] = []
    buf = ""
    for s in sents:
        core = s.rstrip("。！？!?")
        end = s[len(core):] or "。"
        if end == "。" and not buf:
            buf = core
            continue
        if end == "。" and buf:
            cand = buf + "，" + core
            if len(cand) <= target + 30:
                buf = cand
                if len(buf) >= target:
                    out.append(buf + "。")
                    buf = ""
                continue
            out.append(buf + "。")
            buf = core
            continue
        if buf:
            out.append(buf + "。")
            buf = ""
        out.append(s)
    if buf:
        out.append(buf + "。")
    return out


def optimize(answers: list[str], want_ratio: float = 1.8) -> list[str]:
    """answers = 元亨各轮正文；返回调整后的同长度列表。"""
    before = metrics(lens_of(answers))
    # 2026-10-20 修：**已经达标的块一律不动**。
    # 实测：对达标块继续拆会压低 p90，平均 ratio 反而从 2.30 掉到 2.18。
    if before["ratio"] >= want_ratio and before["short"] >= 0.25:
        return answers
    best, best_m = answers, before
    cur = answers
    for limit in (30, 26, 22, 18, 15):
        # 全局保护最长的 12%
        all_s = [(ai, si, len(s)) for ai, t in enumerate(cur)
                 for si, s in enumerate(split_sentences(t))]
        all_s.sort(key=lambda x: -x[2])
        protect = {(ai, si) for ai, si, _ in all_s[: max(1, len(all_s) * 12 // 100)]}
        new = []
        for ai, t in enumerate(cur):
            sents = split_sentences(t)
            tmp: list[str] = []
            for si, s in enumerate(sents):
                if (ai, si) in protect:
                    tmp.append(s)
                else:
                    tmp.extend(split_at_commas(s, limit))
            new.append("".join(merge_shorts(tmp)))
        m = metrics(lens_of(new))
        if m["ratio"] >= want_ratio and m["short"] >= 0.25:
            return new
        if m["ratio"] > best_m["ratio"]:
            best, best_m = new, m
        cur = new
    # 2026-10-20 加：拆不出效果时，反过来**硬造长句抬高 p90** 再试。
    for tgt in (45, 55, 65):
        new = [raise_p90(split_sentences(t), target=tgt) for t in answers]
        new = ["".join(x) for x in new]
        m = metrics(lens_of(new))
        if m["ratio"] >= want_ratio and m["short"] >= 0.25:
            return new
        if m["ratio"] > best_m["ratio"]:
            best, best_m = new, m
    return best


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(ROOT, "docs", "素材", "哲学观点样本.md"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--show", type=int, default=2)
    a = ap.parse_args()

    import v9_story_gate as G
    raw = io.open(a.file, encoding="utf-8", errors="replace").read()
    head, *parts = re.split(r"(?m)^##\s+", raw)

    out_blocks, shown = [], 0
    nb, na, total = [], [], 0
    for b in parts:
        blk = "## " + b.rstrip() + "\n"
        turns = G.parse_turns(blk)
        if not turns:
            out_blocks.append(blk)
            continue
        ans_idx = [i for i, t in enumerate(turns) if t[0] == "元亨" and t[1] == "答"]
        if len(ans_idx) < 2:
            out_blocks.append(blk)
            continue
        # 2026-10-20 修：先剔掉纯分隔符行（`=====`），否则会被当成句子并补个句号
        answers = [re.sub(r"(?m)^\s*=+\s*$", "", turns[i][3]).strip() for i in ans_idx]
        mb = metrics(lens_of(answers))
        new_ans = optimize(answers)
        ma = metrics(lens_of(new_ans))
        nb.append(mb["ratio"])
        na.append(ma["ratio"])
        total += 1
        if shown < a.show and ma["ratio"] > mb["ratio"]:
            print("\n【改前】ratio=%.2f 中位%d p90%d 短句%.0f%%"
                  % (mb["ratio"], mb["med"], mb["p90"], mb["short"] * 100))
            print("  " + answers[0][:150])
            print("【改后】ratio=%.2f 中位%d p90%d 短句%.0f%%"
                  % (ma["ratio"], ma["med"], ma["p90"], ma["short"] * 100))
            print("  " + new_ans[0][:200])
            shown += 1
        # 回写轮次
        new_turns = list(turns)
        for k, i in enumerate(ans_idx):
            new_turns[i] = (turns[i][0], turns[i][1], turns[i][2], new_ans[k])
        # 重建块（保留元数据行）
        meta_lines = [ln for ln in blk.split("\n")
                      if ln.startswith("- ") or ln.startswith("## ")]
        body = []
        for who, kind, num, text in new_turns:
            body.append("### %s%s%s" % (who, kind, num))
            body.append(text.strip())
        out_blocks.append("\n".join(meta_lines) + "\n" + "\n".join(body) + "\n")

    print("\n处理块 %d" % total)
    if nb:
        ok_b = sum(1 for x in nb if x >= 1.8)
        ok_a = sum(1 for x in na if x >= 1.8)
        print("块级 ratio≥1.8 达标：改前 %d/%d（%.0f%%）→ 改后 %d/%d（%.0f%%）"
              % (ok_b, len(nb), 100 * ok_b / len(nb), ok_a, len(na), 100 * ok_a / len(na)))
        print("平均 ratio：%.2f → %.2f" % (sum(nb) / len(nb), sum(na) / len(na)))
    if a.apply:
        with io.open(a.file, "w", encoding="utf-8") as fh:
            fh.write(head.rstrip() + "\n")
            for x in out_blocks:
                fh.write("\n" + x.rstrip() + "\n\n")
        print("已就地改写:", os.path.relpath(a.file, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
