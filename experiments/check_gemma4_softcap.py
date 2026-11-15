# -*- coding: utf-8 -*-
"""查 Gemma4 独有机制的取值 + 生产 GGUF 里到底有没有 softcap。"""
from __future__ import annotations

import json
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
BASE = os.path.join(ROOT, "models", "gemma4-hf", "gemma-4-e4b-it")

print("=" * 74)
print("① Gemma4 独有机制的取值")
print("=" * 74)
cfg = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8-sig"))
tc = cfg.get("text_config") or cfg
for k in ("final_logit_softcapping", "attn_logit_softcapping", "layer_types",
          "num_kv_shared_layers", "num_global_key_value_heads", "global_head_dim",
          "attention_k_eq_v", "enable_moe_block", "num_experts", "top_k_experts",
          "expert_intermediate_size", "hidden_size_per_layer_input",
          "num_hidden_layers", "sliding_window", "rope_parameters"):
    v = tc.get(k, "—")
    if isinstance(v, list):
        v = "%d 项：%s..." % (len(v), v[:6])
    print("   %-30s %s" % (k, str(v)[:110]))

print()
print("=" * 74)
print("② 生产 GGUF 的元数据（看架构名与 softcap 有没有写进去）")
print("=" * 74)


def gguf_meta(path: str) -> dict:
    """极简 GGUF 读取：只拿 KV 元数据（不读张量）。"""
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"GGUF":
            raise ValueError("not gguf")
        ver = struct.unpack("<I", f.read(4))[0]
        n_tensors = struct.unpack("<Q", f.read(8))[0]
        n_kv = struct.unpack("<Q", f.read(8))[0]

        def rd_str() -> str:
            n = struct.unpack("<Q", f.read(8))[0]
            return f.read(n).decode("utf-8", "replace")

        def rd_val(t: int):
            if t == 0:
                return struct.unpack("<B", f.read(1))[0]
            if t == 1:
                return struct.unpack("<b", f.read(1))[0]
            if t == 2:
                return struct.unpack("<H", f.read(2))[0]
            if t == 3:
                return struct.unpack("<h", f.read(2))[0]
            if t == 4:
                return struct.unpack("<I", f.read(4))[0]
            if t == 5:
                return struct.unpack("<i", f.read(4))[0]
            if t == 6:
                return struct.unpack("<f", f.read(4))[0]
            if t == 7:
                return bool(struct.unpack("<B", f.read(1))[0])
            if t == 8:
                return rd_str()
            if t == 9:
                et = struct.unpack("<I", f.read(4))[0]
                n = struct.unpack("<Q", f.read(8))[0]
                return [rd_val(et) for _ in range(n)]
            if t == 10:
                return struct.unpack("<Q", f.read(8))[0]
            if t == 11:
                return struct.unpack("<q", f.read(8))[0]
            if t == 12:
                return struct.unpack("<d", f.read(8))[0]
            raise ValueError("type %d" % t)

        meta = {"__version": ver, "__n_tensors": n_tensors}
        for _ in range(n_kv):
            k = rd_str()
            t = struct.unpack("<I", f.read(4))[0]
            meta[k] = rd_val(t)
        return meta


cands = [
    os.path.join(ROOT, "models", "gemma4-gguf", "gemma-4-E4B_q4_0-it.gguf"),
    os.path.join(ROOT, "models", "gemma4-gguf", "gemma-4-E4B-it-q4_0.gguf"),
]
for p in cands:
    if not os.path.exists(p):
        continue
    try:
        m = gguf_meta(p)
    except Exception as ex:  # noqa: BLE001
        print("   %s 读失败：%s" % (os.path.basename(p), ex))
        continue
    print("   %s（%d 张量）" % (os.path.basename(p), m.get("__n_tensors", 0)))
    arch = m.get("general.architecture")
    print("     general.architecture = %s" % arch)
    soft = {k: v for k, v in m.items() if "softcap" in k.lower() or "soft_cap" in k.lower()}
    print("     softcap 相关键：%s" % (soft or "❌ 没有任何 softcap 元数据"))
    key3 = {k: m[k] for k in m if k.startswith(str(arch) + ".") and
            any(s in k for s in ("logit", "soft", "sliding", "rope", "head"))}
    for k, v in list(key3.items())[:10]:
        print("     %-46s %s" % (k, str(v)[:60]))
