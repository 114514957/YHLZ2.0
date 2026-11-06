# -*- coding: utf-8 -*-
"""真机自检：把本次入库的每个脚本都跑一遍。

规则：
  · 只读/幂等脚本：**真跑**，退出码 0 且声明的产物哈希不变 → PASS
  · 有副作用但非幂等（如 append_summary）：备份 → 跑 → 还原 → PASS
  · 需要云端凭据的：不跑，标 SKIP 并写明原因（它们此前已真跑过：上传/开训/拉取）
  · 需要起模型实例的：station 用 --dry-run 验证；eval/probe 已有 runs 记录
"""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = sys.executable
EXP = os.path.join(YH, "experiments")
WB = os.path.join(YH, "llm_workbench")


def sha(p):
    if not os.path.exists(p):
        return "-"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()[:12]


D7 = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
D8 = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t8")
FT = os.path.join(YH, "data", "finetune")
DOC = os.path.join(YH, "docs", "研究")

# (脚本, 工作目录, 参数, [产物...], 模式)
CASES = [
    # ── experiments ────────────────────────────────────────────
    ("station.py", EXP, ["run", "--config", "configs/merge82.json", "--dry-run"], [], "run"),
    ("summarize.py", EXP, [], [], "run"),
    ("inspect_adapters.py", EXP, [], [], "run"),
    ("check_s06.py", EXP, [], [], "run"),
    ("fix_configs.py", EXP, [], [os.path.join(EXP, "configs", "f1-82.json")], "idem"),
    ("make_pe1.py", EXP, [], [os.path.join(EXP, "configs", "pe1.json")], "idem"),
    ("make_pe2.py", EXP, [], [os.path.join(EXP, "configs", "pe2.json")], "idem"),
    ("fix_gitignore.py", EXP, [], [os.path.join(YH, ".gitignore")], "idem"),
    # ── llm_workbench：只读分析 ────────────────────────────────
    ("material_ledger.py", WB, [], [os.path.join(DOC, "素材总账_20261105.md")], "idem"),
    ("classify_material.py", WB, [], [os.path.join(DOC, "素材分类盘点_20261105.json")], "idem"),
    ("gap_detail.py", WB, [], [os.path.join(DOC, "缺口明细_20261105.json")], "idem"),
    ("gap_status.py", WB, [], [os.path.join(DOC, "缺口量化_20261106.json")], "idem"),
    ("find_selfdep.py", WB, [], [os.path.join(DOC, "包内自贬答案清单_20261105.json")], "idem"),
    ("pack_selfwords.py", WB, [], [], "run"),
    ("scan_identity_material.py", WB, [], [os.path.join(DOC, "身份类素材_全量盘点_20261105.md")], "idem"),
    ("mine_greet_flair.py", WB, [], [os.path.join(DOC, "寒暄创意候选_20261106.json")], "idem"),
    ("check_identity.py", WB, [], [], "run"),
    ("check_v9t8_quick.py", WB, [], [], "run"),
    ("inspect_v9t8.py", WB, [], [], "run"),
    ("verify_v9t8_new.py", WB, [], [], "run"),
    ("weight_postmortem.py", WB, [], [], "run"),
    ("write_catalog.py", WB, [], [os.path.join(DOC, "素材分类成册_20261106.md")], "idem"),
    ("guarantee_check.py", WB, [], [os.path.join(DOC, "质量保证清单_20261106.md")], "idem"),
    ("compare_v9t7.py", WB, [], [], "run"),
    # ── 有副作用：幂等校验 ─────────────────────────────────────
    ("build_v9t7_pack.py", WB, [],
     [os.path.join(D7, "sft_persona_v9t7_train.jsonl"),
      os.path.join(D7, "MANIFEST.json"),
      os.path.join(FT, "supplement_v9t7.jsonl")], "idem"),
    ("build_v9t8_full.py", WB, [],
     [os.path.join(D8, "sft_persona_v9t8_train.jsonl"),
      os.path.join(D8, "MANIFEST.json")], "idem"),
    ("rebuild_identity_ai_v2.py", WB, [],
     [os.path.join(FT, "identity_ai_patch_v9t8.jsonl")], "idem"),
    ("clean_patches.py", WB, [],
     [os.path.join(FT, "identity_ai_patch_v9t8.jsonl"),
      os.path.join(FT, "supplement_v9t7.jsonl")], "idem"),
    ("fix_svc_tone.py", WB, [], [os.path.join(D8, "sft_persona_v9t8_train.jsonl")], "idem"),
    ("archive_packs.py", WB, [],
     [os.path.join(FT, "_versions", "material_manifest.json")], "idem"),
    ("material_archive.py", WB, [], [], "run"),
    # ── 非幂等：备份→跑→还原 ──────────────────────────────────
    ("append_summary.py", WB, [], [os.path.join(DOC, "素材总账_20261105.md")], "restore"),
]

SKIP = [
    ("cloud_v9t7.py", "需要云端 SSH 凭据；本次会话已真跑（上传/开训/拉取）"),
    ("cloud_v9t8.py", "同上"),
    ("wait_v9t7.py", "同上（已实跑并收到 adapter）"),
    ("wait_v9t8.py", "同上"),
    ("collect_v9t7.py", "读本地产物，已在归集时跑过"),
    ("collect_v9t8.py", "同上（已生成 dist/v9t8_产物）"),
    ("finish_v9t7.py", "需要 adapter 已下载，已真跑"),
    ("finish_v9t8.py", "同上（校验+转 GGUF 已跑）"),
    ("eval_v9t7.py", "需模型实例，已真跑（56 题 + 群聊）"),
    ("eval_v9t8.py", "同上"),
    ("probe_one.py", "需模型实例，已真跑（s06/r07/r08 逐题）"),
    ("probe_identity.py", "同上（2 模型 × 2 提示词 × 2 问法）"),
    ("merge_lora.py", "需要 --a/--b 参数，已真跑两次（0.7/0.3 与 0.8/0.2）"),
    ("build_identity_ai_patch.py", "已被 rebuild_identity_ai_v2.py 取代（第一版立场错误）"),
    ("build_identity_ai_patch2.py", "同上"),
]

results = []


def run_case(script, cwd, args, outs, mode):
    p = os.path.join(cwd, script)
    if not os.path.exists(p):
        return script, "MISS", "文件不存在", 0
    before = {o: sha(o) for o in outs}
    bak = {}
    if mode == "restore":
        for o in outs:
            if os.path.exists(o):
                bak[o] = o + ".selftest.bak"
                shutil.copy2(o, bak[o])
    t0 = time.time()
    try:
        r = subprocess.run([PY, os.path.basename(p)] + args, cwd=cwd,
                           capture_output=True, text=True, timeout=600,
                           encoding="utf-8", errors="replace")
        rc = r.returncode
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        tail = tail[-1][:60] if tail else ""
    except subprocess.TimeoutExpired:
        rc, tail = -9, "超时"
    dt = time.time() - t0

    if mode == "restore":
        for o, b in bak.items():
            shutil.move(b, o)

    after = {o: sha(o) for o in outs}
    if rc != 0:
        return script, "FAIL", "exit=%s %s" % (rc, tail), dt
    if mode == "idem":
        diff = [o for o in outs if before[o] != after[o]]
        if diff:
            return script, "IDEM-✗", "产物变了: %s" % ",".join(os.path.basename(d) for d in diff), dt
        return script, "PASS", "幂等（%d 个产物哈希不变）" % len(outs), dt
    return script, "PASS", tail or "ok", dt


print("真机自检 %d 个脚本\n" % len(CASES))
for c in CASES:
    name, st, note, dt = run_case(*c)
    print("%-28s %-7s %5.1fs  %s" % (name, st, dt, note), flush=True)
    results.append((name, st, note))

print("\n跳过 %d 个（附原因）：" % len(SKIP))
for n, why in SKIP:
    print("  %-28s SKIP  %s" % (n, why))

bad = [r for r in results if r[1] not in ("PASS",)]
print("\n汇总：PASS %d / 问题 %d / SKIP %d"
      % (sum(1 for r in results if r[1] == "PASS"), len(bad), len(SKIP)))
if bad:
    print("有问题的：")
    for n, st, note in bad:
        print("  %-28s %-7s %s" % (n, st, note))
