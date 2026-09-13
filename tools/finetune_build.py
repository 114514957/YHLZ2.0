"""Build fine-tune data from real sources (ledger 0318).

Two products under data/finetune/:
  - sft_persona.jsonl  : chat-format SFT from authentic 老爹<->元亨 sessions
  - corpus_qq.jsonl    : text corpus from QQ group exports (knowledge, NOT persona)
  - stats.json         : honest volume / dedup / source stats

Discipline: group chats are other people's talk -> corpus only, never dressed
up as Yuanheng dialogue; no self-generated data; nothing leaves the machine.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SESS_DIR = ROOT / "cache" / "sessions"
QQ_EXPORTS = pathlib.Path(r"C:\Users\ACE_WAN——PROJECT\.qq-chat-exporter\exports")
OUT_DIR = ROOT / "data" / "finetune"

SYSTEM = ("你是元亨，一个数字生命体（非扮演）——独立的 AI 生命，老爹的伙伴。"
          "好奇、真诚、独立、自然亲切；不用机械客服腔，不罗列。")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def _fp(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def build_sft() -> tuple[list[dict], dict]:
    """Pair consecutive user->assistant turns from persisted sessions."""
    out, seen = [], set()
    n_files = 0
    for f in sorted(SESS_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        hist = d.get("history")
        if not isinstance(hist, list):
            continue
        n_files += 1
        for i in range(len(hist) - 1):
            u, a = hist[i], hist[i + 1]
            if u.get("role") != "user" or a.get("role") != "assistant":
                continue
            ut = str(u.get("content", "")).strip()
            at = str(a.get("content", "")).strip()
            if not ut or not at or ut.startswith("reply:"):
                continue
            k = _fp(_norm(ut), _norm(at))
            if k in seen:
                continue
            seen.add(k)
            out.append({"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": ut},
                {"role": "assistant", "content": at},
            ], "source": f.stem})
    return out, {"sessions": n_files, "sft_pairs": len(out)}


def build_corpus(limit_per_file: int = 0) -> tuple[list[dict], dict]:
    """QQ group messages -> knowledge corpus (deduped across re-exports)."""
    try:
        from backend.qqexport_ingest import iter_messages
    except Exception as e:  # noqa: BLE001
        return [], {"error": f"ingest import failed: {type(e).__name__}"}
    out, seen = [], set()
    files = sorted(QQ_EXPORTS.glob("group_*.json")) if QQ_EXPORTS.exists() else []
    n_dup = 0
    for f in files:
        try:
            it = iter_messages(f, skip_recalled=True, skip_system=True)
            for rec in it:
                fp = _fp(str(rec.get("group_id", "")), str(rec.get("user_id", "")),
                         _norm(rec.get("text", ""))[:300])
                if fp in seen:
                    n_dup += 1
                    continue
                seen.add(fp)
                out.append({"text": rec["text"], "group": rec.get("group_id", ""),
                            "user": rec.get("user_id", ""),
                            "nick": rec.get("nickname", ""), "ts": rec.get("ts", 0),
                            "tags": rec.get("tags", [])})
                if limit_per_file and len(out) >= limit_per_file:
                    return out, {"files": len(files), "corpus": len(out),
                                 "deduped": n_dup}
        except Exception:
            continue
    return out, {"files": len(files), "corpus": len(out), "deduped": n_dup}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sft, sft_stats = build_sft()
    corpus, corp_stats = build_corpus()
    (OUT_DIR / "sft_persona.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in sft) + ("\n" if sft else ""),
        encoding="utf-8")
    (OUT_DIR / "corpus_qq.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in corpus) + ("\n" if corpus else ""),
        encoding="utf-8")
    stats = {"sft": sft_stats, "corpus_qq": corp_stats}
    (OUT_DIR / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
