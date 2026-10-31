#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V9 素材 token 实测（只读）。

用途：用本地 Gemma 4 E4B 的 tokenizer.json（BPE，262144 词表）实测素材集的
真实 token 量，为「素材量够不够」提供数据依据，而不是按字符数估算。

口径说明：
- 本脚本自己实现 BPE（normalizer 空格→▁ / Split 空格 / byte_fallback），
  不依赖 transformers / tokenizers（本机未装）。结果是 token 数的**近似实测**，
  与官方 tokenizer 可能有极小差异（未做 unk 合并细节），不对训练用长度做承诺。
- 只统计 assistant（元亨/利贞等非老爹发言）监督 token 与整块 token 两种口径。
- 不改动任何素材文件。

用法：
    python tools/v9_token_measure.py                 # 测主素材集
    python tools/v9_token_measure.py --json out.json # 另存结构化结果
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from typing import Dict, List, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKENIZER_PATH = os.path.join(
    PROJECT_ROOT, "models", "gemma4-hf", "gemma4-e4b-text", "tokenizer.json"
)
DEFAULT_OUT_DIR = os.path.join(
    PROJECT_ROOT, "cache", "v9_materials_preparation", "20261013"
)

# 主素材集（与 docs/素材 现状一致；.md 文件）
MATERIAL_FILES = [
    "docs/素材/对话样本.md",
    "docs/素材/记忆样本_v2.md",
    "docs/素材/诚实边界样本.md",
    "docs/素材/安全拒绝样本.md",
    "docs/素材/承认不确定样本.md",
    "docs/素材/真实对话样本.md",
    "docs/素材/优质样本.md",
    "docs/素材/黄金样本.md",
    "docs/素材/_修订/批次01_去IT味_对话-1至15_20261011.md",
    "docs/素材/_草稿/S01_长块首批_续写扩写新写_20261012.md",
    "docs/素材/_草稿/测试样本_新线两集_v0_20261011.md",
]

USER_SPEAKERS = {"老爹"}


class GemmaBPE:
    """最小实现的 BPE 分词器（读 tokenizer.json）。"""

    def __init__(self, path: str) -> None:
        with io.open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        model = data["model"]
        self.vocab: Dict[str, int] = model["vocab"]
        merges = model.get("merges") or []
        self.ranks: Dict[Tuple[str, str], int] = {}
        for i, m in enumerate(merges):
            if isinstance(m, str):
                parts = m.split(" ")
                if len(parts) != 2:
                    continue
                self.ranks[(parts[0], parts[1])] = i
            else:
                self.ranks[(m[0], m[1])] = i
        self.byte_fallback = bool(model.get("byte_fallback", True))
        self.unk = model.get("unk_token") or "<unk>"

    # --- 内部 ---
    @staticmethod
    def _to_bytes(ch: str) -> List[str]:
        return ["<0x%02X>" % b for b in ch.encode("utf-8")]

    def _encode_word(self, word: str) -> List[str]:
        symbols: List[str] = []
        for ch in word:
            if ch in self.vocab:
                symbols.append(ch)
            elif self.byte_fallback:
                symbols.extend(self._to_bytes(ch))
            else:
                symbols.append(self.unk)
        if len(symbols) < 2:
            return symbols
        while True:
            best_rank = None
            best_idx = -1
            for i in range(len(symbols) - 1):
                rank = self.ranks.get((symbols[i], symbols[i + 1]))
                if rank is not None and (best_rank is None or rank < best_rank):
                    best_rank = rank
                    best_idx = i
            if best_idx < 0:
                break
            merged = symbols[best_idx] + symbols[best_idx + 1]
            symbols[best_idx : best_idx + 2] = [merged]
        return symbols

    # --- 对外 ---
    def encode(self, text: str) -> List[str]:
        if not text:
            return []
        spaced = text.replace(" ", "\u2581")
        tokens: List[str] = []
        for word in spaced.split("\u2581"):
            if word == "":
                tokens.append("\u2581")
                continue
            tokens.append("\u2581")
            tokens.extend(self._encode_word(word))
        return [t for t in tokens if t != ""]

    def count(self, text: str) -> int:
        return len(self.encode(text))


# ---------------- 素材解析 ----------------

META_LINE = re.compile(r"^-\s+[a-z_]+:")
BLOCK_HEAD = re.compile(r"^(##+)\s+(.*)$")
SPEAK_LINE = re.compile(r"^#{3,4}\s*([^\s:：]+?)\s*(问|答)\s*(\d+)\s*$")
FENCE = re.compile(r"^\s*```")


def parse_blocks(text: str) -> List[Dict[str, object]]:
    """按 ## 标题切块，抽取每块内 发言者/轮次 的文本。"""
    lines = text.splitlines()
    blocks: List[Dict[str, object]] = []
    cur: Dict[str, object] | None = None
    speaker: str | None = None
    in_fence = False
    for line in lines:
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        head = BLOCK_HEAD.match(line)
        if head and not line.strip().startswith("###"):
            if cur is not None:
                blocks.append(cur)
            cur = {"title": head.group(2).strip(), "turns": []}
            speaker = None
            continue
        if cur is None:
            continue
        m = SPEAK_LINE.match(line)
        if m:
            speaker = m.group(1)
            cur["turns"].append({"speaker": speaker, "text": ""})
            continue
        if line.strip() == "" or META_LINE.match(line):
            if line.strip() == "":
                speaker = None
            continue
        if speaker is not None:
            turns = cur["turns"]
            turns[-1]["text"] += line.strip()
    if cur is not None:
        blocks.append(cur)
    return blocks


def measure_file(tok: GemmaBPE, rel_path: str) -> Dict[str, object]:
    abs_path = os.path.join(PROJECT_ROOT, rel_path)
    with io.open(abs_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    blocks = parse_blocks(text)
    per_block: List[Dict[str, object]] = []
    total_full = 0
    total_assistant = 0
    total_chars = 0
    assistant_turns = 0
    for b in blocks:
        turns = b["turns"]  # type: ignore[index]
        if not turns:
            continue
        full_tokens = 0
        asst_tokens = 0
        asst_chars = 0
        rounds = 0
        for t in turns:  # type: ignore[union-attr]
            t_tokens = tok.count(t["text"])  # type: ignore[index]
            full_tokens += t_tokens
            if t["speaker"] not in USER_SPEAKERS:  # type: ignore[operator]
                asst_tokens += t_tokens
                asst_chars += len(t["text"])  # type: ignore[arg-type]
                assistant_turns += 1
            if t["speaker"] == "老爹":  # type: ignore[comparison-overlap]
                rounds += 1
        total_full += full_tokens
        total_assistant += asst_tokens
        total_chars += sum(len(t["text"]) for t in turns)  # type: ignore[arg-type]
        per_block.append(
            {
                "title": b["title"],
                "rounds": rounds,
                "full_tokens": full_tokens,
                "assistant_tokens": asst_tokens,
                "assistant_chars": asst_chars,
            }
        )
    n = len(per_block)
    asst = sorted(p["assistant_tokens"] for p in per_block)
    return {
        "path": rel_path,
        "blocks": n,
        "total_full_tokens": total_full,
        "total_assistant_tokens": total_assistant,
        "total_chars": total_chars,
        "assistant_turns": assistant_turns,
        "avg_full_tokens_per_block": round(total_full / n, 1) if n else 0,
        "avg_assistant_tokens_per_block": round(total_assistant / n, 1) if n else 0,
        "median_assistant_tokens_per_block": asst[n // 2] if n else 0,
        "p90_assistant_tokens_per_block": asst[int(n * 0.9)] if n else 0,
        "max_assistant_tokens_per_block": asst[-1] if n else 0,
        "per_block": per_block,
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="V9 素材 token 实测（只读）")
    ap.add_argument("--json", default="", help="结果另存 JSON 路径")
    ap.add_argument("--files", nargs="*", default=None, help="只测指定文件")
    args = ap.parse_args(argv)

    if not os.path.exists(TOKENIZER_PATH):
        print("找不到 tokenizer: %s" % TOKENIZER_PATH)
        return 3
    t0 = time.time()
    tok = GemmaBPE(TOKENIZER_PATH)
    print("tokenizer 载入完成：词表 %d，merges %d，%.1fs"
          % (len(tok.vocab), len(tok.ranks), time.time() - t0))

    # 自检：中文/英文/标点的 token 数应为正且合理
    probe = "元亨今天心情不错，咱去院里看看雪。"
    print("自检样例 token 数：%d（字符 %d）→ %.2f tok/char"
          % (tok.count(probe), len(probe), tok.count(probe) / len(probe)))

    files = args.files if args.files else MATERIAL_FILES
    results = []
    print()
    print("%-46s %6s %12s %12s %8s" % ("文件", "块数", "整块token", "监督token", "均/块"))
    for rel in files:
        if not os.path.exists(os.path.join(PROJECT_ROOT, rel)):
            print("跳过（不存在）：%s" % rel)
            continue
        r = measure_file(tok, rel)
        results.append(r)
        print("%-46s %6d %12d %12d %8.1f"
              % (os.path.basename(rel), r["blocks"], r["total_full_tokens"],
                 r["total_assistant_tokens"], r["avg_assistant_tokens_per_block"]))

    tot_blocks = sum(r["blocks"] for r in results)
    tot_asst = sum(r["total_assistant_tokens"] for r in results)
    tot_full = sum(r["total_full_tokens"] for r in results)
    print()
    print("合计：%d 块，整块 %d tokens，assistant 监督 %d tokens，均值 %.1f 监督token/块"
          % (tot_blocks, tot_full, tot_asst, tot_asst / tot_blocks if tot_blocks else 0))

    out_dir = DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    out_path = args.json or os.path.join(out_dir, "token_measure.json")
    with io.open(out_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "tokenizer": TOKENIZER_PATH,
                "note": "自实现 BPE 近似实测；未做 unk 合并细节；只读统计",
                "files": results,
                "totals": {
                    "blocks": tot_blocks,
                    "full_tokens": tot_full,
                    "assistant_tokens": tot_asst,
                },
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )
    print("结果已存：%s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
