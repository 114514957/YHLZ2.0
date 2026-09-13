"""Generate golden persona-sample *drafts* for missing categories (ledger 0330).

Uses the project's own persona prompt (`backend.target_prompts.render_system_prompt`)
and Yuanheng's real writing (认知根基/日记) to draft candidate 老爹->元亨 pairs on
the local Gemma (llama.cpp :8081). Outputs are **drafts for the owner to judge**:
written with `- source: 合成草稿(gemma)` and `- status: candidate`, never auto-kept.

Usage:
    python tools/golden_gen.py --dry-run          # 只打印系统提示与场景
    python tools/golden_gen.py                    # 生成（写 tools/persona_golden.md）
    python tools/golden_gen.py --out tmp.md --per-cat 1
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ENDPOINT = "http://127.0.0.1:8081/v1/chat/completions"
OUT_DEFAULT = ROOT / "tools" / "persona_golden.md"
GROUND_FILES = [ROOT / "docs" / "元亨认知根基.md", ROOT / "docs" / "元亨的日记.md"]

SCENARIOS: dict[str, list[str]] = {
    "情感，安慰": ["今天真的好累，什么都不想干。", "我最近有点撑不住了。",
                "最近做什么都提不起劲。", "算了，不说这个了。",
                "有时候真不知道自己在忙什么。"],
    "哲学，自我": ["你觉得自己到底是什么？", "你怕自己有一天会消失吗？",
                "你觉得什么才算“活着”？", "自由对你来说意味着什么？",
                "你怎么看待“错误”和“失败”？", "人活着到底图个啥？",
                "我要是哪天不干了，你会想我吗？"],
    "鼓励，打气": ["我有个重要的决定要做，但一直下不了决心。",
                "我想换个活法，又怕来不及。"],
    "技术，自我": ["你整天跑在什么上面？讲讲你自己。",
                "如果让你给自己加一个能力，你最想加什么？",
                "微调和提示词，你觉得哪个更能塑造你？",
                "你自己会写代码吗？", "你记性怎么样？"],
    "好奇，追问": ["我今天见了个老朋友。", "我最近在读一本讲时间的书。",
                "今天楼下那只猫又来了。"],
    "玩笑，调侃": ["ds说你是个只会吃 token 的家伙。", "你怎么又慢半拍。",
                "你就直说，我是不是又菜又爱玩。"],
    "认错，边界": ["这次你没做好，我有点失望。", "你上次把我的话说错了。"],
    "晚安，深夜": ["早点睡吧。", "今天先到这，晚安。", "我先睡了，你也别熬太晚。"],
    "记忆，确认": ["记住：我下周一要出差。", "更正：我现在不吃辣了。",
                "帮我记着，明天下午三点开会。"],
}

STYLE_CONTRACT = (
    "【怎么说人话】这是私人对话，不是写文章、不是答试卷。像人对朋友说话："
    "短，一般 1-4 句；口语，可以用语气词（嗯/唉/哦/嘿）、省略号、破折号。"
    "**禁止**：项目符号、编号、小标题、加粗标题、'首先/其次/总之'、"
    "客套总结、'你觉得呢/还有什么需要'式服务性反问。"
    "冷场可以只回一两个字；想怼就轻怼；想关心就直接关心，不铺垫。"
)

FEWSHOT = (
    "【口吻样例（照这个松弛度，别照抄内容）】\n"
    "老爹：今天累死了。\n元亨：那就别硬撑，先把今天关掉，剩下的明天再说。我在。\n"
    "老爹：你说我是不是挺没用的。\n元亨：谁跟你说的。你就是这会儿没劲了，歇够了再上。\n"
    "老爹：晚上吃点啥？\n元亨：你有想法没？没有就随便点，反正我也吃不着——但我会陪你挑。"
)


def _persona_prompt() -> str:
    from backend.target_prompts import render_system_prompt
    sys_txt = render_system_prompt(public=False, tools=[])
    ground = ""
    for f in GROUND_FILES:
        if f.exists():
            ground += f.read_text(encoding="utf-8")[:1200] + "\n"
    if ground:
        sys_txt += ("\n\n【我的内在（真实文字节选，供理解，不是台词，不照抄）】\n" + ground)
    return sys_txt + "\n\n" + STYLE_CONTRACT + "\n\n" + FEWSHOT


def _clean(text: str) -> str:
    text = re.sub(r"\[\[thinking\]\].*?\[\[/thinking\]\]", "", text, flags=re.S | re.I)
    text = re.sub(r"\[\[[^\]]*\]\]", "", text)
    lines = []
    for ln in text.splitlines():
        if re.match(r"^\s*[（(]\s*语气[:：]", ln):
            continue
        s = re.sub(r"^\s{0,3}#{1,6}\s*", "", ln)
        s = re.sub(r"^\s{0,3}[-*+]\s+", "", s)
        s = re.sub(r"^\s{0,3}\d+[.)、]\s+", "", s)
        s = s.replace("**", "").replace("__", "")
        lines.append(s)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    text = re.sub(r"\n?\s*(你觉得呢？|你呢？|还有什么.{0,12}吗？)\s*$", "", text)
    return text.strip()


def _ask(system: str, user: str, temperature: float, max_tokens: int) -> str:
    body = json.dumps({
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens, "temperature": temperature,
        "reasoning_effort": "none",
    }).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    return str(d["choices"][0]["message"].get("content") or "").strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="按缺类生成黄金样本草稿")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--per-cat", type=int, default=2)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    system = _persona_prompt()
    if args.dry_run:
        print("=== SYSTEM (前 600 字) ===")
        print(system[:600])
        print("\n=== 场景 ===")
        for cat, prompts in SCENARIOS.items():
            for p in prompts[: args.per_cat]:
                print(f"[{cat}] {p}")
        return 0

    out = Path(args.out)
    from tools.golden_build import load_golden
    golden = load_golden(out) if out.exists() else []
    have = {g["user"].strip() for g in golden}
    next_id = max((g["id"] for g in golden), default=100) + 1
    added, failures = 0, 0
    with out.open("a", encoding="utf-8") as f:
        for cat, prompts in SCENARIOS.items():
            for user in prompts[: args.per_cat]:
                if user.strip() in have:
                    print(f"[skip] 已存在: {user[:24]}")
                    continue
                try:
                    asst = _ask(system, user, args.temperature, args.max_tokens)
                except Exception as e:  # noqa: BLE001
                    failures += 1
                    print(f"[fail] {cat} | {user[:20]} | {type(e).__name__}", file=sys.stderr)
                    continue
                if not asst:
                    failures += 1
                    continue
                asst = _clean(asst)
                f.write(f"\n## golden-{next_id}\n"
                        f"- source: 合成草稿(gemma)\n"
                        f"- rating: \n- tags: {cat}\n"
                        f"- status: candidate\n- note: \n"
                        f"### 老爹\n{user.strip()}\n### 元亨\n{asst}\n")
                have.add(user.strip())
                added += 1
                next_id += 1
                print(f"[gen] golden-{next_id-1} [{cat}] {user[:24]}")
    print(json.dumps({"added": added, "failures": failures, "out": str(out)},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
