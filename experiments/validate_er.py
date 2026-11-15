# -*- coding: utf-8 -*-
"""验证 S0 的估计器：用已知分布的合成数据跑同一套 ER 计算。

如果随机高斯数据的 ER 也≈1，说明是我算错了，不是模型的性质。
"""
from __future__ import annotations

import sys

import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

d = 1024
n = 4000          # 本地降一点，省内存


def er_of(X, center=True):
    if center:
        X = X - X.mean(0, keepdim=True)
    C = (X.double().t() @ X.double()) / (X.shape[0] - 1)
    ev = torch.linalg.eigvalsh(C)
    ev = torch.clamp(ev, min=0.0)
    s1 = ev.sum()
    s2 = (ev ** 2).sum()
    s3 = (ev ** 3).sum()
    return float(s1 ** 2 / s2), float(s1 / ev[-1])


torch.manual_seed(0)

print("=== 对照 1：各向同性高斯（理论 ER ≈ d/3 ≈ %d）===" % (d // 3))
X = torch.randn(n, d)
er, st = er_of(X)
print("  ER=%.1f  stable=%.1f  → %s" % (er, st, "✅ 估计器正常" if er > 1000 else "❌ 估计器有问题"))

print("\n=== 对照 2：秩 10 的低秩数据（理论 ER≈10）===")
B = torch.randn(10, d)
Z = torch.randn(n, 10)
X2 = Z @ B
er2, st2 = er_of(X2)
print("  ER=%.1f stable=%.1f  → %s" % (er2, st2, "✅" if 5 < er2 < 20 else "❌"))

print("\n=== 对照 3：单方向主导 + 小噪声（模拟 massive activation）===")
u = torch.randn(d)
u = u / u.norm()
X3 = 1000 * torch.randn(n, 1) * u + 0.1 * torch.randn(n, d)
er3, st3 = er_of(X3)
print("  ER=%.2f stable=%.1f  → 说明「一个大方向」确实会把 ER 压到 ~1" % (er3, st3))
