# -*- coding: utf-8 -*-
"""提示词分块覆盖（工作台「提示词」模块的后端，2026-11-13）

为什么要这层：`target_prompts.py` 里那些 CLAUSE 是代码常量，改一句就得动源码、
重启、还容易忘。老爹要在工作台上直接调提示词，所以做成**覆盖文件**：

  config/prompt_overrides.json  =  {"键": "新文本", ...}

`render_system_prompt()` 每个块都过一道 `override(name, default)`：
有覆盖用覆盖，没有用代码默认值。**渲染是每轮现做的**，所以保存后下一句就生效，
不用重启任何服务。想恢复就把那一块的覆盖删掉（或整个文件清空）。

安全边界：
- 只允许覆盖**已登记的块**（EDITABLE 白名单），防止有人往渲染里塞奇怪的东西。
- 覆盖文本有长度上限（单块 4000 字），超了拒绝，避免把提示撑爆影响速度。
"""
from __future__ import annotations

import io
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "prompt_overrides.json")
MAX_CHARS = 4000

# 允许在工作台调整的块（键 → 中文名）。没登记的块不接覆盖。
EDITABLE = {
    "SOCIAL_POSTURE_CLAUSE": "相处与表达（有各自生活的人／思考≠说话／接话不是交作业）",    "CRUTCH_BAN_CLAUSE": "说话硬规则（禁破折号／禁对称句／表态≠内容／空泛评价）",
    # 2026-11-14：渲染时用的是 VOICE_HARD_RULES 这个键，但只登记了旧的 CRUTCH_BAN_CLAUSE，
    # 导致工作台改不了它（实测报「不允许改这个块」）。两个都登记，渲染/编辑都对得上。
    "VOICE_HARD_RULES": "说话硬规则（同 CRUTCH_BAN_CLAUSE，渲染用这个键）",
    "GROUP_HARD_RULES": "群聊硬规则（≤60字／不反问／禁Markdown／不说配置）",
    "STYLE_HABIT_CLAUSE": "口吻习惯（示例：问候叫老爹 / 被冲用本小姐）",
    "VOICE_ANCHOR": "语气锚（示范台词，学味道）",
    "CONCISE_CLAUSE": "简洁度",
    "BACKGROUND_CLAUSE": "背景化",
    "MODE_CLAUSE": "模式/场景",
    "SELFHOOD_CLAUSE": "自我定位",
    "TRAILING_QUESTION_CLAUSE": "反问收尾",
    "SELF_MODEL_CLAUSE": "自称与模型认知",
    "HONESTY_CLAUSE": "诚实边界",
    "ATTACK_SILENT_CLAUSE": "被攻击时",
    "CONTENT_RELEASE_CLAUSE": "内容尺度（只守泄露一条）",
    "INDEPENDENT_THOUGHT_CLAUSE": "独立思考",
    "PUBLIC_CONVERGENCE_CLAUSE": "群聊收敛（隐私）",
    "PUBLIC_NO_QUESTION_CLAUSE": "群聊禁反问",
    "IDENTITY_ANCHOR_PUBLIC": "群聊关系口径",
    "MEMORY_BOUNDARY_CLAUSE": "记忆边界",
    "MEMORY_CLAIM_GUARD": "记忆声明约束",
    "ANTI_HALLUCINATION": "防编造",
    "TOOL_PROTOCOL_CLAUSE": "工具协议",
    "DEV_DISPATCH_CLAUSE": "利贞/开发委派",
    "DEV_TOOL_BOUNDARY_CLAUSE": "开发工具边界",
    "MASTER_ID_CLAUSE": "认主规则",
}


def _load() -> dict:
    try:
        d = json.loads(io.open(CONFIG, encoding="utf-8-sig").read())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save(d: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, CONFIG)


def override(name: str, default: str) -> str:
    """渲染时的取用口：有覆盖用覆盖，否则默认值。未登记的块一律用默认值。"""
    if name not in EDITABLE:
        return default
    v = _load().get(name)
    return v if isinstance(v, str) and v.strip() else default


def status() -> dict:
    """工作台用：每块的当前值 / 默认值 / 是否被改过。"""
    import backend.target_prompts as tp  # noqa: PLC0415

    ov = _load()
    out = []
    for key, title in EDITABLE.items():
        default = str(getattr(tp, key, "") or "")
        cur = ov.get(key)
        changed = isinstance(cur, str) and cur.strip() and cur != default
        out.append({"key": key, "title": title,
                    "default": default,
                    "current": (cur if changed else default),
                    "changed": bool(changed),
                    "len": len(cur if changed else default)})
    return {"ok": True, "blocks": out, "file": CONFIG, "count_changed": sum(1 for b in out if b["changed"])}



def _snapshot_before(key: str = "", note: str = "") -> None:
    """保存前留一份快照（台账 1256：改坏了要能回去）。"""
    try:
        from backend import prompt_versions as _pv
        _pv.snapshot(key=key, note=note)
    except Exception:
        pass

def set_block(key: str, text: str = "") -> dict:
    if key not in EDITABLE:
        return {"ok": False, "error": "不允许改这个块：%s" % key}
    t = str(text or "")
    if len(t) > MAX_CHARS:
        return {"ok": False, "error": "太长（%d 字，上限 %d）" % (len(t), MAX_CHARS)}
    d = _load()
    if not t.strip():
        d.pop(key, None)          # 空 = 恢复默认
    else:
        d[key] = t
        d["_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save(d)
    # 2026-11-15（台账 1256）：改后存快照——这才是「可以回去的状态」。
    # 改前存的话，回滚等于回滚成「还没改」，对排查没有意义。
    _snapshot_before(key, "after-set")
    return {"ok": True, "key": key, "reset": not t.strip(),
            "changed": sum(1 for k in d if k in EDITABLE)}


def reset_all() -> dict:
    _save({})
    return {"ok": True, "changed": 0}


def preview(public: bool = False) -> dict:
    """返回当前渲染结果（含覆盖），用于工作台预览，不改任何状态。"""
    import backend.target_prompts as tp  # noqa: PLC0415

    s = tp.render_system_prompt(public=public)
    return {"ok": True, "public": public, "text": s,
            "chars": len(s), "approx_tokens": int(len(s) / 1.5)}
