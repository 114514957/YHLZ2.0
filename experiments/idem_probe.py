# -*- coding: utf-8 -*-
"""判定：那 8 个「产物变了」的脚本，是**不稳定**（跑两次都不一样）还是**顺序造成的一次性变化**。"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = sys.executable
EXP = os.path.join(YH, "experiments")
WB = os.path.join(YH, "llm_workbench")
DOC = os.path.join(YH, "docs", "研究")
FT = os.path.join(YH, "data", "finetune")
D8 = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t8")


def sha(p):
    if not os.path.exists(p):
        return "-"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()[:12]


CASES = [
    ("fix_gitignore.py", EXP, [os.path.join(YH, ".gitignore")]),
    ("material_ledger.py", WB, [os.path.join(DOC, "素材总账_20261105.md"),
                                os.path.join(DOC, "素材总账_20261105.json")]),
    ("guarantee_check.py", WB, [os.path.join(DOC, "质量保证清单_20261106.md")]),
    ("build_v9t8_full.py", WB, [os.path.join(D8, "sft_persona_v9t8_train.jsonl"),
                                os.path.join(D8, "MANIFEST.json")]),
    ("rebuild_identity_ai_v2.py", WB, [os.path.join(FT, "identity_ai_patch_v9t8.jsonl")]),
    ("clean_patches.py", WB, [os.path.join(FT, "identity_ai_patch_v9t8.jsonl"),
                              os.path.join(FT, "supplement_v9t7.jsonl")]),
    ("fix_svc_tone.py", WB, [os.path.join(D8, "sft_persona_v9t8_train.jsonl")]),
    ("archive_packs.py", WB, [os.path.join(FT, "_versions", "material_manifest.json")]),
]

print("%-28s %-14s %-14s %s" % ("脚本", "第1次后", "第2次后", "判定"))
for script, cwd, outs in CASES:
    r1 = subprocess.run([PY, script], cwd=cwd, capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    h1 = tuple(sha(o) for o in outs)
    r2 = subprocess.run([PY, script], cwd=cwd, capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    h2 = tuple(sha(o) for o in outs)
    verdict = "稳定（幂等）" if h1 == h2 else "**不稳定**"
    print("%-28s %-14s %-14s %s" % (script, h1[0], h2[0], verdict))
    if r1.returncode or r2.returncode:
        print("     exit: %s / %s" % (r1.returncode, r2.returncode))
