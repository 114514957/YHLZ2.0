"""Rebuild 真实对话样本.md from the 小寻 QQ group export (spec dim A).

Replaces the whole file: one block per 元亨 message (33), user turn = the message
she replied to (quote) or the immediate preceding messages; answer = her text
(cleaned) or voice ASR transcript (marked in note).

Usage: python tools/real_qq_build.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.emotion_classifier import classify_emotion  # noqa: E402

BOT_MSGS = ROOT / "cache" / "tmp" / "qq_bot_msgs.json"
VOICE_ASR = ROOT / "cache" / "tmp" / "qq_voice_asr.json"
OUT = ROOT / "docs" / "素材" / "真实对话样本.md"
OWNER_UIN = "2258374446"
REPLY_HDR = re.compile(r"^\[回复 [^\]]*\]\s*\n?")
AT_HDR = re.compile(r"^(?:@[^\s@]+\s+)+")


def clean_answer(text: str) -> str:
    t = REPLY_HDR.sub("", text or "")
    t = AT_HDR.sub("", t)
    t = t.replace("袁亨", "元亨")
    return t.strip()


JUNK_Q = re.compile(r"^\[[^\]]{0,12}\]$")


def tier_of(n: int) -> str:
    return "short" if n <= 45 else ("medium" if n <= 150 else "long")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    rows = json.loads(BOT_MSGS.read_text(encoding="utf-8"))
    asr = json.loads(VOICE_ASR.read_text(encoding="utf-8")) if VOICE_ASR.exists() else {}

    blocks = []
    n = 0
    skipped = 0
    for r in rows:
        ans, note = "", ""
        if r.get("voice"):
            ans = (asr.get(r["time"]) or "").strip()
            note = "元亨以语音回复（ASR 转写）"
        if not ans:
            ans = clean_answer(r.get("text", ""))
            if ans in ("[语音]", "[图片]", "[视频]") or not ans:
                skipped += 1
                continue
        if "【系统监测到不安全行为，已屏蔽】" in ans:
            skipped += 1
            continue
        q, speaker = "", "群友"
        if r.get("reply") and "原消息" not in r["reply"]:
            q = r["reply"].split(":", 1)[-1].strip()
        if not q and r.get("ctx"):
            sp, qt, _t = r["ctx"][-1]
            q = qt.strip()
            speaker = "老爹" if "六哉万也" in sp else "朋友"
        if not q or JUNK_Q.match(q.strip()):
            skipped += 1
            continue
        n += 1
        lines = [f"## real-qq-{n}｜小寻虚拟主播交流群",
                 "- source: qq_小寻虚拟主播交流群(1094579571)",
                 f"- summary: {q[:40]}",
                 f"- relationship: {speaker}",
                 "- status: keep",
                 f"- emotion: {classify_emotion(ans)['emotion']}",
                 f"- length_tier: {tier_of(len(ans))}",
                 "- contract: VOICE_ANCHOR",
                 "- subtype: 真实对话"]
        if note:
            lines.append(f"- note: {note}")
        lines += [f"### {speaker}问1", q, "### 元亨答1", ans]
        blocks.append("\n".join(lines))

    header = (f"# 元亨真实对话样本（QQ 实录·原样保留·不得润色）\n\n"
              f"> 来源：小寻虚拟主播交流群（331 人）导出，`tools/real_qq_build.py` 重建；"
              f"共 {len(blocks)} 块（元亨文字 {len(blocks) - sum(1 for b in blocks if 'ASR' in b)} + "
              f"语音转写 {sum(1 for b in blocks if 'ASR' in b)}）。\n\n")
    text = header + "\n\n".join(blocks) + "\n"
    if args.apply:
        pathlib.Path(args.out).write_text(text, encoding="utf-8")
    print(json.dumps({"blocks": n, "skipped": skipped, "apply": bool(args.apply),
                      "out": str(OUT)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
