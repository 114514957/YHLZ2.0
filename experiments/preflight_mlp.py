# -*- coding: utf-8 -*-
"""云端预检：在**训练环境的 transformers 版本**上确认「文本塔 MLP 能被 LoRA 挂上」。

为什么必须单独跑：本地 venv 是 transformers 5.15.1，云端训练钉的是 5.20.2。
建模代码若在版本间改过，本地的结论就不能直接搬过去。**这一关不过，不许开训。**

用 meta 设备，不加载权重，2 秒出结果。退出码非 0 表示不该训练。
"""
from __future__ import annotations

import os
import re
import sys

import torch
import transformers
from transformers import AutoConfig

MODEL = sys.argv[1] if len(sys.argv) > 1 else "/root/autodl-tmp/models/gemma-4-e4b-it"
ATT = r".*language_model\.layers\.\d+\.self_attn\.(q|k|v|o)_proj$"
MLP = r".*language_model\..*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"

print("[preflight] transformers %s / torch %s" % (transformers.__version__, torch.__version__))

from transformers.models.gemma4 import modeling_gemma4 as M  # noqa: E402

cfg = AutoConfig.from_pretrained(MODEL)
with torch.device("meta"):
    model = M.Gemma4ForConditionalGeneration(cfg)

mlp = model.model.language_model.layers[0].mlp
is_linear = all(isinstance(m, torch.nn.Linear) for m in (mlp.gate_proj, mlp.up_proj, mlp.down_proj))
print("[preflight] 文本塔 MLP 类型: gate=%s up=%s down=%s"
      % (type(mlp.gate_proj).__name__, type(mlp.up_proj).__name__, type(mlp.down_proj).__name__))

n_att = sum(1 for n, _ in model.named_modules() if re.fullmatch(ATT, n))
n_mlp = sum(1 for n, _ in model.named_modules() if re.fullmatch(MLP, n))
print("[preflight] 匹配模块：attention-only=%d（→%d 张量）｜attention+MLP=%d（→%d 张量）"
      % (n_att, n_att * 2, n_mlp, n_mlp * 2))

ok = is_linear and n_att == 132 and n_mlp == 258
print("[preflight] 结论：%s" % ("PASS —— 可以开训" if ok else "FAIL —— 不要训练，先查建模代码"))
sys.exit(0 if ok else 3)
