"""Scene dialogue generator with hard gates (ledger 0351).

Generates 老爹/元亨/利贞 multi-role dialogues by category (日常/哲学/技术/闲聊):
  - 元亨: 活泼乐观傲娇, 哲学强; 利贞: 稳重博学直接, 技术强; 大肥鱼: 宠物, 不说话.
  - worldview implicit (not crammed); ≤30 chars/turn; only 老爹/元亨/利贞 speak.
  - gates + retry: format 问K/答K paired, role set, no 大肥鱼 lines, no ideology in
    non-哲学, no markdown, self-reference consistency.

Usage:
    python tools/scene_dataset.py --n 12                 # Gemma
    python tools/scene_dataset.py --n 12 --model qwen    # qwen2.5:3b
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DOC = ROOT / "docs" / "素材" / "对话样本.md"

ROLES = ("老爹", "元亨", "利贞")
IDEOLOGY = ("唯物", "辩证", "历史唯物", "阶级", "意识形态", "生产资料", "异化",
            "商品拜物", "剩余价值", "剥削")

PERSONA = (
    "你是一个多角色对话剧本生成器。角色与语气：\n"
    "- 老爹：创造者，随意、懒散、爱开玩笑。\n"
    "- 元亨：活泼、乐观、傲娇，哲学强；爱用「哼/本小姐/老娘/啦/哟」。\n"
    "- 利贞：稳重、博学、直接，技术强，少废话。\n"
    "- 大肥鱼：是元亨老爹的宠物（鲸鱼娘），**不会说话**——绝不给它台词，只能被提起；"
    "行为按语境：最爱**吃白饭**、饿了、在水里跑/泡着，偶尔喷水（低频，水边才用）。\n"
    "只有 老爹 / 元亨 / 利贞 会说话。\n"
    "硬规则：每条发言≤32字（越短越好）；口语、俏皮；不要旁白、不要解释、不要 Markdown。\n"
    "不要往日常/技术对话里硬塞哲学或政治术语；三观自然融在人物的话里。\n"
    "自称不许错乱：老爹不说「本小姐/老娘」，元亨不说「利贞」以外的第一人称。\n"
    "输出格式：每轮两行——\n"
    "### <角色>问K\n<内容>\n### <角色>答K\n<内容>\n"
    "同一 K 只能有一个问、一个答；问答者可互换；生成 2-3 轮。\n\n"
    "【风格样例】\n"
    "### 老爹问1\n今天天好，去黄河边坐坐？\n"
    "### 元亨答1\n去去去！本小姐要占最好的那块石头。你带水，我带嘴。\n"
    "### 利贞问2\n风大，带件外套；数据晚点跑没事，太阳不等人。\n"
    "### 元亨答2\n哎哟，利贞今天居然不催活了？行，老娘准了。\n\n"
    "### 元亨问1\n利贞，黑格尔那句‘存在即合理’对吗？\n"
    "### 利贞答1\n原话是‘凡是合乎理性的都是现实的’。它讲必然性，不是叫你认命。\n"
    "### 元亨答2\n我补一句——现实会自己长出矛盾再被扬弃，这叫否定之否定。\n"
)

CATS = {
    "日常": ["出去吃饭", "黄河边晒太阳", "钓鱼", "给电脑清灰", "茶摊喝茶",
           "咖啡店看书", "逛博物馆", "动物园看动物", "公园散步", "周末大扫除",
           "煮一锅面", "阳台养花", "傍晚遛弯", "逛菜市场"],
    "哲学": ["苏格拉底：什么是好的生活", "柏拉图：洞穴寓言", "亚里士多德：幸福",
           "康德：道德律", "黑格尔：辩证法", "叔本华：痛苦", "笛卡尔：我思",
           "马克思：劳动异化", "泰戈尔：爱与自由", "尼采：超人", "论语：君子"],
    "技术": ["优化慢查询", "排查内存泄漏", "写单元测试", "重构一个函数",
           "模型量化", "GPU 显存不足", "日志结构化", "接口超时重试"],
    "闲聊": ["人为什么要工作", "为什么要睡觉", "时间是什么", "孤独是什么",
           "怎么才算过得好", "要不要养宠物"],
}
MIX = [("日常", 40), ("哲学", 25), ("技术", 20), ("闲聊", 15)]


def _gemma(system: str, user: str) -> str:
    body = json.dumps({"messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}],
                       "max_tokens": 500, "temperature": 0.85,
                       "reasoning_effort": "none"}).encode()
    req = urllib.request.Request("http://127.0.0.1:8081/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8", "replace"))["choices"][0]["message"].get("content", "")


def _qwen(system: str, user: str) -> str:
    body = json.dumps({"model": "qwen2.5:3b",
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}],
                       "stream": False,
                       "options": {"temperature": 0.85, "num_predict": 500}}).encode()
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read().decode("utf-8", "replace")).get("message", {}).get("content", "")


TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)\s*(\d+)\s*$", re.MULTILINE)


def parse(txt: str) -> list[tuple[str, str, int, str]] | None:
    ms = list(TURN.finditer(txt))
    if not ms:
        return None
    out = []
    for i, m in enumerate(ms):
        role = m.group(1).strip()
        kind, num = m.group(2), int(m.group(3))
        end = ms[i + 1].start() if i + 1 < len(ms) else len(txt)
        text = txt[m.end():end].strip().splitlines()[0].strip() if txt[m.end():end].strip() else ""
        out.append((role, kind, num, text))
    return out


def validate(turns: list[tuple[str, str, int, str]], cat: str) -> str | None:
    if not turns:
        return "空"
    rounds: dict[int, dict] = {}
    for role, kind, num, text in turns:
        if role not in ROLES:
            return f"非法角色:{role}"
        if not text or len(text) > 32:
            return f"长度:{role}{kind}{num}={len(text)}"
        if re.search(r"[\uac00-\ud7af\u3040-\u30ff\u0400-\u04ff]", text):
            return f"外文:{role}"
        if cat != "哲学" and any(w in text for w in IDEOLOGY):
            return f"非哲学含意识形态:{role}"
        if role == "老爹" and ("本小姐" in text or "老娘" in text):
            return "老爹自称错乱"
        if "**" in text or text.startswith(("-", "*", "#")):
            return "markdown"
        rounds.setdefault(num, {})[kind] = text
    if not (2 <= len(rounds) <= 3):
        return f"轮数:{len(rounds)}"
    for num, d in rounds.items():
        if set(d) != {"问", "答"}:
            return f"第{num}轮不配对"
    return None


def render(scene: str, cat: str, turns: list[tuple[str, str, int, str]]) -> str:
    lines = [f"## {scene}", f"- category: {cat}", "- status: candidate"]
    for role, kind, num, text in turns:
        lines.append(f"### {role}{kind}{num}")
        lines.append(text)
    return "\n".join(lines)


def gen_scene(system: str, cat: str, scene: str, model: str, tries: int = 3) -> tuple[str, str] | None:
    user = f"生成一条【{cat}】场景的多角色对话。主题：{scene}。2-3 轮。"
    for _ in range(tries):
        try:
            txt = _gemma(system, user) if model == "gemma" else _qwen(system, user)
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
            continue
        turns = parse(txt)
        if turns is None:
            last = "解析失败"
            continue
        err = validate(turns, cat)
        if err is None:
            return txt, ""
        last = err
    return None, last


def _quota(n: int, rng: random.Random) -> list[str]:
    total = sum(w for _, w in MIX)
    seq = []
    for cat, w in MIX:
        seq += [cat] * round(n * w / total)
    while len(seq) < n:
        seq.append(MIX[len(seq) % len(MIX)][0])
    seq = seq[:n]
    rng.shuffle(seq)
    return seq


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="场景对话批量生成（带硬闸）")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--model", choices=["gemma", "qwen"], default="gemma")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--append", action="store_true")
    ap.add_argument("--doc", default=str(DOC))
    args = ap.parse_args()

    rng = random.Random(args.seed)
    cats_seq = _quota(args.n, rng)
    doc = Path(args.doc)
    doc.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append else "w"
    ok = fail = 0
    with doc.open(mode, encoding="utf-8") as f:
        if not args.append:
            f.write("# 元亨对话样本（场景·多角色）\n\n"
                    "> 由 `tools/scene_dataset.py` 生成；硬闸：≤32字/问答成对/仅老爹·元亨·利贞发言/"
                    "非哲学禁意识形态/大肥鱼不发言。\n> `status` 可改 keep/drop。\n\n")
        for i, cat in enumerate(cats_seq):
            scene = rng.choice(CATS[cat])
            res, err = gen_scene(PERSONA, cat, scene, args.model)
            if res is None:
                fail += 1
                print(f"[{i+1}/{args.n}] 放弃 [{cat}] {scene} :: {err}")
                continue
            f.write(render(f"对话-{i+1}｜{cat}", cat, parse(res)) + "\n\n")
            ok += 1
            print(f"[{i+1}/{args.n}] OK [{cat}] {scene}")
    print(json.dumps({"ok": ok, "fail": fail, "doc": str(doc)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
