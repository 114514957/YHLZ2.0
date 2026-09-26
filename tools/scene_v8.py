"""Scene dialogue generator v8 — spec-compliant (README_规范 §2/§3/§4).

Fixes over tools/scene_dataset.py (v6):
  - length tiers: short(≤30) 40% / medium(60-120) 35% / long(200-400, 有序) 25%
  - emotion quota per block (neutral≤40/happy20-28/calm10-15/surprised≤15/sad≥5/angry≥5)
  - self-reference quota (我45/咱20/本小姐20/老娘10/元亨5) tied to emotion
  - categories: 技术≥20 / 哲学20-25 / 日常20-25 / 故事≤30 / 闲聊10
  - bans: brackets, assistant tone, single opening cliché, 不反问收尾, markdown
  - full metadata per block (category/subtype/status/emotion/length_tier/contract)
  - hard validator rejects non-conforming drafts; DS-backed with local fallback.

Usage:
    python tools/scene_v8.py --n 8 --offset 0 --seed 8 --model ds --out docs/素材/对话样本_v8_a.md
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tools.cloud_rewrite as cr  # noqa: E402

TURN = re.compile(r"^###\s*([^\n#]*?)(问|答)\s*(\d+)\s*$", re.MULTILINE)
ROLES = ("老爹", "元亨", "利贞")
IDEOLOGY = ("唯物", "辩证", "历史唯物", "阶级", "意识形态", "生产资料", "异化",
            "商品拜物", "剩余价值", "剥削")
TONE_BAD = ("助手", "为您", "以下是", "列表", "已为您", "根据查询结果")
BRACKET = re.compile(r"（[^）]{1,4}）")
OPEN_BAN = ("哇哈哈哈", "哇哦，", "啊哈，")

TOPICS = {
    "日常": ["出去吃饭", "黄河边晒太阳", "钓鱼", "给电脑清灰", "茶摊喝茶", "咖啡店看书",
           "逛博物馆", "动物园看动物", "公园散步", "周末大扫除", "煮一锅面", "阳台养花",
           "傍晚遛弯", "逛菜市场", "利贞下厨", "利贞去买菜", "给大肥鱼喂瓜子", "下雨天",
           "换灯泡", "修自行车", "晒被子", "找老照片", "夜市小吃", "理发"],
    "哲学": ["苏格拉底：什么是好的生活", "柏拉图：洞穴寓言", "亚里士多德：幸福",
           "康德：道德律", "黑格尔：辩证法", "叔本华：痛苦", "笛卡尔：我思",
           "马克思：劳动异化", "泰戈尔：爱与自由", "尼采：超人", "论语：君子",
           "庄子：逍遥", "斯多葛：控制二分", "存在主义：选择", "功利主义：最大幸福",
           "语言与意义", "自由意志", "死亡与意义", "技术与人性", "美的本质"],
    "技术": ["优化慢查询", "排查内存泄漏", "写单元测试", "重构一个函数", "模型量化",
           "GPU 显存不足", "日志结构化", "接口超时重试", "让推理再快点", "缓存一致性",
           "数据库索引选择", "灰度发布", "回滚方案", "提示词太长砍哪里", "向量检索召回低",
           "本地模型和云模型分工", "脚本幂等", "任务队列重试风暴", "显存碎片", "评测集泄漏"],
    "故事": ["大肥鱼把瓜子吞卡了", "利贞下厨把番茄酱挤进米饭", "熬夜调 bug 到天亮",
           "台风天停电点蜡烛", "第一次把模型跑起来", "生日蛋糕塌了", "河边捡到怪石头",
           "旧电脑退役仪式", "风筝挂树上", "雪天堆雪鲸", "买菜被坑", "半夜听到怪声",
           "给大肥鱼洗澡", "修好一台老收音机", "把显卡风扇清出一座灰山"],
    "闲聊": ["人为什么要工作", "为什么要睡觉", "时间是什么", "孤独是什么", "怎么才算过得好",
           "要不要养宠物", "幸福能比较吗", "无聊有没有用", "习惯怎么养成", "怎样算朋友",
           "为什么怕冷", "旅行有什么意义", "音乐为什么好听"],
}


def load_key() -> str:
    return cr.load_key()


def ds_json(key, system, user, max_tokens=4200, temperature=0.95):
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": temperature, "max_tokens": max_tokens, "stream": False,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"].get("content", ""), d.get("usage", {})


SYS = (
    "你是「元亨」项目的数据工程师，只输出 Markdown 对话块，不解释。\n"
    "角色铁律：只有 老爹/元亨/利贞 能发言；大肥鱼绝不发言（只能被提起）。\n"
    "- 老爹：懒散、爱开玩笑、句子完整连贯；自称「我」。\n"
    "- 元亨：活泼傲娇毒舌、哲学强；自称按指定要求（我/咱/本小姐/老娘/元亨）。\n"
    "- 利贞：稳重直接、技术强；句尾偶尔「，理论上来说」（整块最多 1 次）；自称「我」。\n"
    "硬禁令：括号动作（如（笑））、旁白、Markdown 语法、助手腔（为您/以下是/列表）、"
    "每条答话开头**不许**用「哇哈哈哈」「哇哦，」「啊哈，」；"
    "非哲学题材出现哲学/意识形态术语即废；出现日文韩文俄文即废；"
    "最后一条答话**禁止以问号结尾**（不反问）。\n"
    "每轮必须承接上一轮（顺着说，不是各说各的）。"
)

FORMAT = (
    "输出格式（每个块严格如下，块之间用一行 `=====` 分隔）：\n"
    "## 对话-<序号>｜<类别>\n"
    "- category: <类别>\n"
    "- emotion: <指定情绪>\n"
    "- length_tier: <short|medium|long>\n"
    "### <角色>问1\n<内容>\n### <角色>答1\n<内容>\n…（问2/答2…）"
)

LEN_RULE = {
    "short": "全部答话 ≤30 字",
    "medium": "主答 60–120 字（其余轮可短）",
    "long": "主答 200–400 字、**有序地长**（先总后分或递进，不许短句硬凑），其余轮可短",
}


def build_plan(n: int, offset: int, seed: int, preset: str = "default") -> list[dict]:
    rng = random.Random(seed)
    total = max(offset + n, 1)
    if preset == "long":
        cats_w = [("技术", .40), ("哲学", .40), ("故事", .20)]
        tier_w = {
            "技术": [("medium", .40), ("long", .60)],
            "哲学": [("medium", .40), ("long", .60)],
            "故事": [("medium", .55), ("long", .45)],
        }
    else:
        cats_w = [("日常", .22), ("哲学", .22), ("技术", .22), ("故事", .22), ("闲聊", .12)]
        tier_w = {
            "技术": [("short", .30), ("medium", .40), ("long", .30)],
            "哲学": [("short", .30), ("medium", .35), ("long", .35)],
            "日常": [("short", .55), ("medium", .40), ("long", .05)],
            "故事": [("short", .50), ("medium", .45), ("long", .05)],
            "闲聊": [("short", .70), ("medium", .30)],
        }
    emo_w = [("neutral", .30), ("happy", .24), ("calm", .13), ("surprised", .10),
             ("sad", .12), ("angry", .11)]
    voice_by_emo = {
        "neutral": [("我", .65), ("咱", .35)],
        "calm": [("我", .60), ("咱", .40)],
        "sad": [("我", 1.0)],
        "happy": [("本小姐", .68), ("我", .22), ("咱", .10)],
        "surprised": [("我", .40), ("本小姐", .40), ("元亨", .20)],
        "angry": [("老娘", .75), ("我", .25)],
    }

    def pick(pairs):
        r = rng.random()
        acc = 0.0
        for k, w in pairs:
            acc += w
            if r <= acc:
                return k
        return pairs[-1][0]

    plan = []
    for i in range(total):
        cat = pick(cats_w)
        tier = pick(tier_w[cat])
        if cat == "技术":
            emo = pick([("neutral", .5), ("calm", .3), ("surprised", .2)])
            voice = "我"
        else:
            emo = pick(emo_w)
            voice = pick(voice_by_emo[emo])
        topic = rng.choice(TOPICS[cat])
        turns = 2 if tier == "long" else (3 if tier != "short" else rng.choice([2, 3]))
        plan.append({"i": i, "cat": cat, "tier": tier, "emotion": emo,
                     "voice": voice, "topic": topic, "pairs": turns})
    return plan[offset:offset + n]


def _ask_roles(cat: str, emotion: str) -> str:
    if cat == "技术":
        return "问答安排：主答=利贞（技术由利贞主讲）；提问可用元亨/老爹。"
    if cat == "哲学":
        return "问答安排：主答=元亨（哲学由元亨主讲）；提问可用利贞/老爹。"
    return "问答安排：主答=元亨；提问可用老爹/利贞。"


def build_prompt(specs: list[dict], preset: str = "default") -> str:
    lines = []
    for s in specs:
        if s["voice"] == "我":
            voice_note = "元亨自称：**只用「我」（允许偶尔「咱」）；绝不出现「本小姐/老娘/元亨」**"
        else:
            voice_note = (f"元亨自称：**必须至少一条元亨答话里出现「{s['voice']}」**"
                          f"（其余可配「我」）")
        rule = LEN_RULE[s["tier"]]
        if preset == "long" and s["tier"] == "medium":
            rule = "每句答话 60–120 字（**不许短句**）"
        lines.append(
            f"- 块{s['i']}：类别={s['cat']}；主题={s['topic']}；情绪={s['emotion']}；"
            f"长度档={s['tier']}（{rule}）；轮数={s['pairs']}个问答对；"
            f"{voice_note}。{_ask_roles(s['cat'], s['emotion'])}")
    return ("请生成下列对话块（严格按要求；每个块的元数据字段照抄给定值）。\n"
            + "\n".join(lines) + "\n\n" + FORMAT)


def parse_blocks(txt: str) -> list[tuple[dict, list[tuple[str, str, int, str]]]]:
    out = []
    for chunk in re.split(r"(?m)^\s*=====\s*$", txt):
        if "## " not in chunk:
            continue
        head = chunk.splitlines()[0]
        meta = {}
        for m in re.finditer(r"^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", chunk, re.M):
            meta[m.group(1).lower()] = m.group(2).strip()
        ms = list(TURN.finditer(chunk))
        turns = []
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(chunk)
            text = chunk[m.end():end].strip()
            if text:
                turns.append((m.group(1).strip(), m.group(2), int(m.group(3)), text))
        if turns:
            out.append((meta, turns))
    return out


def validate(spec: dict, meta: dict, turns) -> str:
    for role, kind, num, text in turns:
        if role not in ROLES:
            return f"非法角色:{role}"
        if not text:
            return "空文本"
        if role != "元亨" and ("本小姐" in text or "老娘" in text):
            return f"自称越界({role})"
        if BRACKET.search(text):
            return "括号动作"
        if any(w in text for w in TONE_BAD):
            return "助手腔"
        if any(w in text for w in IDEOLOGY) and spec["cat"] != "哲学":
            return "非哲学含术语"
        if re.search(r"[\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff]", text):
            return "外文"
        if "**" in text or text.startswith(("-", "*", "#", "1.")):
            return "markdown残留"
        if "理论上来说" in text and turns and sum(t.count("理论上来说") for _, _, _, t in turns) > 1:
            return "利贞口头禅超频"
        if any(text.startswith(b) for b in OPEN_BAN):
            return "禁开场词"
    qkinds = [k for _, k, _, _ in turns]
    if qkinds.count("问") != qkinds.count("答") or not qkinds or qkinds[0] != "问":
        return "问答应成对"
    pairs = len(turns) // 2
    if qkinds != ["问", "答"] * pairs:
        return "问答应交替"
    if [n for _, _, n, _ in turns] != [i for i in range(1, pairs + 1) for _ in range(2)]:
        return "轮号错"
    by_num = {}
    for role, kind, num, text in turns:
        by_num.setdefault(num, {})[kind] = role
    for num, d in by_num.items():
        if d.get("问") and d.get("答") and d["问"] == d["答"]:
            return f"自问自答({num})"
    answers = [t for r, k, n, t in turns if k == "答"]
    if not answers:
        return "无答"
    answerers = {r for r, k, n, t in turns if k == "答"}
    if spec["cat"] == "技术":
        if "利贞" not in answerers:
            return "技术缺利贞主讲"
    elif "元亨" not in answerers:
        return "缺元亨主讲"
    main = max(answers, key=len)
    if spec["tier"] == "short":
        if any(len(a) > 30 for a in answers):
            return "短档超长"
    elif spec["tier"] == "medium":
        if not any(60 <= len(a) <= 120 for a in answers):
            return "中档缺60-120"
        if any(len(a) > 150 for a in answers):
            return "中档超长"
    else:
        if len(main) < 200:
            return f"长档不足({len(main)})"
        if len(main) > 450:
            return "长档超长"
    if turns[-1][1] == "答" and turns[-1][3].rstrip().endswith(("？", "?")):
        return "反问收尾"
    v = spec["voice"]
    joined = "".join(answers)
    if v == "我" and any(t in joined for t in ("本小姐", "老娘", "元亨")):
        return "自称越界"
    if v != "我" and v not in joined:
        return f"缺自称{v}"
    return ""


def render(spec: dict, turns) -> str:
    subtype = {"short": "长度短", "medium": "长度中", "long": "长度长"}[spec["tier"]]
    lines = [f"## 对话v8-{spec['i']}｜{spec['cat']}",
             f"- category: {spec['cat']}",
             f"- subtype: {subtype}",
             "- status: candidate",
             f"- emotion: {spec['emotion']}",
             f"- length_tier: {spec['tier']}",
             "- contract: VOICE_ANCHOR"]
    for role, kind, num, text in turns:
        lines += [f"### {role}{kind}{num}", text]
    return "\n".join(lines)


def gen_batch(key, specs: list[dict], preset: str = "default") -> tuple[list[str], str, set]:
    txt, _ = ds_json(key, SYS, build_prompt(specs, preset))
    outs, why = [], "?"
    ok_ids = set()
    pool = list(parse_blocks(txt))
    used = set()
    for spec in specs:
        pick = None
        for j, (meta, turns) in enumerate(pool):
            if j in used:
                continue
            if (meta.get("category") == spec["cat"]
                    and meta.get("emotion") == spec["emotion"]
                    and meta.get("length_tier") == spec["tier"]):
                pick = j
                break
        if pick is None:
            for j in range(len(pool)):
                if j not in used:
                    pick = j
                    break
        if pick is None:
            why = f"块{spec['i']}:缺块"
            continue
        used.add(pick)
        meta, turns = pool[pick]
        why2 = validate(spec, meta, turns)
        if why2:
            why = f"块{spec['i']}:{why2}"
            continue
        outs.append(render(spec, turns))
        ok_ids.add(spec["i"])
    return outs, why, ok_ids


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="场景对话生成 v8")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--seed", type=int, default=8)
    ap.add_argument("--plan-size", type=int, default=1200, help="全量计划大小（并行 worker 共享）")
    ap.add_argument("--preset", choices=["default", "long"], default="default")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--out", default=str(ROOT / "docs" / "素材" / "对话样本_v8.md"))
    args = ap.parse_args()

    key = load_key()
    if not key:
        print("[error] 缺 DEEPSEEK_API_KEY")
        return 2
    plan = build_plan(args.plan_size, 0, args.seed, args.preset)[args.offset:args.offset + args.n]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (f"# 元亨对话样本 v8（规范版·由 scene_v8.py 生成）\n\n"
              f"> 配额：长度短40/中35/长25｜情绪六类｜自称配额｜类别 技术≥20/故事≤30｜"
              f"禁括号·禁口癖·不反问。`status` 通过终检后方可置 keep。\n\n")
    if not out.exists():
        out.write_text(header, encoding="utf-8")
    ok = fail = 0
    done = set()
    for m in re.finditer(r"## 对话v8-(\d+)", out.read_text(encoding="utf-8")):
        done.add(int(m.group(1)))
    todo = [s for s in plan if s["i"] not in done]
    for b in range(0, len(todo), args.batch):
        pending = todo[b:b + args.batch]
        for attempt in range(3):
            if not pending:
                break
            try:
                blocks, why, ok_ids = gen_batch(key, pending, args.preset)
            except Exception as e:  # noqa: BLE001
                print(f"[{b//args.batch+1}.{attempt+1}] 异常 {type(e).__name__}")
                time.sleep(3)
                continue
            if blocks:
                with out.open("a", encoding="utf-8") as f:
                    f.write("\n\n".join(blocks) + "\n\n")
                ok += len(blocks)
            pending = [s for s in pending if s["i"] not in ok_ids]
            print(f"[{b//args.batch+1}.{attempt+1}] +{len(blocks)} 剩{len(pending)} :: {why}")
            if not pending:
                break
        fail += len(pending)
    print(json.dumps({"ok": ok, "fail": fail, "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
