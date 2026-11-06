# -*- coding: utf-8 -*-
"""v9t8 全量素材包：v9t7 + 全部未进包素材 + 两个补丁，一条不扔。

老爹 2026-11-06：「把已有的素材全用上吧」。
所以这一版的口径变了：
  · 不再按长度/问号收尾删样本（那是风格问题，最后用判据管，不靠砍数据）；
  · 只做格式清洗：剥掉 `[[at: …]]` / `[[reply: …]]` 平台标记、去首尾空白、回答为空的丢；
  · 按答案去重，避免同一句话重复训练。
来源：
  A. v9t7 包（6607 条）
  B. 素材里还没进包的问答（上次统计 287 条）
  C. supplement_v9t7（内部拒绝 + 群短答）
  D. identity_ai_patch_v9t8（身份 AI 问法）
"""
from __future__ import annotations

import glob
import hashlib
import io
import json
import os
import re
import shutil
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MAT = os.path.join(YH, "docs", "素材")
FT = os.path.join(YH, "data", "finetune")
SRC_PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
DST = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t8")
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
import mine_samples as M  # noqa: E402

SKIP = re.compile(r"_(压缩前|改名块头前|补称呼前)")
MARK = re.compile(r"\[\[(at|reply):[^\]]*\]\]\s*")


def read_jsonl(p):
    with io.open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def clean(t: str) -> str:
    return MARK.sub("", (t or "")).strip()


# ① 以 v9t7 为底
train = read_jsonl(os.path.join(SRC_PKG, "sft_persona_v9t7_train.jsonl"))
val = read_jsonl(os.path.join(SRC_PKG, "sft_persona_v9t7_val.jsonl"))
base = train + val
SYSTEM = next(m["content"] for m in base[0]["messages"] if m["role"] == "system")
print("底包 v9t7：%d 条" % len(base))

have_a = set()
for r in base:
    # 必须取**所有** assistant 轮：包里多是多轮样本，素材那句常在第一轮
    for m in r["messages"]:
        if m["role"] == "assistant":
            have_a.add(clean(m["content"])[:40])
have_h = {r.get("content_hash") for r in base}
print("已有答案前缀 %d 个" % len(have_a))


def mk(q, a, src, sid, weight=1.0):
    q, a = clean(q), clean(a)
    return {"messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": q},
                         {"role": "assistant", "content": a}],
            "source": src, "source_id": sid, "group_id": "%s:%s" % (src.split(":")[0], sid),
            "content_hash": hashlib.sha1((q + "\x00" + a).encode()).hexdigest()[:16],
            "safety_labels": "none", "consent_status": "n/a", "weight": weight,
            "annotator_exec": "agent:build_v9t8_full", "annotator_review": ""}


# ② 素材里所有还没进包的问答
new_rows, seen = [], set()
for p in sorted(glob.glob(os.path.join(MAT, "*.md"))):
    fn = os.path.basename(p)
    if SKIP.search(fn) or fn.startswith(("README", "素材清单")):
        continue
    for bid, blk in M.parse(p):
        for q, a in M.pairs(blk):
            q, a = clean(q), clean(a)
            if not a:
                continue
            if a[:40] in have_a or a[:40] in seen:
                continue
            seen.add(a[:40])
            new_rows.append(mk(q, a, "material_full:%s" % fn, bid, 0.8))
print("素材新增：%d 条（全部未进包的）" % len(new_rows))

# ③ 两个补丁
#    注意：补丁按 (问题, 答案) 去重，不按答案去重——
#    身份补丁的价值就是「同一句金句配新问法」，按答案去重会把它们全吃掉（上一版只剩 2 条）。
patch_rows = []
have_pair = set()
for r in base:   # 先用底包把已有问答对铺满，否则补丁里 82 条会原样重复一遍
    q = next((m["content"] for m in r["messages"] if m["role"] == "user"), "")
    a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1]
    have_pair.add((clean(q), clean(a)))
for name, w in (("supplement_v9t7.jsonl", 1.0), ("identity_ai_patch_v9t8.jsonl", 1.0)):
    p = os.path.join(FT, name)
    if not os.path.exists(p):
        continue
    n0 = len(patch_rows)
    for r in read_jsonl(p):
        q = next(m["content"] for m in r["messages"] if m["role"] == "user")
        a = [m["content"] for m in r["messages"] if m["role"] == "assistant"][-1]
        key = (clean(q), clean(a))
        if key in have_pair:
            continue
        have_pair.add(key)
        patch_rows.append(mk(q, a, str(r.get("source", name)), str(r.get("source_id", "")), w))
    print("补丁 %-32s +%d" % (name, len(patch_rows) - n0))

added = new_rows + patch_rows
print("合计新增：%d 条" % len(added))

# ④ 90/10 切分，按行序轮转（避免同源整组进 val）
add_train = [r for i, r in enumerate(added) if i % 10 != 9]
add_val = [r for i, r in enumerate(added) if i % 10 == 9]
final_train = train + add_train
final_val = val + add_val

os.makedirs(DST, exist_ok=True)
os.makedirs(os.path.join(DST, "config"), exist_ok=True)
for fn, data in (("sft_persona_v9t8_train.jsonl", final_train),
                 ("sft_persona_v9t8_val.jsonl", final_val)):
    with io.open(os.path.join(DST, fn), "w", encoding="utf-8") as f:
        for r in data:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
for fn in ("finetune_train.py",):
    shutil.copy2(os.path.join(SRC_PKG, fn), os.path.join(DST, fn))
shutil.copy2(os.path.join(SRC_PKG, "config", "finetune.gemma4.v9t7lora.json"),
             os.path.join(DST, "config", "finetune.gemma4.v9t8lora.json"))

cfg = json.load(io.open(os.path.join(DST, "config", "finetune.gemma4.v9t8lora.json"),
                        encoding="utf-8"))
cfg["train_file"] = "/root/yh/retrain_pkg_gemma_v9t8/sft_persona_v9t8_train.jsonl"
cfg["val_file"] = "/root/yh/retrain_pkg_gemma_v9t8/sft_persona_v9t8_val.jsonl"
cfg["output_dir"] = "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-v9t8"
cfg["_说明"] = "gemma v9t8：全量素材（v9t7 + 未进包 287 + 两个补丁），超参与 v9t7 一致"
json.dump(cfg, io.open(os.path.join(DST, "config", "finetune.gemma4.v9t8lora.json"),
                       "w", encoding="utf-8"), ensure_ascii=False, indent=2)

src = Counter(str(r.get("source", "")).split(":")[0] for r in added)
manifest = {"version": "v9t8", "base": "retrain_pkg_gemma_v9t7",
            "added": {"material_full": len(new_rows), "patches": len(patch_rows),
                      "total": len(added), "by_source": dict(src)},
            "train": len(final_train), "val": len(final_val),
            "note": "老爹「把已有的素材全用上」：只做格式清洗，不按长度/问号删样本"}
json.dump(manifest, io.open(os.path.join(DST, "MANIFEST.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

print("\n包 → %s" % DST)
print("train %d（+%d）｜val %d（+%d）｜合计 %d"
      % (len(final_train), len(add_train), len(final_val), len(add_val),
         len(final_train) + len(final_val)))
print("新增来源：%s" % dict(src))
