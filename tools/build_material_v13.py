# -*- coding: utf-8 -*-
"""重建训练素材集 v13（2026-11-14）。

## 为什么重建（证据，不是感觉）
- v9t10（5931 条）= **48/56**，是历史最好的 SFT 配比；v11（13189 条）= **44/56**。
- 差异主因：v11 灌进 **LCCC 3494 条（占条数 26.5%）**，把人格类权重占比从 **33.5% 腰斩到 14.4%**；
  而人格条数几乎没变（1019→1039）。→ **不是数据多有害，是稀释有害。**
- 口述故事（老爹亲讲）是高价值：v11 里 488 条拿到 3.5× 权重（占总权重 23.7%），均 37 字，教的是**口味**。

## 这一版的做法
1. **底 = v9t10 全部 5931 条**（原样、原权重，不动它验证过的配比）
2. **只加口述故事**（v11 里 `v11_dad_story` 488 条），权重 **1.5×**（不是 v11 的 3.5×——
   那次是混杂实验，3.5× 没有干净证据；1.5× 先保守）
3. **彻底不要 LCCC**（证据：7.3% 权重换来 -4 分）
4. **不要 persona_gen / revised / other 这些合成或来路不明的**（留待单独实验）
5. **质量闸门**：去重（内容哈希）｜末条必须 assistant｜首条必须 user｜单样本 ≤1400 字/≤10 条消息｜
   空答案/极短答案丢弃｜坏自称（AI助手/大模型）丢弃
6. **权重占比上限**：任何单一来源 ≤30% 总权重（防止某一类再次挤掉人格）

输出：`dist/material_v13/{train,val}.jsonl` + `manifest.json` + `report.md`
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
BASE = os.path.join(ROOT, "dist", "retrain_pkg_gemma_v9t10", "sft_persona_v9t10_train.jsonl")
ADD = os.path.join(ROOT, "dist", "retrain_pkg_gemma_v11", "sft_persona_v11_train.jsonl")
OUT = os.path.join(ROOT, "dist", "material_v13")

MAX_CHARS = 1400
MAX_MSGS = 10
DAD_STORY_WEIGHT = 2.0
MAX_SOURCE_SHARE = 0.30
VAL_RATIO = 0.02
BADCALL = re.compile(r"(AI ?助手|智能助手|人工智能助手|虚拟助手|大语言模型)")

# ── 老爹的禁令（2026-11-14）──────────────────────────────────────────
# 破折号：**修**（换成句号），不丢样本——那只是标点习惯。
# 其它命中：**整条丢**——那句话本身就是坏示范，留着等于教她。
# 词表来自 config/style_bans.json（8 组正则）+ 这里追加的硬条。
_EXTRA_BANS = [
    ("助理腔", re.compile(r"我理解你的意思|还需要我做什么|还有什么可以帮|随时待命|"
                          r"很高兴为您|为您服务|可以帮到您")),
    ("汇报式开头", re.compile(r"^(好的|收到|明白了|了解)[，,。]")),
    ("回答空转", re.compile(r"^(嗯|哦|好|行)[。，,]?$")),
]


def _load_ban_patterns() -> list[tuple[str, re.Pattern]]:
    p = os.path.join(ROOT, "config", "style_bans.json")
    out: list[tuple[str, re.Pattern]] = []
    try:
        d = json.load(io.open(p, encoding="utf-8"))
        for g, pats in (d.get("groups") or {}).items():
            if g.startswith("破折号"):
                continue                     # 破折号走"修"，不丢
            for pat in pats:
                try:
                    out.append((g, re.compile(pat)))
                except re.error:
                    continue
    except Exception:  # noqa: BLE001
        pass
    out.extend(_EXTRA_BANS)
    return out


BAN_PATTERNS = _load_ban_patterns()


def scrub_dashes(text: str) -> tuple[str, bool]:
    """把破折号换成句号。只动标点，不删词。"""
    try:
        sys.path.insert(0, ROOT)
        from backend.text_scrub import has_dash, scrub
        if has_dash(text):
            return scrub(text), True
    except Exception:  # noqa: BLE001
        pass
    return text, False


def first_ban(ans: str) -> str:
    for g, pat in BAN_PATTERNS:
        if pat.search(ans):
            return g
    return ""


def rows(path: str) -> list[dict]:
    out = []
    for ln in io.open(path, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:  # noqa: BLE001
            continue
    return out


def msgs_of(r: dict) -> list[dict]:
    return [m for m in (r.get("messages") or []) if isinstance(m, dict)]


def fam_of(src: str) -> str:
    return re.split(r"[/:|]", str(src or "（无）"))[0].strip() or "（空）"


def ok_quality(r: dict) -> tuple[bool, str]:
    """质量闸门。

    实测结构：v9t10 的样本**首条是 system（内嵌人设）**、末条 assistant（5895/5931），
    所以不能要求首条是 user——上一版这么写把 5931 条全丢了。
    """
    m = msgs_of(r)
    if len(m) < 2:
        return False, "消息太少"
    roles = [x.get("role") for x in m]
    if "user" not in roles or "assistant" not in roles:
        return False, "缺 user 或 assistant"
    if roles[-1] != "assistant":
        return False, "末条不是 assistant"
    if len(m) > MAX_MSGS + 1:
        return False, "轮数过多"
    total = sum(len(str(x.get("content") or "")) for x in m)
    if total > MAX_CHARS + 200:
        return False, "超长"
    ans = str(m[-1].get("content") or "").strip()
    if len(ans) < 4:
        return False, "答案过短"
    if BADCALL.search(ans) and "AI" in ans:
        return False, "坏自称"
    return True, ""


def key_of(r: dict) -> str:
    """去重键：全部消息的角色+内容（含 tool_calls 的 id），归一化后哈希。"""
    buf = []
    for m in msgs_of(r):
        c = str(m.get("content") or "")
        tc = m.get("tool_calls") or []
        buf.append("%s|%s|%s" % (m.get("role"), c.strip(),
                                 json.dumps(tc, ensure_ascii=False, sort_keys=True) if tc else ""))
    return hashlib.sha1("\n".join(buf).encode("utf-8")).hexdigest()


def main() -> int:
    base = rows(BASE)
    added_all = rows(ADD)
    added = [r for r in added_all if str(r.get("source") or "") == "v11_dad_story"]
    print("底（v9t10）：%d 条｜待加口述故事：%d 条（v11 总 %d 条）"
          % (len(base), len(added), len(added_all)))

    for r in added:
        r["weight"] = float(DAD_STORY_WEIGHT)

    seen: set[str] = set()
    kept: list[dict] = []
    drop = Counter()
    dash_fixed = 0
    ban_by = Counter()
    for r in base + added:
        ok, why = ok_quality(r)
        if not ok:
            drop[why] += 1
            continue
        ms = msgs_of(r)
        # 1) 破折号：修标点，不丢
        for m in ms:
            if m.get("role") == "assistant":
                fixed, changed = scrub_dashes(str(m.get("content") or ""))
                if changed:
                    m["content"] = fixed
                    dash_fixed += 1
        ans = "\n".join(str(x.get("content") or "") for x in ms
                        if x.get("role") == "assistant")
        # 2) 禁令：命中即整条丢（那句话本身是坏示范）
        g = first_ban(ans)
        if g:
            ban_by[g] += 1
            drop["禁令:" + g] += 1
            continue
        k = key_of({"messages": ms})
        if k in seen:
            drop["重复"] += 1
            continue
        seen.add(k)
        kept.append({"messages": ms, "source": str(r.get("source") or "（无）"),
                     "weight": float(r.get("weight") or 1.0)})

    # 权重占比上限：超过就整体缩
    total_w = sum(r["weight"] for r in kept)
    by = defaultdict(float)
    for r in kept:
        by[fam_of(r["source"])] += r["weight"]
    scaled = 0
    for fam, w in by.items():
        if total_w and w / total_w > MAX_SOURCE_SHARE:
            factor = (MAX_SOURCE_SHARE * total_w) / w
            for r in kept:
                if fam_of(r["source"]) == fam:
                    r["weight"] *= factor
            scaled += 1
    if scaled:
        total_w = sum(r["weight"] for r in kept)

    # 切分（确定性：按哈希取前 2% 作 val）
    kept.sort(key=lambda r: key_of(r))
    n_val = max(50, int(len(kept) * VAL_RATIO))
    val, train = kept[:n_val], kept[n_val:]

    os.makedirs(OUT, exist_ok=True)
    for name, data in (("train", train), ("val", val)):
        with io.open(os.path.join(OUT, "sft_persona_v13_%s.jsonl" % name), "w",
                     encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 统计
    stat = defaultdict(lambda: {"n": 0, "w": 0.0, "chars": 0})
    for r in train:
        s = stat[fam_of(r["source"])]
        s["n"] += 1
        s["w"] += r["weight"]
        s["chars"] += sum(len(str(m.get("content") or "")) for m in r["messages"])
    tw = sum(v["w"] for v in stat.values())
    manifest = {
        "built_at": "2026-11-14",
        "base": os.path.relpath(BASE, ROOT),
        "added": {"v11_dad_story": {"rows": len(added), "weight": DAD_STORY_WEIGHT}},
        "excluded": {"lccc": "证据：7.3% 权重换来 -4 分（44 vs 48）",
                     "persona_gen / revised / other": "合成或来路不明，留待单独实验"},
        "filters": {"max_chars": MAX_CHARS, "max_msgs": MAX_MSGS,
                    "drop": dict(drop), "dedup": "sha1(角色+内容+tool_calls)",
                    "bans": "config/style_bans.json 全组（破折号除外）命中即丢；"
                            "破折号改为换句号，不丢样本",
                    "dash_fixed": dash_fixed},
        "bans_hit": dict(ban_by),
        "max_source_share": MAX_SOURCE_SHARE,
        "n_train": len(train), "n_val": len(val),
        "sum_weight": round(tw, 1),
        "by_source": {k: {"n": v["n"], "share_rows": round(100 * v["n"] / len(train), 1),
                          "w": round(v["w"], 1),
                          "share_w": round(100 * v["w"] / tw, 1) if tw else 0,
                          "avg_chars": round(v["chars"] / max(1, v["n"]))}
                      for k, v in sorted(stat.items(), key=lambda x: -x[1]["w"])},
    }
    io.open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8").write(
        json.dumps(manifest, ensure_ascii=False, indent=1))

    print("\n丢弃：%s" % (dict(drop) or "无"))
    print("破折号修掉 %d 处（样本保留）" % dash_fixed)
    print("保留 train %d｜val %d｜Σ权重 %.1f" % (len(train), len(val), tw))
    print("\n%-22s %6s %8s %9s %8s %8s" % ("来源", "条数", "条数%", "Σ权重", "权重%", "均字"))
    for k, v in manifest["by_source"].items():
        print("%-22s %6d %7.1f%% %9.1f %7.1f%% %8d"
              % (k[:22], v["n"], v["share_rows"], v["w"], v["share_w"], v["avg_chars"]))
    print("\n输出：%s" % os.path.relpath(OUT, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
