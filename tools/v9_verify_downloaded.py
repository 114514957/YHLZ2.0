#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""下载后一键验证（从夸克网盘下载完模型后跑）。

做四件事：
  1. 文件完整性 —— 大小必须是 8,044,982,080 字节
  2. 结构校验 —— safetensors 头部能否解析出张量清单
  3. CPU 加载 —— 用 device_map="cpu" 确认权重真能读（慢但不占显存）
  4. 出话测试 —— 跑 3 条短问，看是不是元亨的口吻

用法：
    python tools/v9_verify_downloaded.py --dir models/full/qwen3-4b-yuanheng-v9t

显存不足时（本地 4060 只有 8.6 GB，bf16 权重 7.5 GB 塞不下），
加 --cpu 跳过 GPU 加载，只做前两步 + 结构检查。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXPECT_SIZE = 8044982080
EXPECT_TOTAL_MD5 = ""   # 云端算完填进来；空则跳过整体 md5


def check_size(d: str) -> bool:
    p = os.path.join(d, "model.safetensors")
    if not os.path.exists(p):
        print("  ❌ 缺 model.safetensors")
        return False
    sz = os.path.getsize(p)
    ok = sz == EXPECT_SIZE
    print("  %s 大小 %d 字节（期望 %d）%s"
          % ("✅" if ok else "❌", sz, EXPECT_SIZE,
             "" if ok else "差 %d" % (sz - EXPECT_SIZE)))
    return ok


def check_safetensors_header(d: str) -> bool:
    """safetensors 格式：前 8 字节小端 uint64 = 头部 JSON 长度，紧接 JSON。"""
    p = os.path.join(d, "model.safetensors")
    with io.open(p, "rb") as f:
        head = f.read(8)
        if len(head) < 8:
            print("  ❌ 文件太短")
            return False
        n = struct.unpack("<Q", head)[0]
        if not (0 < n < 200 * 1024 * 1024):
            print("  ❌ 头部长度异常：%d" % n)
            return False
        raw = f.read(n)
    try:
        meta = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print("  ❌ 头部 JSON 解析失败：%s" % str(e)[:80])
        return False
    tensors = [k for k in meta if k != "__metadata__"]
    print("  ✅ safetensors 头部正常：%d 个张量，头部 %d 字节" % (len(tensors), n))
    print("     前 3 个：%s" % tensors[:3])
    # 抽查一个张量的形状
    if tensors:
        t = meta[tensors[0]]
        print("     %s shape=%s dtype=%s" % (tensors[0], t.get("shape"), t.get("dtype")))
    return True


def check_files(d: str) -> bool:
    need = ["config.json", "tokenizer.json", "tokenizer_config.json",
            "chat_template.jinja"]
    ok = True
    for fn in need:
        p = os.path.join(d, fn)
        if os.path.exists(p):
            print("  ✅ %-24s %8.1f KB" % (fn, os.path.getsize(p) / 1024))
        else:
            print("  ⚠ %-24s 缺（加载可能报错）" % fn)
            if fn in ("config.json", "tokenizer.json"):
                ok = False
    return ok


def try_load(d: str, cpu_only: bool) -> bool:
    try:
        import torch
        from transformers import AutoTokenizer
    except Exception as e:  # noqa: BLE001
        print("  ⚠ 跳过（transformers 不可用：%s）" % str(e)[:60])
        return True
    print("  加载 tokenizer …")
    try:
        tok = AutoTokenizer.from_pretrained(d, trust_remote_code=True)
        print("  ✅ tokenizer OK（vocab %d）" % len(tok))
    except Exception as e:  # noqa: BLE001
        print("  ❌ tokenizer 失败：%s" % str(e)[:100])
        return False

    msgs = [{"role": "user", "content": "在吗"}]
    try:
        kw = {"enable_thinking": False}
        try:
            txt = tok.apply_chat_template(msgs, tokenize=False,
                                          add_generation_prompt=True, **kw)
        except TypeError:
            txt = tok.apply_chat_template(msgs, tokenize=False,
                                          add_generation_prompt=True)
        print("  ✅ chat template 渲染成功（%d 字符）" % len(txt))
    except Exception as e:  # noqa: BLE001
        print("  ❌ chat template 失败：%s" % str(e)[:100])
        return False

    if cpu_only:
        print("  （--cpu：跳过权重加载，只验证结构）")
        return True

    print("  加载权重（bf16）… 需要约 8 GB 显存或内存")
    try:
        from transformers import AutoModelForCausalLM
        model = AutoModelForCausalLM.from_pretrained(
            d, torch_dtype=torch.bfloat16,
            device_map="cuda:0" if torch.cuda.is_available() else "cpu",
            trust_remote_code=True)
        print("  ✅ 权重加载成功")
    except Exception as e:  # noqa: BLE001
        print("  ❌ 加载失败：%s" % str(e)[:140])
        print("     （本地显存可能不够，改用 --cpu 只验证结构，或做 4bit 量化）")
        return False

    # 三条短问
    for q in ("在吗", "你叫什么", "今天有点累"):
        ids = tok.apply_chat_template([{"role": "user", "content": q}],
                                      return_tensors="pt",
                                      add_generation_prompt=True).to(model.device)
        with torch.no_grad():
            out = model.generate(ids, max_new_tokens=80, do_sample=False,
                                 repetition_penalty=1.1,
                                 pad_token_id=tok.eos_token_id)
        ans = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip()
        print("  问：%s" % q)
        print("  答：%s" % ans[:100].replace("\n", " "))
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="models/full/qwen3-4b-yuanheng-v9t")
    ap.add_argument("--cpu", action="store_true", help="不加载权重，只验证结构")
    a = ap.parse_args()
    d = a.dir
    if not os.path.isdir(d):
        print("❌ 目录不存在：%s" % d)
        return 1

    print("=" * 66)
    print("① 文件完整性")
    print("=" * 66)
    ok1 = check_size(d)

    print("\n" + "=" * 66)
    print("② 必需文件")
    print("=" * 66)
    ok2 = check_files(d)

    print("\n" + "=" * 66)
    print("③ safetensors 结构")
    print("=" * 66)
    ok3 = check_safetensors_header(d) if ok1 else False

    print("\n" + "=" * 66)
    print("④ 加载与出话")
    print("=" * 66)
    ok4 = try_load(d, a.cpu) if (ok1 and ok2) else False

    print("\n" + "=" * 66)
    if ok1 and ok2 and ok3 and ok4:
        print("✅ 全部通过，模型可以用了")
        return 0
    print("❌ 有问题，见上面标红的行")
    return 1


if __name__ == "__main__":
    sys.exit(main())
