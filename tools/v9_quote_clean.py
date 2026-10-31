"""台词清洗 v2：只留台词（ledger 0864）。

v1 的教训：维基语录页的台词**没有引号**，靠引号筛只剩 66 条；萌娘页大量是设定说明。
v2 判据：
  1) **利用角色标题**（`== 空（荧） ==` 清洗后残留 `空（荧）====`）切段：标题下的行才当台词候选；
  2) **说话特征**：出现 我/你/咱/我们/你们 之一，且带语气词（吧/呢/吗/啊/哦/哼/喂/嗯/嘛/啦/呀/咧）；
     或整行被引号包住；
  3) **排除说明文**：研发/开发/发行/游戏/作品/角色扮演/世界观/设定/组织/文明/灾难/抗体/圣痕/
     神之键/玩家/剧情/版本/活动/分类/目录/待补充/参见/外部链接/简介/背景 等；
  4) 长度 6–120；无 URL/模板残留。
输出 data/pd/v9_game_quotes_clean.jsonl（带 who/game），并打印样例供老爹过目。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pd"
SRC = ["v9_game_quotes.jsonl", "v9_game_quotes_extra.jsonl"]

HEAD_RE = re.compile(r"^(?P<who>[^=\n]{1,24}?)\s*=+\s*$")
PRONOUN = re.compile(r"[我你咱]|我們|你们|你們")
PARTICLE = re.compile(r"[吧呢吗啊哦哼喂嗯嘛啦呀咧哈嘿哎唉]")
DESC = ("研发", "開發", "开发", "发行", "發行", "游戏", "遊戲", "作品", "角色扮演",
        "世界觀", "世界观", "设定", "設定", "组织", "組織", "文明", "灾难", "災難",
        "抗体", "抗體", "圣痕", "聖痕", "神之键", "神之鍵", "玩家", "剧情", "劇情",
        "版本", "活动", "活動", "分类", "分類", "目录", "目錄", "待補充", "待补充",
        "参见", "參見", "外部链接", "外部連結", "简介", "簡介", "背景", "列表",
        "排序", "收錄", "收录", "由米哈游", "由米哈遊")
BULLET = re.compile(r"^[*#:;·\-\s]+")


def is_speech(line: str) -> bool:
    if not (6 <= len(line) <= 120):
        return False
    if "http" in line or "[[" in line or "{{" in line:
        return False
    if any(d in line for d in DESC):
        return False
    if line.endswith("====") or HEAD_RE.match(line):
        return False
    if re.fullmatch(r"[（(].*[)）]", line):
        return False
    quoted = bool(re.search(r"[“「『][^”」』]{4,}[”」』]", line))
    return quoted or (bool(PRONOUN.search(line)) and bool(PARTICLE.search(line)))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kept, dropped = [], []
    seen = set()
    for name in SRC:
        p = OUT / name
        if not p.exists():
            continue
        who = None
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            t = BULLET.sub("", str(d.get("text") or "").strip())
            m = HEAD_RE.match(t)
            if m and not t.endswith("。"):
                who = m.group("who").strip(" 「」『』")
                continue
            if not is_speech(t):
                dropped.append(t)
                continue
            h = hashlib.sha256(t.encode()).hexdigest()[:16]
            if h in seen:
                continue
            seen.add(h)
            kept.append({**d, "text": t, "content_hash": h})   # 不写 who：标题归属不可靠，避免伪造

    out = OUT / "v9_game_quotes_clean.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r in kept:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    by_game: dict[str, int] = {}
    for r in kept:
        g = r.get("game") or "?"
        by_game[g] = by_game.get(g, 0) + 1
    rep = {"kept": len(kept), "dropped": len(dropped), "by_game": by_game,
           "kept_chars": sum(len(r["text"]) for r in kept),
           "sample_kept": [f"{r.get('who') or '?'}: {r['text']}" for r in kept[:10]],
           "file": str(out.relative_to(ROOT))}
    (OUT / "clean_manifest.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("kept", "dropped", "by_game",
                                          "kept_chars", "sample_kept")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
