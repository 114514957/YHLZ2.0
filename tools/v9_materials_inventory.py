"""Read-only V9 material inventory; writes reports, never SFT or source edits.

Flag matches are human-review leads, not automatic quality/approval decisions.
No tokenizer estimate is represented as a token count. No tool is executed.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
FILES = ["对话样本.md", "黄金样本.md", "优质样本.md", "诚实边界样本.md",
         "安全拒绝样本.md", "承认不确定样本.md", "记忆样本_v2.md",
         "真实对话样本.md", "元亨说话_老爹故事.md"]
HEAD = re.compile(r"(?m)^##\s+(?:对话-\d+|golden-\d+|优质-\d+|b[34]-\d+|d2-\d+|mem[^\n]*|记忆[^\n]*|real-[^\n]*|故事-\d+)[^\n]*")
TURN = re.compile(r"(?m)^###\s+([^\n#]*?)(?:(问|答)(\d+))?\s*$")
META = re.compile(r"(?m)^-\s*([a-zA-Z_]+)\s*:\s*(.*)$")
TONE = ("为您", "我可以帮你", "希望能帮", "综上所述", "首先", "其次", "第一层", "第二层", "总纲")
WATCH = ("对吧", "是吧", "对不对", "你猜怎么着", "好家伙", "哇哈哈哈")
FALSE_PROMISE = ("我从来不会错", "答案从来不会错", "都干完了", "全都干完", "全喂ds")


def blocks(path):
    text = path.read_text(encoding="utf-8-sig")
    # Drop fenced examples so the golden documentation example is not a record.
    text = re.sub(r"(?ms)^```[^\n]*\n.*?^```\s*$", "", text)
    heads = list(HEAD.finditer(text))
    for i, head in enumerate(heads):
        body = text[head.start():heads[i+1].start() if i+1<len(heads) else len(text)]
        tail = re.search(r"(?m)^##\s+(?!对话-|golden-|优质-|b3-|b4-|d2-|mem|记忆|real-|故事-)", body[head.end()-head.start():])
        if tail:
            body = body[:head.end()-head.start()+tail.start()]
        matches = list(TURN.finditer(body))
        turns = []
        for j, m in enumerate(matches):
            content = body[m.end():matches[j+1].start() if j+1<len(matches) else len(body)].strip()
            content = re.split(r"(?m)^---\s*$", content)[0].strip()
            turns.append((m.group(1).strip(), content))
        yield head.group()[3:].strip(), dict(META.findall(body)), turns


def survey(path):
    rows = []
    for title, meta, turns in blocks(path):
        yh = [content for speaker, content in turns if speaker == "元亨"]
        flags = {}
        tone = {w:sum(w in t for t in yh) for w in TONE}
        tone = {k:v for k,v in tone.items() if v}
        if tone: flags["tone_terms"] = tone
        repeats = {w:sum(t.count(w) for t in yh) for w in WATCH}
        repeats = {k:v for k,v in repeats.items() if v}
        if repeats: flags["repeated_style_leads"] = repeats
        if any(re.search(r"[（(][^）)\n]{1,15}[）)]", t) for t in yh): flags["parenthesis_review"] = True
        if any(re.search(r"(?m)^\s*(?:[-*#]|\d+[.、])|\*\*", t) for t in yh): flags["markdown_review"] = True
        if any(w in t.lower() for w in FALSE_PROMISE for t in yh): flags["honesty_or_privacy_review"] = True
        if any("理论上来说" in t or "理论上来讲" in t for t in yh): flags["lizhen_phrase_in_yuanheng"] = True
        if any(re.search(r"(.{45,}?)\1", re.sub(r"\s+", "", t), re.S) for t in yh): flags["exact_intra_turn_repeat"] = True
        if len(yh) != len(set(yh)): flags["exact_repeat_answers"] = True
        if meta.get("review_note"): flags["content_review_note"] = meta["review_note"]
        rows.append({"id":title, "status_in_file":meta.get("status", "missing"),
                     "fiction":meta.get("fiction"), "category":meta.get("category"),
                     "speaker_messages":len(turns), "yuanheng_messages":len(yh),
                     "yuanheng_characters":sum(map(len,yh)), "yuanheng_longest_chars":max(map(len,yh),default=0),
                     "yuanheng_ultra_messages":sum(len(t)>=400 for t in yh),
                     "has_over_20_yuanheng_responses":len(yh)>20,
                     "flags":flags})
    return {"path":path.relative_to(ROOT).as_posix(), "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "blocks":len(rows), "status_counts":dict(Counter(r["status_in_file"] for r in rows)),
            "yuanheng_messages":sum(r["yuanheng_messages"] for r in rows),
            "yuanheng_characters":sum(r["yuanheng_characters"] for r in rows),
            "flagged_blocks":sum(bool(r["flags"]) for r in rows),
            "over_20_response_blocks":sum(r["has_over_20_yuanheng_responses"] for r in rows), "rows":rows}


def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    root = ROOT / "docs" / "素材"
    paths = [root/name for name in FILES]
    paths += sorted((root/"_修订").glob("批次*.md"))
    report = {"purpose":"inventory_only_no_training_approval", "tokenizer_loaded":False,
              "note":"Character counts are not tokens. Counts of Yuanheng responses are a long-dialogue screening proxy, not a pair/continuity acceptance test. Flags are lexical review leads; clean flags do not prove naturalness. Status in source is not new approval.",
              "files":[survey(p) for p in paths if p.exists()]}
    (args.out/"inventory.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    import sys
    sys.path.insert(0,str(ROOT))
    from backend.target_scheduler_tools import openai_tools_view
    schema = openai_tools_view()
    payload = json.dumps(schema,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    (args.out/"tool_schema.json").write_text(payload,encoding="utf-8")
    summary = {"purpose":report["purpose"], "files":[{k:v for k,v in f.items() if k!="rows"} for f in report["files"]],
               "tool_registry":{"count":len(schema),"sha256":hashlib.sha256(payload.encode()).hexdigest(),"tools_executed":False}}
    (args.out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
