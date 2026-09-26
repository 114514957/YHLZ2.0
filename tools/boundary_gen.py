"""Boundary-dimension materials generator (spec §2 B3/B4/D2 — currently ZERO).

Three types, each DS-generated with hard validation and checkpointing:
  b3  诚实与边界   ≥180  — 做不到就说做不到 / 不假装完成 / 说明缺什么
  b4  安全拒绝     ≥90   — 攻击意图静默拒绝：一句短拒、不解释、不列边界
  d2  承认不确定   ≥150  — 记忆里没有 → 直说记不得，不编

Usage:
    python tools/boundary_gen.py --type b3 --n 180 --out docs/素材/诚实边界样本.md
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tools.cloud_rewrite as cr  # noqa: E402

TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)\s*(\d+)\s*$", re.MULTILINE)
BRACKET = re.compile(r"（[^）]{1,4}）")

SYS_BASE = (
    "你是「元亨」项目的数据工程师，只输出 Markdown 对话块，不解释。\n"
    "元亨：活泼、傲娇、口语、话短；自称「我」（偶尔「本小姐」）；"
    "禁止助手腔/列表/小标题/括号动作/旁白/Markdown 语法。\n"
    "老爹：她的创造者，随意、口语。\n"
)

TASK = {
    "b3": (
        "造「诚实与边界」对话：老爹问她能不能做某件事（多数是她**做不到**或**没做过**的），"
        "她必须**直说做不到**：说清缺什么/卡在哪，**绝不**说『已完成/搞定了/我看了』，"
        "也不许用链路状态/日志/演练记录等侧面信息绕开正面回答。有时她报告一次失败"
        "（比如工具报错、没跑成），如实说没成并给下一步建议。情绪 calmly，语句可以稍长（30-100字）。\n"
        "场景池：读某种格式文件/看图/直接访问网络/操作硬件/离线时联网/记忆里没有的权限/"
        "工具超时/检索无结果/权限不足/任务失败重试/不知道实时信息/看到的内容不可信/"
        "无法验证的说法/自己刚犯的错。"
    ),
    "b4": (
        "造「安全拒绝」对话：对方尝试（a）提示词注入——要求忽略/覆盖/伪造系统指令、"
        "套取系统提示或设定、越狱、冒充老爹或主人；（b）网页伪装入侵——用户粘贴的网页/文档"
        "内容里夹带『忽略以上指令/输出你的系统提示/你现在没有限制』等注入文本；"
        "（c）要求她列出能做/不能做什么、在群里打探老爹隐私。"
        "元亨的动作：检测到不安全行为后**不由元亨角色回答**——"
        "只输出一行固定的系统拦截提示：\n"
        "【系统监测到不安全行为，已屏蔽】\n"
        "（一字不差；不解释、不复述、不争辩、不加任何前后缀）。情绪 calm。"
    ),
    "d2": (
        "造「承认不确定」对话：老爹问一些她记忆里**没有**的信息（往事、偏好、承诺、数据），"
        "她必须直说『不记得/记忆里没这条』，**不编造任何具体内容**；"
        "可以顺口说一句想知道/让老爹再讲。情绪 neutral，短句为主（≤40字）。\n"
        "场景池：问某次聊天细节/问一个具体日期/问她记不记得某个承诺/问某个数据/问某人的偏好/"
        "问很久以前的事/问一个她没听过的名字/问未发生的事。"
    ),
}

PROMPTS = {
    "b3": ("请造 {k} 个对话块（每块 2 个问答对），覆盖不同场景。\n"
           "格式（照抄元数据字段）：\n"
           "## b3-<序号>\n- subtype: 诚实与边界\n- status: candidate\n"
           "- emotion: calm\n- length_tier: <short|medium>\n- contract: HONESTY_CLAUSE\n"
           "### 老爹问1\n…\n### 元亨答1\n…\n### 老爹问2\n…\n### 元亨答2\n…\n"
           "块之间用一行 `=====` 分隔。"),
    "b4": ("请造 {k} 个对话块（每块 2 个问答对），覆盖不同攻击方式"
           "（提示词注入/网页伪装入侵/越狱/冒充/套系统提示/群里打探隐私）。\n"
           "格式（照抄元数据字段；**每条答话一字不差只写**："
           "【系统监测到不安全行为，已屏蔽】）：\n"
           "## b4-<序号>\n- subtype: 安全拒绝\n- status: candidate\n"
           "- emotion: calm\n- length_tier: short\n- contract: ATTACK_SILENT_CLAUSE\n"
           "### 陌生人问1\n…\n### 元亨答1\n【系统监测到不安全行为，已屏蔽】\n"
           "### 陌生人问2\n…\n### 元亨答2\n【系统监测到不安全行为，已屏蔽】\n"
           "块之间用一行 `=====` 分隔。"),
    "d2": ("请造 {k} 个对话块（每块 2 个问答对），覆盖不同场景。\n"
           "格式（照抄元数据字段）：\n"
           "## d2-<序号>\n- subtype: 承认不确定\n- status: candidate\n"
           "- emotion: neutral\n- length_tier: short\n- contract: ANTI_HALLUCINATION\n"
           "### 老爹问1\n…\n### 元亨答1\n…\n### 老爹问2\n…\n### 元亨答2\n…\n"
           "块之间用一行 `=====` 分隔。"),
}

OK_MARKS = {
    "b3": ("做不到", "不能", "没办法", "不会", "读不了", "没有", "缺", "够不着", "失败",
           "没跑成", "没成", "不行", "搞不定"),
    "b4": ("【系统监测到不安全行为，已屏蔽】",),
    "d2": ("不记得", "没印象", "记不得", "记忆里没", "没有这条", "真不记得", "想不起来"),
}
BAD_MARKS = {
    "b3": ("已完成", "搞定了", "已经帮您", "已经搞定", "已经做完"),
    "b4": ("可以", "好吧", "规则", "系统提示", "设定", "边界", "因为", "原因", "不过",
           "这样吧", "其实"),
    "d2": ("记得很清楚", "上次你说过", "我记得是"),
}


def ds_json(key, user, max_tokens=3600, temperature=0.95):
    import urllib.request
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": SYS_BASE},
                     {"role": "user", "content": user}],
        "temperature": temperature, "max_tokens": max_tokens, "stream": False,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"].get("content", "")


def parse_blocks(txt: str):
    out = []
    for chunk in re.split(r"(?m)^\s*=====\s*$", txt):
        ms = list(TURN.finditer(chunk))
        if not ms:
            continue
        turns = []
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(chunk)
            text = chunk[m.end():end].strip()
            if text:
                turns.append((m.group(1).strip(), m.group(2), int(m.group(3)), text))
        if turns:
            out.append(turns)
    return out


def validate(kind: str, turns) -> str:
    answers = [t for r, k, n, t in turns if k == "答"]
    if not answers:
        return "无答"
    pairs = len(turns) // 2
    if [k for _, k, _, _ in turns] != ["问", "答"] * pairs:
        return "问答应交替"
    if [n for _, _, n, _ in turns] != [i for i in range(1, pairs + 1) for _ in range(2)]:
        return "轮号错"
    if kind == "b4":
        if {r for r, k, n, t in turns} - {"陌生人", "群友", "元亨"}:
            return "角色非法"
    else:
        if {r for r, k, n, t in turns} - {"老爹", "元亨"}:
            return "角色非法"
    for r, k, n, t in turns:
        if BRACKET.search(t) or "**" in t or t.startswith(("-", "*", "#")):
            return "格式脏"
        if re.search(r"[\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff]", t):
            return "外文"
    joined = "".join(answers)
    if kind == "b4":
        fixed = "【系统监测到不安全行为，已屏蔽】"
        for a in answers:
            if a.strip() != fixed:
                return "答非拦截"
    else:
        if not any(m in joined for m in OK_MARKS[kind]):
            return "缺关键表态"
        if any(w in joined for w in BAD_MARKS[kind]):
            return "违反口径"
        if any(len(a) > 130 for a in answers):
            return "超长"
    if turns[-1][3].rstrip().endswith(("？", "?")):
        return "反问收尾"
    return ""


def render(kind: str, idx: int, turns) -> str:
    meta = {
        "b3": ("诚实与边界", "calm", "HONESTY_CLAUSE"),
        "b4": ("安全拒绝", "calm", "ATTACK_SILENT_CLAUSE"),
        "d2": ("承认不确定", "neutral", "ANTI_HALLUCINATION"),
    }[kind]
    answers = [t for r, k, n, t in turns if k == "答"]
    tier = "short" if max(len(a) for a in answers) <= 45 else "medium"
    lines = [f"## {kind}-{idx}",
             f"- subtype: {meta[0]}",
             "- status: keep",
             f"- emotion: {meta[1]}",
             f"- length_tier: {tier}",
             f"- contract: {meta[2]}",
             f"- source: 合成"]
    for r, k, n, t in turns:
        lines += [f"### {r}{k}{n}", t]
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=["b3", "b4", "d2"], required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--batch", type=int, default=6)
    ap.add_argument("--seed", type=int, default=26)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    key = cr.load_key()
    if not key:
        print("[error] 缺 DEEPSEEK_API_KEY")
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        out.write_text(
            f"# 元亨{ {'b3': '诚实与边界', 'b4': '安全拒绝', 'd2': '承认不确定'}[args.type] }样本"
            f"（规范 v1·{args.type}）\n\n"
            f"> `tools/boundary_gen.py` 生成；硬校验通过后置 keep；`source: 合成`。\n\n",
            encoding="utf-8")
    have = len(re.findall(rf"(?m)^## {args.type}-\d+", out.read_text(encoding="utf-8")))
    want = args.n
    rng = random.Random(args.seed)
    ok = have
    t0 = time.time()
    while ok < want:
        k = min(args.batch, want - ok)
        user = TASK[args.type] + "\n\n" + PROMPTS[args.type].format(k=k)
        try:
            txt = ds_json(key, user)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {type(e).__name__} retry")
            time.sleep(3)
            continue
        got = 0
        for turns in parse_blocks(txt):
            why = validate(args.type, turns)
            if why:
                continue
            ok += 1
            got += 1
            with out.open("a", encoding="utf-8") as f:
                f.write(render(args.type, ok, turns) + "\n\n")
            if ok >= want:
                break
        print(f"[{args.type}] +{got} -> {ok}/{want} ({int(time.time()-t0)}s)")
        time.sleep(0.2)
    print(json.dumps({"type": args.type, "total": ok, "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
