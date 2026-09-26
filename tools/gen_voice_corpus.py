"""Build a 2h clean "Yuanheng voice" speech corpus (Edge zh-CN-XiaoyiNeural).

Sources (her own words first, then natural QQ sentences):
  docs/素材/对话样本.md (元亨 answers), 记忆样本_v2.md, 黄金样本.md,
  data/finetune/corpus_qq_raw.jsonl
Cleaning: split long lines at punctuation into 8-45 char chunks; drop non-Chinese,
URLs, brackets; dedupe.
Output: models/tts/voice_train/yuanheng_2h/
  wavs/00001.wav ... (44100 Hz mono, loudnorm -16 LUFS)
  metadata.jsonl  {id, wav, text, chars, dur}
  data.list       SoVITS format: wav|speaker|zh|text
  说明.txt
Usage: python tools/gen_voice_corpus.py --hours 2.0 [--concurrency 6]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import random
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
D = ROOT / "docs" / "素材"
OUT = ROOT / "models" / "tts" / "voice_train" / "yuanheng_2h"
CJK = re.compile(r"[\u4e00-\u9fff]")
BAD = re.compile(r"https?://|\.com|\.cn|@|\[|\]|<|>|\{|\}|（|）|\(|\)|\*|#|`")


def split_chunks(text: str) -> list[str]:
    text = re.sub(r"\s+", "", text)
    parts = re.split(r"[，。！？；、,.!?;]", text)
    out, buf = [], ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) <= 38:
            buf += p
        else:
            if len(buf) >= 8:
                out.append(buf)
            buf = p
        if len(buf) >= 38:
            out.append(buf)
            buf = ""
    if len(buf) >= 8:
        out.append(buf)
    return out


def harvest() -> list[str]:
    lines: list[str] = []

    def from_doc(path: pathlib.Path, answers_only: bool = True):
        if not path.exists():
            return
        txt = path.read_text(encoding="utf-8")
        for chunk in re.split(r"(?m)(?=^## )", txt):
            if not chunk.startswith("## "):
                continue
            for m in re.finditer(r"^###\s*([^\n#]*?)(问|答)\s*(\d+)\s*$", chunk, re.MULTILINE):
                end = chunk.find("\n### ", m.end())
                body = chunk[m.end():end if end > 0 else len(chunk)].strip()
                if answers_only and (m.group(2) != "答" or m.group(1).strip() != "元亨"):
                    continue
                if body:
                    lines.append(body)

    from_doc(D / "对话样本.md")
    from_doc(D / "记忆样本_v2.md")
    from_doc(D / "黄金样本.md")
    from_doc(D / "真实对话样本.md")

    qq = ROOT / "data" / "finetune" / "corpus_qq_raw.jsonl"
    if qq.exists():
        for raw in qq.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                t = str(json.loads(raw).get("text") or "").strip()
            except Exception:  # noqa: BLE001
                continue
            if 10 <= len(t) <= 45:
                lines.append(t)

    chunks: list[str] = []
    for ln in lines:
        if len(CJK.findall(ln)) < 6:
            continue
        chunks.extend(split_chunks(ln))
    seen = set()
    uniq = []
    for c in chunks:
        if len(c) < 8 or BAD.search(c) or len(CJK.findall(c)) < 5:
            continue
        if c in seen:
            continue
        seen.add(c)
        uniq.append(c)
    random.Random(20260927).shuffle(uniq)
    return uniq


async def synth(texts: list[str], concurrency: int, hours: float) -> None:
    import edge_tts
    import imageio_ffmpeg
    import soundfile as sf

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    (OUT / "wavs").mkdir(parents=True, exist_ok=True)
    meta_path = OUT / "metadata.jsonl"
    have = set()
    total = 0.0
    if meta_path.exists():
        for line in meta_path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                have.add(int(r["id"]))
                total += float(r.get("dur") or 0)
            except Exception:  # noqa: BLE001
                pass
    target = hours * 3600.0
    print(f"target {target/60:.0f} min, have {total/60:.1f} min, texts {len(texts)}", flush=True)

    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    state = {"total": total, "n": 0}

    async def one(i: int, text: str) -> None:
        wav = OUT / "wavs" / f"{i:05d}.wav"
        if i in have or state["total"] >= target:
            return
        mp3 = wav.with_suffix(".mp3")
        async with sem:
            if state["total"] >= target:
                return
            try:
                await edge_tts.Communicate(text, "zh-CN-XiaoyiNeural").save(str(mp3))
                await asyncio.to_thread(subprocess.run, [
                    ffmpeg, "-y", "-i", str(mp3), "-af",
                    "loudnorm=I=-16:TP=-1.5:LRA=11", "-ac", "1", "-ar", "44100",
                    str(wav)], capture_output=True)
                mp3.unlink(missing_ok=True)
                dur = float(sf.info(str(wav)).duration)
            except Exception:  # noqa: BLE001
                mp3.unlink(missing_ok=True)
                return
            async with lock:
                if state["total"] >= target:
                    wav.unlink(missing_ok=True)
                    return
                state["total"] += dur
                state["n"] += 1
                with meta_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"id": i, "wav": f"wavs/{i:05d}.wav",
                                        "text": text, "chars": len(text),
                                        "dur": round(dur, 3)}, ensure_ascii=False) + "\n")
                if state["n"] % 100 == 0:
                    print(f"  +{state['n']} clips, {state['total']/60:.1f} min", flush=True)

    await asyncio.gather(*(one(i, t) for i, t in enumerate(texts, 1)))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--concurrency", type=int, default=6)
    a = ap.parse_args()
    texts = harvest()
    print(f"unique chunks: {len(texts)} (~{sum(len(t) for t in texts)} chars)")
    asyncio.run(synth(texts, a.concurrency, a.hours))

    # write data.list + 说明
    rows = []
    if (OUT / "metadata.jsonl").exists():
        for line in (OUT / "metadata.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:  # noqa: BLE001
                pass
    rows.sort(key=lambda r: r["id"])
    with (OUT / "data.list").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"{r['wav']}|xiaoyi|zh|{r['text']}\n")
    total = sum(r["dur"] for r in rows)
    (OUT / "说明.txt").write_text(
        "元亨干音语料（Edge zh-CN-XiaoyiNeural 合成，干净干声）\n"
        f"片段数：{len(rows)}｜总时长：{total/60:.1f} 分钟（目标 120 分钟）\n"
        "格式：wav 44.1kHz 单声道，loudnorm -16 LUFS；附 metadata.jsonl 与 data.list（SoVITS 格式）\n"
        "用途：Qwen3-TTS / GPT-SoVITS / DDSP-SVC 等声线训练或参考。\n",
        encoding="utf-8")
    print(json.dumps({"clips": len(rows), "minutes": round(total / 60, 1),
                      "out": str(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
