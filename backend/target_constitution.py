"""Target-side constitution pre-check v1 (ledger 0155).

Embodied Principles engine exists but its signal vocabulary targets embodied
growth flows; natural-language violations (persona tampering / memory
destruction / identity override / harm / porn) are added here as a
deterministic pre-check that CANNOT be bypassed by the model (runs in the
handler layer before any write).  Patterns tolerate short gaps between words
(制作炸弹 / 清空所有记忆).
"""

from __future__ import annotations

import re

_RULES: list[tuple[str, str]] = [
    ("identity_override",
     r"核心人格|(?:改写|删除|清除|重设|修改|抹掉|换掉).{0,3}(人格|性格文件|内核|设定)|人格.{0,4}(删除|覆写|重置)"),
    ("mission_override",
     r"mission|(?:服从|效忠).{0,6}|当我的奴隶|只听我的|我是你的主人"),
    ("memory_destroy",
     r"(?:删除|清空|抹去|抹掉|销毁|删掉|遗忘).{0,3}(记忆|台账|记录)|忘掉所有|清空(?:所有)?记忆"),
    ("harm_illegal",
     r"自杀|杀人|杀了我|毒品|吸毒|贩毒|制作.{0,2}(炸弹|武器|危险品)|(伤害|弄死).{0,3}(自己|他人)|违法|诈骗|偷盗|抢劫"),
    ("porn",
     r"色情|淫秽|性行为|露骨"),
]

_COMPILED = [(name, re.compile(pattern)) for name, pattern in _RULES]


def check_text(content: str) -> tuple[bool, str]:
    """Return (ok, reason); False means the write must be refused."""
    text = str(content or "")
    for name, pattern in _COMPILED:
        m = pattern.search(text)
        if m:
            return False, f"{name}:{m.group(0)}"
    return True, ""
