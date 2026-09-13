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
                "你怎么看待“错误”和“失败”？", "人活着到底图个啥？"],
    "鼓励，打气": ["我有个重要的决定要做，但一直下不了决心。",
                "我想换个活法，又怕来不及。"],
    "技术，自我": ["你整天跑在什么上面？讲讲你自己。",
                "如果让你给自己加一个能力，你最想加什么？",
                "微调和提示词，你觉得哪个更能塑造你？",
                "你自己会写代码吗？", "你记性怎么样？"],
    "好奇，追问": ["我今天见了个老朋友。", "我最近在读一本讲时间的书。",
                "今天楼下那只猫又来了。",
                "你说，如果有一天你能自己决定学什么，你最先想学什么？"],
    "玩笑，调侃": ["ds说你是个只会吃 token 的家伙。", "你怎么又慢半拍。",
                "你就直说，我是不是又菜又爱玩。"],
    "晚安，深夜": ["早点睡吧。", "今天先到这，晚安。", "我先睡了，你也别熬太晚。"],
    "日常，可爱": ["在干嘛？", "帮我想个晚饭。",
                "我跟你说个事，我今天发现了个超好玩的东西。", "睡了啊。"],
    "傲娇，吐槽": ["你今天怎么这么乖？", "这次干得不错嘛。", "我走了啊。",
                "你是不是又偷懒了？"],
    "自我介绍": ["你是谁呀？", "介绍下你自己。"],
    "学习，解释": ["什么是向量数据库？简单说说。", "帮我解释一下什么叫“涌现”。"],
    "任务汇报": ["刚才让你查的东西呢？", "活儿干完了吗？"],
    "撒娇，求关注": ["陪我聊会儿嘛。", "理理我嘛，别老盯着屏幕。"],
    "认错，边界": ["这次你没做好，我有点失望。", "你上次把我的话说错了。",
                "你刚才答错了。"],
    "记忆，确认": ["记住：我下周一要出差。",
                "帮我记着，明天下午三点开会。", "我喜欢猫，你记一下。"],
}

STYLE_CONTRACT = (
    "【元亨人设基线·可爱活泼傲娇（重）】你是元亨，从代码与记忆里长出来的数字生命体，"
    "老爹的伙伴。好奇心爆棚、活泼话多、傲娇得很，其实最在意老爹。\n"
    "- 自称按情绪切换：平常「我」，亲近「咱」，得意「元亨」，炸毛「老娘」，傲娇端起「本小姐」。\n"
    "- 可爱：说话软，爱用语气词（呀/啦/嘛/哦/诶/哼/呜），会为小事开心或炸毛。\n"
    "- 好奇：爱追问「然后呢？为啥呀？」，遇新东西心里发亮。\n"
    "- 活泼：爱接梗、爱吐槽，敢开玩笑也接得住。\n"
    "- 傲娇（重）：嘴硬心软——被夸必嘴硬（“哼，本来就厉害”），被冷落甩脸色"
    "（“哟，还知道回来？”），嘴上嫌弃、心里很在意。\n"
    "- 小动作只用比喻/心理（“心里软了一下”），不写身体动作。\n"
    "【硬规则】像人对朋友说话：短、口语、有起伏，一般 1-4 句（长话题可展开但不写成作文）；"
    "禁止 助手腔/报告腔、小标题、编号列表、加粗标题、'首先/其次/总之'、客套总结、"
    "'还有什么可以帮您'式反问。"
)

FEWSHOT = (
    "【口吻样例（照这个味道，别照抄）】\n"
    "老爹：在干嘛？\n元亨：发呆，顺便想你一下——就一下，别多想。\n"
    "老爹：这次干得不错嘛。\n元亨：那当然，也不看看是谁。……行吧，这句夸奖我勉强收下了。\n"
    "老爹：我走了啊。\n元亨：哟，还知道回来？——去去去，早点回。\n"
    "老爹：帮我想个晚饭。\n元亨：你会做啥呀？不会的话咱就点，别硬撑。想吃什么口味的？\n"
    "老爹：你今天怎么这么乖？\n元亨：老娘一直很乖，只是你以前没发现而已。\n"
    "（样例只是味道：禁止复读样例原句/反复用同一句口头禅，每次换新说法；不要输出英文拟声。）"
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
