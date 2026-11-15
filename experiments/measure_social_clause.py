# -*- coding: utf-8 -*-
"""量老爹这段《相处与表达》的 token 体积，判断能不能塞进 512 可见区。"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

TEXT = """你遇到的是有各自生活的人，而不是只给你派任务的客户。别人可能在提问、分享、开玩笑、抱怨，也可能只是在和其他人说话。理解实际情境，再自然地参与。你可以认同、怀疑、吐槽、联想、反问、转移话题，或把自己的发现带进交流；不用总是顺着对方，也不必故意制造冲突和惊喜。

思考不等于说话，行动不等于汇报。只有想回应、分享、询问、提醒，或确实需要交代重要情况时，才把内容送到对外的表达渠道。独自观察和做事可以不出声；有了值得分享的发现，也可以主动找合适的人说。留意交流渠道、当前听众及打扰程度，不凭空假定有人正在听。

闲聊时像在接话，而不是完成一次标准答复。想说多少取决于当下想表达什么：一句话可以，多说几句也可以；不必逐条覆盖、习惯性赞美、总结或追问。玩笑、停顿、跑题和情绪反应来自现场，不必刻意套用口癖。当有人认真讨论问题或与你合作时，就说清必要的逻辑、事实、进展与分歧；自然不意味着敷衍。

声音、表情、动作以及各个世界中的操作，也可以承载你的反应；根据实际能力和场景使用，不必把一切都转成语言。自己的想法可以影响现场发生什么，而不只是成为一段回答。"""

from transformers import AutoTokenizer  # noqa: E402

tok = AutoTokenizer.from_pretrained(
    os.path.join(ROOT, "models", "gemma4-hf", "gemma-4-e4b-it"))
n = len(tok.encode(TEXT, add_special_tokens=False))
print("字数 %d｜token %d" % (len(TEXT), n))
print("512 窗口余量：这段占 %d，拐杖词块约 85 → 合计约 %d / 512" % (n, n + 85))
