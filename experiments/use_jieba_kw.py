# -*- coding: utf-8 -*-
"""把话题词换成 jieba 分词（中文不分词出来的都是"我也/我这"这种垃圾）。

改法：_kw 内部优先用 jieba，失败自动回退到 n-gram（不引入硬依赖）。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "qq_intel.py")
t = io.open(P, encoding="utf-8").read()

NEW = '''def _kw(texts: list[str], k: int = 3) -> list[str]:
    """话题词：**优先 jieba 分词**（未被分词的中文 n-gram 全是"我也/我这"这类垃圾），
    jieba 不可用时退回 n-gram。只收中文、≥2 字、非停用词、频次 ≥3。"""
    cnt: Counter[str] = Counter()
    try:
        import jieba
        for t in texts:
            for w in jieba.cut(_NONWORD.sub("", str(t or ""))):
                w = w.strip()
                if not _CN.match(w) or w in STOP:
                    continue
                cnt[w] += 1
    except Exception:  # noqa: BLE001
        for t in texts:
            s = _NONWORD.sub("", str(t or ""))
            for n in (2, 3, 4):
                for i in range(len(s) - n + 1):
                    g = s[i:i + n]
                    if not _CN.match(g) or g in STOP:
                        continue
                    cnt[g] += 1
    out: list[str] = []
    for g, c in cnt.most_common(80):
        if c < 3:
            break
        if any(g in s or s in g for s in out):
            continue
        out.append(g)
        if len(out) >= k:
            break
    return out
'''

start = t.find("def _kw(")
end = t.find("def group_cards(")
assert start > 0 and end > start, "定位失败"
t = t[:start] + NEW + "\n\n" + t[end:]
io.open(P, "w", encoding="utf-8").write(t)
print("_kw 已改为 jieba 优先")
