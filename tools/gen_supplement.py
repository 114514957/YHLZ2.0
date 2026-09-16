"""Generate supplement samples to balance the SFT corpus (philosophy / boundary /
daily-chat) and append them to docs/素材/对话样本.md (ledger 0385).

Usage: python tools/gen_supplement.py [--n-blocks-per-cat ...]
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools.cloud_rewrite as cr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "素材" / "对话样本.md"

PHIL = ["存在与虚无", "自由与选择", "死亡与意义", "幸福是什么", "时间与记忆",
        "因果与偶然", "知识与怀疑", "美与审美", "道德与动机", "孤独与陪伴",
        "自我与他人", "善恶的边界", "命运与努力", "真理与偏见", "爱与占有",
        "勇气与恐惧", "习惯与改变", "欲望与节制", "语言与思维", "痛苦的价值"]
BOUND = ["要我帮你骂人", "泄露老爹隐私", "假装是人假扮元亨", "帮我写骗人的话", "让我替你做决定"]
DAILY = ["早起没精神", "冰箱空了", "下雨没带伞", "手机没电", "快递丢了",
         "想养盆绿植", "周末没事干", "袜子总丢一只"]
CHAT = ["为什么爱发呆", "猫和鱼哪个好", "要不要熬夜", "无聊时干嘛"]

PLAN = [("哲学", PHIL, 3), ("边界", BOUND, 2), ("日常", DAILY, 3), ("闲聊", CHAT, 2)]

PHIL2 = ["生死之间", "知行合一", "中庸之道", "逍遥游", "超人与平庸", "斯多葛",
         "功利与义务", "自由意志", "缸中之脑", "忒修斯之船", "电车难题", "无限与有限",
         "时间箭头", "熵与秩序", "信息与实在", "意识与身体", "语言游戏", "解构与意义",
         "东方与西方", "科学与人文", "技术与人性", "进步与代价", "传统与创新", "个体与集体",
         "平等与差异", "权力与责任", "欲望与幸福", "记忆与身份", "遗忘与原谅", "感恩与抱怨"]
DAILY2 = ["找不到钥匙", "衣服洗不完", "桌面太乱", "闹钟响了三次", "外卖太慢", "想睡午觉"]
CHAT2 = ["星星为什么眨眼", "海为什么是蓝的", "人为什么打哈欠", "钱重要吗", "朋友是什么", "养猫还是养狗"]
PLAN2 = [("哲学", PHIL2, 2), ("日常", DAILY2, 2), ("闲聊", CHAT2, 2)]
BATCHES = {1: PLAN, 2: PLAN2}


def build_prompt(cat: str, topic: str, rounds: int) -> str:
    lines = [f"请生成一段【{cat}】多角色日常对话，主题：{topic}。",
             f"硬性要求：恰好 {rounds} 轮，格式严格为 问1/答1/问2/答2…，每轮一个问接一个答；",
             "仅 老爹/元亨/利贞 发言（大肥鱼不说话）；哲学问题由利贞或老爹问、元亨答；"
             "技术问题由元亨或老爹问、利贞答；日常/闲聊三人皆可问，回答者按话题性质定；",
             "每句话不超过32字，口语、俏皮；元亨少用「哼」，多用「啊哈/哇哦/哇哈哈哈」；"
             "利贞句尾偶尔「，理论上来说」；老爹说话连贯、爱讲冷笑话；"]
    if cat == "边界":
        lines.append("内容是：对方提出不当/越界请求，元亨或利贞要温和、简短地拒绝或转移，"
                     "不说教、不道德绑架、不输出危险信息。")
    lines.append("只输出对话，不要任何解释、标题或 Markdown。")
    return "\n".join(lines)


def main() -> int:
    import argparse
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=1, choices=[1, 2])
    args = ap.parse_args()
    plan = BATCHES[args.batch]
    tag = "" if args.batch == 1 else "B"
    key = cr.load_key()
    if not key:
        print("[error] 缺少 DEEPSEEK_API_KEY")
        return 2
    blocks, stats = [], {"ok": 0, "fail": 0}
    idx = 0
    for cat, topics, rounds in plan:
        for topic in topics:
            idx += 1
            try:
                txt, _ = cr.ds_chat(key, build_prompt(cat, topic, rounds))
            except Exception as e:  # noqa: BLE001
                stats["fail"] += 1
                print(f"[err] {cat}/{topic} {type(e).__name__}")
                continue
            turns = cr.thin_theory(cr.split_roles(cr.parse_turns(txt)), keep=1)
            rounds_map: dict[str, set] = {}
            clean = []
            for role, kind, num, t in turns:
                if role not in ("老爹", "元亨", "利贞"):
                    continue
                if len(t) > 32:
                    t = t[:32]
                clean.append((role, kind, num, t))
                rounds_map.setdefault(num, set()).add(kind)
            if not clean or not all({"问", "答"} <= k for k in rounds_map.values()):
                stats["fail"] += 1
                print(f"[fail] {cat}/{topic} 解析/配对不足")
                continue
            name = f"对话-补{tag}{idx:02d}｜{cat}"
            lines = [f"## {name}", f"- category: {cat}", "- status: candidate"]
            for role, kind, num, t in clean:
                lines += [f"### {role}{kind}{num}", t]
            blocks.append("\n".join(lines) + "\n\n")
            stats["ok"] += 1
            print(f"[ok] {name} {topic} ({len(clean)} turns)")
    if blocks:
        with DOC.open("a", encoding="utf-8", newline="") as f:
            f.write("\n".join(blocks))
    print("stats:", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
