# -*- coding: utf-8 -*-
"""逐条核对外部建议里的 5 个"Gemma4 陷阱"（能静态查的先查，不瞎猜）。

1. use_cache=False 是否真的破坏 Gemma4 注意力
2. ClippableLinear 到底包了哪些塔
3. lm_head 有没有 bias、是不是被训到
4. 我们实际的 trainable params 与"应有 5.95M"是否矛盾
5. 梯度累积 / DeepSpeed 我们是否踩到
"""
from __future__ import annotations

import glob
import json
import os
import re
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
BASE = os.path.join(ROOT, "models", "gemma4-hf", "gemma-4-e4b-it")

print("=" * 72)
print("① ClippableLinear 到底包裹了哪些塔（查 transformers 源码）")
print("=" * 72)
f = glob.glob(os.path.join(ROOT, ".venv", "Lib", "site-packages", "transformers",
                           "models", "gemma4", "modeling_gemma4.py"))
if not f:
    f = glob.glob(os.path.join(ROOT, ".venv", "Lib", "site-packages", "transformers",
                               "models", "**", "modeling_gemma*.py"), recursive=True)
if f:
    t = open(f[0], encoding="utf-8", errors="replace").read()
    print("   源码：%s" % os.path.basename(f[0]))
    cls = [m.start() for m in re.finditer(r"class .*ClippableLinear", t)]
    print("   ClippableLinear 定义：%d 处" % len(cls))
    # 谁用了它
    users = set()
    for m in re.finditer(r"ClippableLinear", t):
        seg = t[max(0, m.start() - 400):m.start()]
        for c in re.finditer(r"class (\w+)\(", seg):
            users.add(c.group(1))
    print("   出现在这些类的附近：%s" % sorted(users)[:10])
    # 文本 MLP 用的是什么
    for name in ("Gemma4TextMLP", "Gemma4MLP", "TextMLP"):
        m = re.search(r"class %s\b.*?(?=\nclass )" % name, t, re.S)
        if m:
            body = m.group(0)
            kinds = set(re.findall(r"self\.\w+\s*=\s*(?:nn\.(Linear|ClippableLinear))", body))
            print("   %s 里的线性层：%s" % (name, kinds or "（未识别）"))
else:
    print("   没找到 gemma4 modeling 源码")

print()
print("=" * 72)
print("② use_cache=False 在 Gemma4 注意力里有没有特殊分支")
print("=" * 72)
if f:
    hits = [ln.strip() for ln in t.splitlines()
            if "use_cache" in ln and ("if " in ln or "not " in ln)]
    print("   含 use_cache 判断的行 %d 条，前 6 条：" % len(hits))
    for h in hits[:6]:
        print("     " + h[:110])
else:
    print("   无源码可查")

print()
print("=" * 72)
print("③ lm_head 有没有 bias（读 safetensors 头，不加载模型）")
print("=" * 72)
idx = os.path.join(BASE, "model.safetensors.index.json")
names = []
if os.path.exists(idx):
    d = json.load(open(idx, encoding="utf-8"))
    names = list((d.get("weight_map") or {}).keys())
    print("   分片索引里的张量 %d 个" % len(names))
else:
    st = os.path.join(BASE, "model.safetensors")
    if os.path.exists(st):
        with open(st, "rb") as fh:
            n = struct.unpack("<Q", fh.read(8))[0]
            hdr = json.loads(fh.read(n))
        names = [k for k in hdr if k != "__metadata__"]
        print("   单文件里的张量 %d 个" % len(names))
    else:
        print("   找不到权重文件")

lm = [x for x in names if "lm_head" in x]
print("   lm_head 相关张量：%s" % (lm or "无（可能是 tied embedding）"))
emb = [x for x in names if "embed_tokens" in x]
print("   embed_tokens：%s" % (emb[:2] or "无"))
bias_cnt = sum(1 for x in names if x.endswith(".bias"))
print("   带 .bias 的张量总数：%d" % bias_cnt)

print()
print("=" * 72)
print("④ 我们实际的 trainable params vs 建议里的 5.95M")
print("=" * 72)
print("   我们的训练日志：trainable params: 34,881,536 / all 7,975,982,368 = 0.4373%")
print("   建议里说的 5.95M≈0.14% —— 那是**只训 q/v** 的量级；")
print("   我们训了 q,k,v,o + gate,up,down 共 7 类（含 MLP），所以是 34.9M，量级合理。")

print()
print("=" * 72)
print("⑤ 梯度累积 / DeepSpeed")
print("=" * 72)
for cfg in glob.glob(os.path.join(ROOT, "dist", "retrain_pkg_gemma_*", "config", "*.json")):
    try:
        d = json.load(open(cfg, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        continue
    print("   %-52s grad_accum=%s｜deepSpeed=%s｜use_cache=%s"
          % (os.path.relpath(cfg, ROOT)[-52:], d.get("grad_accum"),
             d.get("deepspeed", "无"), d.get("use_cache", "（代码里设 False）")))
