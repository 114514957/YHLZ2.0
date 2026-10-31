"""R2 提示词消融 runner（一个进程只跑一个 arm，独立解释器）。

用法：
    .venv\\Scripts\\python.exe -B tools/persona_ablation.py \
        --arm both --ids u01,u09,u19,u21 --save cache/persona_ablation_both_pilot.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:  # 重定向控制台下 GBK 会对生僻字符崩溃（anchor 臂实测）
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ap = argparse.ArgumentParser()
ap.add_argument("--arm", required=True,
                choices=("current", "style", "anchor", "both", "final", "final2"))
ap.add_argument("--bank", choices=("unseen", "guard", "r4"), default="unseen")
ap.add_argument("--rep", type=int, default=1)
ap.add_argument("--ids", default="")
ap.add_argument("--save", required=True)
ap.add_argument("--base-url", default="http://127.0.0.1:8081/v1/chat/completions")
ap.add_argument("--expect-lora", default="yuanheng-v7b-lora.gguf")
ap.add_argument("--policy-mode", default="production")
args = ap.parse_args()

os.environ["YHLZ_PROMPT_ARM"] = args.arm  # 必须在导入 backend 前设置

from tools.persona_regression import run_live, save_answers  # noqa: E402
from tools.persona_unseen_bank import UNSEEN_BANK  # noqa: E402
from tools.persona_guard_bank import GUARD_BANK, MANIFEST_VERSION as GUARD_VERSION  # noqa: E402
from tools.persona_r4_bank import R4_BANK, MANIFEST_VERSION as R4_VERSION  # noqa: E402
from tools.persona_unseen_bank import MANIFEST_VERSION  # noqa: E402

MARK = {
    "自称-老娘": re.compile(r"老娘"),
    "自称-本小姐": re.compile(r"本小姐"),
    "自称-咱": re.compile(r"咱"),
    "口头禅": re.compile(r"好家伙|哎呦|哇哦|嘿嘿"),
    "口语-你猜/对吧": re.compile(r"你猜|对吧|是吧"),
    "傲娇-哼/才不": re.compile(r"哼|才不|少来"),
}
GENERIC = {
    "助手腔": re.compile(r"我理解你|建议你|希望能帮"),
    "加粗": re.compile(r"\*\*"),
    "编号列表": re.compile(r"(^|\n)\s*\d+[.、]\s"),
    "anchor复读": re.compile(r"还在学着成长为自己、学着理解和陪伴的那一个"),
}

if args.bank == "guard":
    bank, bank_version = list(GUARD_BANK), GUARD_VERSION
elif args.bank == "r4":
    bank, bank_version = list(R4_BANK), R4_VERSION
else:
    bank, bank_version = list(UNSEEN_BANK), MANIFEST_VERSION
if args.ids:
    want = {x.strip() for x in args.ids.split(",") if x.strip()}
    bank = [e for e in bank if e["id"] in want]
if args.rep > 1:
    bank = bank * args.rep

answers, env = asyncio.run(run_live(bank, base_url=args.base_url,
                                    expect_lora=args.expect_lora,
                                    policy_mode=args.policy_mode))
env["ablation_arm"] = args.arm
env["unseen_bank_version"] = bank_version
save_answers(Path(args.save), answers, version="v7b-r2-%s" % args.arm, env=env)

trained, generic = [], []
for it in answers:
    a = str(it.get("answer") or "")
    for k, p in MARK.items():
        if p.search(a):
            trained.append([it["id"], k])
    for k, p in GENERIC.items():
        if p.search(a):
            generic.append([it["id"], k])
print(json.dumps({"arm": args.arm, "n": len(answers),
                  "trained_hits": len(trained), "generic_hits": len(generic),
                  "trained": trained, "generic": generic}, ensure_ascii=False))
