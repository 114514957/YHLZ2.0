# -*- coding: utf-8 -*-
"""随机对照：把真方向的每个维度打乱，模长和层结构不变。

这是台账 1015 定的纪律：没有随机对照，「输出变了」不算证据。
"""
from __future__ import annotations

import os
import sys

import numpy as np

import gguf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
STEER = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench\steer"
SRC = os.path.join(STEER, "cvec_style_mean.gguf")
DST = os.path.join(STEER, "cvec_random.gguf")

r = gguf.GGUFReader(SRC)
rng = np.random.default_rng(20261104)
w = gguf.GGUFWriter(DST, "controlvector")
w.add_string("controlvector.model_hint", "gemma4")
n = 0
for t in r.tensors:
    arr = np.array(t.data, dtype=np.float32).reshape(-1).copy()
    rng.shuffle(arr)
    w.add_tensor(t.name, arr)
    n += 1
w.add_uint32("controlvector.layer_count", n)
w.write_header_to_file()
w.write_kv_data_to_file()
w.write_tensors_to_file()
w.close()
print("wrote %s with %d shuffled tensors" % (DST, n))
