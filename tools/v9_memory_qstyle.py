"""问句化记忆样本（ledger 0892）。

背景：现有 memory 样本的"问"其实是**记忆摘要陈述**（"从实践看，先摸清依赖…"），
答是短反应。老爹要「陈述式 + 问句式都要」，本脚本补**问句式**：

  对每块记忆（status=keep）：
    · key   = 摘要里的关键短语（前一分句，≤18 字）
    · 问句  = 6 种模板轮转（"你还记得…吗" / "…这事我跟你说过吧" / …）
    · 答    = 先复述事实（取摘要主干 30–60 字），再一句元亨口吻的反应（从原答案借语气）
  校验：答里必须含摘要里的一个实词（否则丢弃），保证"确实回答了"。

产出：data/finetune/memory_qstyle.jsonl（source=memory_qstyle，simulation/generated=true）
用法：python tools/v9_memory_qstyle.py [--per-block 2]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "素材" / "记忆样本_v2.1.md"
OUT = ROOT / "data" / "finetune" / "memory_qstyle.jsonl"

QT = ["你还记得{key}那事吗？", "{key}这事我跟你说过吧？",
      "我上次提的{key}，你还记得不？", "关于{key}，你还记得多少？",
      "问你个事，{key}还记得吗？", "还记得我以前说过{key}吗？"]
STOP = set("的了是在和就都而及与着或一个这那有也")


def key_of(summary: str) -> str:
    s = re.split(r"[，。；：,;:]", summary.strip())[0]
    s = re.sub(r"^(从|在|对|关于)", "", s)
    return s[:18]


def fact_of(summary: str) -> str:
    return re.split(r"[。！？]", summary.strip())[0][:60]


def tail_style(answer: str) -> str:
    """从原答案里取一句短反应（去掉问句/长解释）。"""
    a = re.sub(r"^[^，。！？]{0,6}[，,]", "", answer.strip())
    a = re.split(r"[。！？]", a)[0]
    return a[:24] if len(a) >= 4 else ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-block", type=int, default=2)
    args = ap.parse_args()
    random.seed(20261020)

    text = SRC.read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^## ", text)[1:]
    rows, kept_blocks, dropped = [], 0, 0
    for b in blocks:
        bid = b.splitlines()[0].strip()
        meta = dict(re.findall(r"(?m)^-\s*([a-z_]+):\s*(.+)$", b))
        if meta.get("status") != "keep":
            continue
        summary = (meta.get("summary") or "").strip()
        if len(summary) < 12:
            continue
        # 原答案用来借语气
        ans = ""
        m = re.search(r"###\s*元亨答\d+\s*\n(.+)", b)
        if m:
            ans = m.group(1).strip()
        key, fact = key_of(summary), fact_of(summary)
        if len(key) < 4:
            dropped += 1
            continue
        kept_blocks += 1
        for i in range(args.per_block):
            q = QT[(kept_blocks * args.per_block + i) % len(QT)].format(key=key)
            reply = f"记得。{fact}"
            st = tail_style(ans)
            if st:
                reply += f"。{st}"
            # 校验：答案必须含摘要里的实词
            toks = [w for w in re.findall(r"[\u4e00-\u9fa5]{2,}", summary)][:8]
            if not any(t in reply for t in toks):
                dropped += 1
                continue
            msgs = [{"role": "user", "content": q},
                    {"role": "assistant", "content": reply}]
            rows.append({"messages": msgs, "source": "memory_qstyle",
                         "source_id": f"mq#{bid}#{i}", "group_id": f"mq:{bid}",
                         "simulation": True, "generated": True,
                         "license": "own",
                         "content_hash": hashlib.sha256(
                             json.dumps(msgs, ensure_ascii=False).encode()).hexdigest()[:16]})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"blocks": kept_blocks, "rows": len(rows), "dropped": dropped,
                      "file": str(OUT.relative_to(ROOT))}, ensure_ascii=False))
    for r in rows[:4]:
        print("  Q:", r["messages"][0]["content"])
        print("   A:", r["messages"][1]["content"][:70])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
