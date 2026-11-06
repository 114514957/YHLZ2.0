# -*- coding: utf-8 -*-
"""把两个 LoRA 精确合并成一个 adapter（秩拼接，不是近似）。

原理：
    单个 LoRA 的增量 = (α/r) · B·A
    想要 s1·Δ1 + s2·Δ2 = (α/r)(s1·B1A1 + s2·B2A2)
    令  A_cat = [A1; A2]（竖拼，rank r1+r2），B_cat = [s1·B1, s2·B2]（横拼）
    则  B_cat·A_cat = s1·B1A1 + s2·B2A2  —— **恒等，无误差**
    同时把 α 提到 2α（保持 α/r = 2 不变）。

所以「合并后 scale=1.0」应当与「运行时 --lora-scaled 0.7/0.3」**结果一致**——
这正好是个可验证的预言。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--sa", type=float, default=0.7)
    ap.add_argument("--sb", type=float, default=0.3)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    import torch  # noqa: PLC0415
    from safetensors.torch import load_file, save_file  # noqa: PLC0415

    fa = load_file(os.path.join(a.a, "adapter_model.safetensors"))
    fb = load_file(os.path.join(a.b, "adapter_model.safetensors"))
    assert set(fa) == set(fb), "两个 adapter 的键不一致"

    merged = {}
    for k in fa:
        A1, A2 = fa[k], fb[k]
        assert A1.shape == A2.shape, k
        if k.endswith("lora_A.weight"):
            merged[k] = torch.cat([A1, A2], dim=0)          # 竖拼（rank 相加）
        elif k.endswith("lora_B.weight"):
            merged[k] = torch.cat([a.sa * A1, a.sb * A2], dim=1)   # 横拼（各自缩放）
        else:
            raise SystemExit("不认识的键：%s" % k)

    os.makedirs(a.out, exist_ok=True)
    save_file(merged, os.path.join(a.out, "adapter_model.safetensors"))

    cfg = json.load(io.open(os.path.join(a.a, "adapter_config.json"), encoding="utf-8"))
    r_old = int(cfg["r"])
    cfg["r"] = r_old * 2
    cfg["lora_alpha"] = int(cfg["lora_alpha"]) * 2      # 保持 α/r 不变
    with io.open(os.path.join(a.out, "adapter_config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    for extra in ("chat_template.jinja",):
        src = os.path.join(a.a, extra)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(a.out, extra))

    n = sum(1 for _ in merged)
    sz = os.path.getsize(os.path.join(a.out, "adapter_model.safetensors"))
    print("合并完成：%s" % a.out)
    print("  张量 %d 个｜r %d→%d｜α %d→%d｜%d 字节"
          % (n, r_old, cfg["r"], int(cfg["lora_alpha"]) // 2, cfg["lora_alpha"], sz))
    print("  权重：%s×A + %s×B" % (a.sa, a.sb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
