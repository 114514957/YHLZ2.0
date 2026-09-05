"""Ledger QA bank (ledger 0152): questions whose answers live in the ledger.

Every question can be answered ONLY by retrieving the ledger/memory (unique
facts).  ``verify`` uses lenient keyword checks against the model answer.
"""

QA_BANK = [
    {"q": "TTS 默认音色是哪个 speaker 的名字？",
     "keys": ["Vivian"], "rec": "记录0129/0130"},
    {"q": "YHLZ 记忆架构分为哪几层？",
     "keys": ["三层", "L1", "L2", "L3"], "rec": "记录0116-0120"},
    {"q": "语音链路的语言范围锁定为哪两种？",
     "keys": ["中文", "英文"], "rec": "记录0143"},
    {"q": "台账与记忆检索当前使用什么索引方案？",
     "keys": ["关键词索引", "keyword index", "轻量关键词"], "rec": "记录0148"},
    {"q": "TTS/LLM 文字测试默认句是什么？",
     "keys": ["进步始于思想", "元亨开拓未来"], "rec": "记录0129"},
    {"q": "语音输入测试句是什么？",
     "keys": ["元亨，能听到吗"], "rec": "记录0129"},
    {"q": "记忆候选生成与裁决的角色分工是什么？",
     "keys": ["本地筛选", "云端裁决", "Ollama", "DeepSeek"], "rec": "记录0138"},
    {"q": "Agent 演进接入点写在哪个 ADR？",
     "keys": ["ADR-006"], "rec": "记录0112/ADR-006"},
    {"q": "行动语义层（Capability Registry）设计在哪个 ADR？",
     "keys": ["ADR-007"], "rec": "记录0145"},
    {"q": "真机 ASR 60 秒监听验收（与视频内容高度吻合）记录在哪个编号？",
     "keys": ["0150"], "rec": "记录0150"},
    {"q": "语言范围（中英双语）在哪个台账记录定案？",
     "keys": ["0143"], "rec": "记录0143"},
    {"q": "人格基调的锚句是什么？",
     "keys": ["先进始于计算"], "negative": ["进步始于思想"], "rec": "记录0144"},
    {"q": "调度能力工具集中，写类（side-effect、需审批）的能力叫什么？",
     "keys": ["memory.save", "memory_save", "保存记忆"], "rec": "记录0152"},
    {"q": "检索验收时发现并修复了几个真实缺陷？",
     "keys": ["三", "3", "四个", "4"], "rec": "记录0149"},
    {"q": "TTS 测试默认语调从哪种改成了自然平实？",
     "keys": ["激动", "兴奋", "EXCITED"], "rec": "记录0149/0150"},
]


def verify(question: str, answer: str) -> tuple[bool, str]:
    entry = next(x for x in QA_BANK if x["q"] == question)
    hit = [k for k in entry["keys"] if k in answer]
    bad = [k for k in entry.get("negative", []) if k in answer]
    ok = bool(hit) and not bad
    detail = ("+".join(hit) if hit else "无命中")
    if bad:
        detail += f" !排除词命中:{','.join(bad)}"
    return ok, detail
