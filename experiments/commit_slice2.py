# -*- coding: utf-8 -*-
"""提交工作站第二片（提示词版本/回滚 + 逐题对拍 + 台账分家）。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
MSG = os.path.join(ROOT, "cache", "cm_slice2.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "feat(workbench): 第二片——提示词版本/回滚、逐题对拍、台账分家\n\n"
    "① 提示词版本/回滚（1256）\n"
    "- backend/prompt_versions.py：每次保存后快照整份 overrides 到\n"
    "  config/prompt_overrides.history/，带 index.jsonl；保留最近 200 份\n"
    "- 接口：GET /api/prompt_versions、POST /api/prompt_restore、POST /api/prompt_snapshot\n"
    "- 卡：提示词历史（列快照 + 回滚，支持单块/整份）\n"
    "- 修了一个设计错：快照原本存在改前，回滚等于回滚成「还没改」；改为改后存\n\n"
    "② 逐题对拍（1257）\n"
    "- backend/eval_compare.py：A旧/B新 → 修好/新挂/持续失败，带题目原文\n"
    "- 接口 GET /api/eval_compare；一键评测卡里加「与上一版对拍」\n"
    "- 过滤掉 cache/eval_state.json 这类非评测文件（否则被当成 0/0 的版本）\n"
    "- 实测：云端_B重跑1 → wb_first，人格 126→126 但修好8/新挂8；群聊 71→72\n\n"
    "③ 台账分家（1258）\n"
    "- backend/ledger_views.py：元亨台账(任务/计划/成长，不含日记) / 项目台账(分页+只看元亨相关) / 日记\n"
    "- 接口：/api/ledger_her、/api/ledger_project、/api/ledger_diary\n"
    "- 卡：三本分开、颜色区分（橙/蓝/紫），默认只看元亨台账\n"
    "- 实测：项目台账 146 条（元亨相关 27）、日记 27KB\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-80:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-120:])
