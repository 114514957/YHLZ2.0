# -*- coding: utf-8 -*-
"""硬规则机械清洗（2026-11-14，老爹：「破折号一个都不许用」）。

为什么用代码而不是光靠提示词：
  破折号是**唯一一条可以 100% 机械判定**的硬规则。模型再听话也可能漏，
  而这一条完全可以事后确定性地修掉，不需要它"自觉"。

做的只有一件事：把破折号换成句号（老爹给的替换方案就是"要断句就写句号"）。
不做任何别的改写——**不删词、不改语序、不动内容**。

用法：
    from backend.text_scrub import scrub
    ans = scrub(ans)
"""
from __future__ import annotations

import re

# 中文破折号（两个连写是最常见形态）、单个、英文长横、全角减号
_DASH_RUN = re.compile(r"[—–―－]{1,}")

# 句末已有标点时不要叠出两个句号
_DUP_PUNCT = re.compile(r"。{2,}")


def has_dash(text: str) -> bool:
    return bool(_DASH_RUN.search(text or ""))


def scrub(text: str) -> str:
    """把破折号统一换成句号，并收拾由此产生的重复标点/多余空格。"""
    t = text or ""
    if not t or not _DASH_RUN.search(t):
        return t
    # 破折号前若是逗号/顿号也一并替换（「，——」→「。」）
    t = re.sub(r"[，,、]?\s*[—–―－]{1,}\s*", "。", t)
    t = _DUP_PUNCT.sub("。", t)
    # 句号后面紧跟标点的情况（「。，」）
    t = re.sub(r"。([，,、；;])", r"。", t)
    # 收尾空格
    return t.strip()


def violations(text: str) -> list[str]:
    """返回命中的硬规则名（给统计用，不改文本）。"""
    t = text or ""
    out = []
    if _DASH_RUN.search(t):
        out.append("破折号")
    if re.search(r"不是[^。！？\n]{1,20}[，,]?而是", t):
        out.append("对称句")
    if re.search(r"(这条|这个)?我?认了?[。！]?$", t.strip()):
        out.append("表态冒充内容")
    if re.search(r"值得一看|挺有意思|可以一试|可以试试", t):
        out.append("空泛评价")
    if re.search(r"(这话|这个|这句)我?不接|这个我不聊", t):
        out.append("姿态挡箭牌")
    if re.search(r"满意了?[?？]?|够了吗?[?？]?", t):
        out.append("阴阳收尾")
    if re.search(r"还需要我|还有什么可以帮|我理解你的意思|随时待命", t):
        out.append("助理腔")
    return out


if __name__ == "__main__":
    cases = [
        "这句话稳——接得漂亮。",
        "不是他不想来—而是来不了。",
        "行了——就这样吧——",
        "破折号测试：他说——你听。",
        "这句话我认。",
        "满意了？",
        "我理解你的意思，还需要我做什么吗",
    ]
    for c in cases:
        s = scrub(c)
        print("原文：%s" % c)
        print("清洗：%s" % s)
        print("命中：%s" % ("、".join(violations(c)) or "无"))
        print()
