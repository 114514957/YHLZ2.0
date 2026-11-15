# -*- coding: utf-8 -*-
"""读拒绝方向向量（cvec GGUF），看它的结构和维度。"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(YH, "llm_workbench", "steer", "cvec_refuse_mean.gguf")

sys.path.insert(0, os.path.join(YH, "models", "llama-cuda", "src",
                                "llama.cpp-b10991", "gguf-py"))
try:
    from gguf import GGUFReader  # noqa: E402
except Exception as ex:  # noqa: BLE001
    print("gguf-py 导入失败：%s" % ex)
    sys.exit(1)

r = GGUFReader(P)
print("张量 %d 个｜KV %d 条" % (len(r.tensors), len(r.fields)))
for t in list(r.tensors)[:3] + list(r.tensors)[-2:]:
    print("  %-22s shape=%s type=%s" % (t.name, list(t.shape), t.tensor_type))
    break
names = [t.name for t in r.tensors]
print("  前 5 个名字：%s" % names[:5])
print("  维度：%s" % list(r.tensors[0].shape))
import numpy as np  # noqa: E402
arr = np.array(r.tensors[0].data[:8])
print("  前 8 个分量：%s" % np.round(arr, 4))
print("  范数（全向量）：%.4f" % float(np.linalg.norm(np.array(r.tensors[0].data[:]))))
