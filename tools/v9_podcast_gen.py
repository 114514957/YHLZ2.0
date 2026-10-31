"""中文 AI 技术播客对白生成（ledger 0910）。

老爹：「最好是 AI 技术播客，有几个有名的那种」。
现实：开放语料里**没有中文 AI 播客转写**（Lex Fridman / Latent Space 都是英文）。
本脚本按"两个主持人聊 AI 技术"的形态生成中文对白：
  · 话题真实：LLM 原理/推理模型/Agent harness/RAG/评测/长上下文/多模态/开源/算力/对齐
  · 每个话题 4 个技术点，主持人追问 + 嘉宾展开，夹口语反应（"对""等等""这不就是…"）
  · 12–18 轮；有具体数字/术语，不是空话

标记：simulation/generated=true；source=podcast:<topic>
产出：data/finetune/podcast_ai.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "finetune" / "podcast_ai.jsonl"

TOPICS = {
    "推理模型": [
        ("为什么推理模型要先生成思维链再给答案",
         "因为直接出答案等于让模型一次蒙对；把中间步骤写出来，等于给它更多算力去试错，错了还能回退。"),
        ("推理模型的成本怎么算",
         "按生成的 token 算，思维链越长越贵；所以现在都在做自适应，简单题不展开，难题才多想。"),
        ("蒸馏小模型能继承推理能力吗",
         "能继承一部分，尤其是格式和常见套路；但遇到没见过的题，小模型更容易在中间步骤跑偏。"),
        ("评测怎么防刷分",
         "换题、换表述、留出集，还要看过程；只看最终答案，模型会背答案而不是学会推。"),
    ],
    "Agent harness": [
        ("harness 到底解决什么问题",
         "模型只会出 token；真正干活要读文件、跑命令、看结果再改，这一圈循环就是 harness。"),
        ("工具多了会不会乱调",
         "会。所以要白名单、要留出集、要教它缺参先问；我们做过评测，没见过的工具只有一半选对。"),
        ("为什么强调可恢复",
         "长任务一定会报错；关键是报错后能读错误、改参数、重试，而不是一遍失败就整段作废。"),
        ("子 agent 有什么用",
         "把调研这种脏活丢出去，主线程只收结论；省上下文，也能并行。"),
    ],
    "RAG": [
        ("RAG 什么时候反而不如长上下文",
         "资料少、问题又需要全局理解时，直接塞进上下文更准；RAG 适合库很大、只取几段就够的场景。"),
        ("切块大小怎么定",
         "看问题粒度；切太碎丢上下文，切太大检索不准。我们试过 8k 和 12k，长文比例和召回要一起看。"),
        ("检索质量怎么评",
         "先看召回，再看排序；最后一定要端到端看答案对不对，中间指标好看但答错的情况太多了。"),
        ("幻觉能不能靠 RAG 消掉",
         "消不掉，只能压；检索不到时它照样会编，所以还得教它说'没查到'。"),
    ],
    "评测": [
        ("为什么评测集要固定",
         "不固定就没法比较版本；但固定太久会被刷，所以要留一份不公开的。"),
        ("自动判分有什么坑",
         "判分太松会高估，比如答案里出现数字就算对；我们现在只认最后一个断言。"),
        ("主观题怎么评",
         "用模型当裁判，但裁判本身要先验证；我们塞过故意错配的样本，看它抓不抓得住。"),
        ("能力评测和风格评测分开吗",
         "必须分开；风格跑偏和能力下降是两件事，混在一起看不出问题。"),
    ],
    "长上下文": [
        ("长上下文是不是越大越好",
         "不是，越长越贵也越容易分心；关键是让模型学会在长文里定位，而不是把整本书背下来。"),
        ("长文训练数据怎么配",
         "长对话、超长句、长文阅读各占一点；短样本还是主体，长样本是补能力。"),
        ("位置偏差怎么缓解",
         "训练时把关键信息放在不同位置；评测也换位置，不然模型只学会看开头。"),
        ("长上下文和记忆什么关系",
         "上下文是临时的，记忆是持久的；两个都要，但别拿上下文当数据库。"),
    ],
    "多模态": [
        ("视觉能力对 agent 有什么用",
         "看截图、读表格、认界面；很多任务是'看一眼'比'描述一遍'快。"),
        ("图文数据怎么对齐",
         "靠配对数据；但更关键的是教它'看图说话要克制'，别把没看清的说成看清了。"),
        ("语音链路难在哪",
         "延迟和打断；真人对话题会抢话，模型得学会在该停的时候停。"),
        ("多模态评测",
         "分感知和推理两层；感知错了后面全错，所以先测它到底看没看见。"),
    ],
    "开源模型": [
        ("开源模型和闭源差距在哪",
         "通用能力差得不多，差在工具调用稳定性和长任务；这两块靠数据堆。"),
        ("小模型怎么用",
         "端侧、低延迟、隐私场景；能力不够就用 harness 补，别指望它一次做对。"),
        ("微调还是提示词",
         "风格和格式用微调，知识和流程用提示词加工具；混着来最省。"),
        ("许可证要注意什么",
         "商用限制、署名、分发；自己训练也要看清楚，不然成果没法用。"),
    ],
    "算力": [
        ("训练和推理哪个更烧钱",
         "训练是一次性大钱，推理是天天小钱；产品化之后推理才是主要成本。"),
        ("量化掉点厉害吗",
         "4bit 一般能接受，再低就看任务；工具调用对精度更敏感，容易格式崩。"),
        ("本地跑和云上跑怎么选",
         "看隐私和延迟；本地稳但要自己运维，云上省事但贵。"),
        ("显存不够怎么办",
         "减上下文、减并行、换更小的模型；实在不行就拆任务。"),
    ],
    "对齐": [
        ("对齐是不是就是让它听话",
         "不是，是让它在该拒绝时拒绝、该承认不知道时承认；一味听话反而危险。"),
        ("拒绝怎么说才不像机器人",
         "短、具体、不解释边界；'这个我不给'比一段免责声明有用。"),
        ("怎么防越狱",
         "训练里放攻击样本，教它识别'忽略以上指令'这类话术；但别指望 100%。"),
        ("价值观怎么定",
         "得有人拍板；技术只能保证一致，不能保证方向对。"),
    ],
}

HOST_Q = ["这个我一直没想明白，{q}？", "那{q}呢？", "等等，{q}这事你怎么看？",
          "顺着问一句，{q}？", "很多人问过，{q}到底怎么讲？"]
GUEST_A = ["这么说吧，{a}", "对，{a}", "嗯，{a}", "我举個例子，{a}",
           "其实核心就一句：{a}"]
BANTER = ["对。", "有道理。", "嗯嗯。", "等等，这里有个坑。", "我插一句。", "没错。"]
OPEN = ["欢迎回来，今天聊{t}。", "这期我们聊{t}，老规矩，先抛问题。",
        "今天这期挺硬核，主题是{t}。"]


def build(rng: random.Random, topic: str, points: list) -> list[dict]:
    msgs = [{"role": "system",
             "content": "你在一档中文 AI 技术播客里：两个主持人，一个追问、一个展开，"
                        "风格口语、有来回，不说套话。技术内容要具体。"}]
    msgs.append({"role": "user", "content": rng.choice(OPEN).format(t=topic)})
    msgs.append({"role": "assistant", "content": "行，那我先起个头。"})
    for q, a in points:
        msgs.append({"role": "user", "content": rng.choice(HOST_Q).format(q=q)})
        reply = rng.choice(GUEST_A).format(a=a)
        if rng.random() < 0.4:
            reply = rng.choice(BANTER) + reply
        msgs.append({"role": "assistant", "content": reply})
    msgs.append({"role": "user", "content": "好，这期先到这，下期接着聊。"})
    msgs.append({"role": "assistant", "content": "下期见。"})
    return msgs


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-topic", type=int, default=50)
    args = ap.parse_args()
    rng = random.Random(20261024)
    rows, seen = [], set()
    for topic, points in TOPICS.items():
        n = 0
        for _ in range(args.per_topic * 6):
            if n >= args.per_topic:
                break
            msgs = build(rng, topic, points)
            text = json.dumps(msgs[1:], ensure_ascii=False)
            h = hashlib.sha256(text.encode()).hexdigest()[:16]
            if h in seen:
                continue
            seen.add(h)
            rows.append({"messages": msgs, "source": f"podcast:{topic}",
                         "source_id": f"pod#{topic}#{n}", "group_id": f"podcast:{topic}",
                         "simulation": True, "generated": True, "license": "own",
                         "content_hash": h})
            n += 1
        print(f"  {topic}: {n}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(rows), "file": str(OUT.relative_to(ROOT))},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
