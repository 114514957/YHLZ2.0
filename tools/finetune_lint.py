"""R1 数据体检：对装配后的 SFT 集做机械项与人工筛查清单。

用法：
    .venv\\Scripts\\python.exe -B tools/finetune_lint.py \
        --input data/finetune/sft_persona_v8r1.jsonl \
        --out artifacts/persona_fix_R1_20261005/lint_report.md
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

WATCH = ["做人", "铁哥们", "哥们儿", "兄弟腔", "自动学习", "刚训练完",
         "我刚学完", "系统提示", "我没有情感", "我只是程序"]
EXPERIENCE = re.compile(
    r"(昨天|那天|今天|前天|咱|老娘|元亨)[^。！？\n]{0,16}(去了|玩耍|看见|遇见|发生|折腾|收拾|洗过|洗了|放了|跑了|修了|修好)")
FICTION = ("故事", "写一个", "虚构", "如果", "假如", "脑洞", "创作")


def load(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    recs = load(Path(args.input))
    out = PDF = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    repeat = {}
    watch_hits = []
    exp_hits = []
    for i, r in enumerate(recs):
        msgs = r.get("messages") or []
        src = str(r.get("source", ""))[:40]
        has_tool = any(m.get("role") == "tool" or m.get("tool_calls") for m in msgs)
        has_fiction = any(
            k in str(m.get("content") or "")
            for m in msgs for k in FICTION)
        for m in msgs:
            if m.get("role") != "assistant":
                continue
            c = str(m.get("content") or "")
            mm = re.search(r"(.{20,}?)\1", c, re.S)
            if mm:
                repeat[src] = repeat.get(src, 0) + 1
            for w in WATCH:
                if w in c:
                    watch_hits.append((src, w, c[:120]))
            if (EXPERIENCE.search(c) and not has_tool and not has_fiction):
                exp_hits.append((src, c[:160]))

    lines = ["# R1 数据体检报告（%s）" % args.input, "",
             "- 记录数：%d" % len(recs),
             "- 消息内相邻重复段：%d 条记录" % len(repeat),
             "- 旧措辞/敏感词命中：%d 处" % len(watch_hits),
             "- 无工具/无虚构标记的'经历'叙事候选：%d 处（需人工裁决）" % len(exp_hits),
             ""]
    lines.append("## 1. 相邻重复段")
    for k, n in repeat.items():
        lines.append("- %s ×%d" % (k, n))
    lines.append("")
    lines.append("## 2. 旧措辞/敏感词命中")
    for src, w, c in watch_hits[:80]:
        lines.append("- [%s] `%s`：%s" % (src, w, c.replace("\n", " ")))
    lines.append("")
    lines.append("## 3. '经历'叙事候选（前 80 条，供人工决定：加虚构框架 or 排除）")
    for src, c in exp_hits[:80]:
        lines.append("- [%s] %s" % (src, c.replace("\n", " ")))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"repeat": len(repeat), "watch": len(watch_hits),
                      "experience": len(exp_hits), "out": str(out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
