"""Deterministic style sampling. Stores references and measurements, not approval."""
from __future__ import annotations
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from tools.v9_materials_inventory import blocks
SEED=20261011


def choose(label,pool,n=3):
    seed=int.from_bytes(hashlib.sha256(f"{SEED}:{label}".encode()).digest()[:8],"big")
    return random.Random(seed).sample(pool,min(n,len(pool)))


def read_remote(url):
    with urlopen(Request(url,headers={"User-Agent":"YHLZ-style-comparison/1.0"}),timeout=25) as r:
        raw=r.read(5_000_001)
    if len(raw)>5_000_000:raise ValueError("bounded source limit exceeded")
    return raw


def snapshot_rows(filename):
    path=ROOT/"cache/v9_materials_review/20261008"/filename
    ev=json.loads(path.read_text(encoding="utf-8"))
    rows={}
    for preview in [ev.get("preview",{})]+ev.get("additional_previews",[]):
        for r in preview.get("data",{}).get("rows",[]):rows[r["row_idx"]]=r["row"]
    return ev,rows,path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--out",required=True,type=Path)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    manifest={"purpose":"style_comparison_only","seed":SEED,"seed_rule":"sha256(seed:group) first 8 bytes to Random.sample","sample_size_per_pool":3,"training_approved":False,"groups":[],"limitations":["Small subjective comparison, not an overall dataset ranking.","Sources have different genres and sampling frames.","Pairs use identical original block IDs; no style-based resampling.","External quote displays may be short excerpts; full records are read for assessment."]}
    def emit(label,frame,records,source):
        entries=[]
        print("\nGROUP",label,"FRAME",frame)
        for ref,turns in records:
            chars=[len(t) for _,t in turns]
            entries.append({"ref":ref,"speaker_messages":len(turns),"max_message_characters":max(chars,default=0),"characters_total":sum(chars)})
            print("REF",ref)
            for role,text in turns:print(role+": "+text)
        manifest["groups"].append({"name":label,"sampling_frame":frame,"source":source,"samples":entries})
    material=ROOT/"docs/素材/对话样本.md"
    original={title.split("｜")[0]:(title,meta,turns) for title,meta,turns in blocks(material)}
    reviewed=ROOT/"docs/素材/_修订/批次02_v3_开源对白学习后重写_20261011.md"
    revisions={title.split("｜")[0]:(title,meta,turns) for title,meta,turns in blocks(reviewed)}
    selected=choose("paired_self",sorted(set(original)&set(revisions)))
    for label,pool,path in [("本库_配对原稿",original,material),("本库_配对v3",revisions,reviewed)]:
        emit(label,f"same 3 blocks from {len(revisions)} revised block IDs",[(k,pool[k][2]) for k in selected],{"path":path.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    selected_all=choose("self_all",list(original))
    emit("本库_主对话随机",f"all {len(original)} current blocks",[(k,original[k][2]) for k in selected_all],{"path":material.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(material.read_bytes()).hexdigest()})
    gold=ROOT/"docs/素材/黄金样本.md"
    goldpool=[x for x in blocks(gold) if x[1].get("status") in {"keep","fixed"}]
    selected_gold=choose("golden",goldpool)
    emit("本库_黄金随机",f"{len(goldpool)} old keep/fixed blocks, not newly approved",[(t,tr) for t,meta,tr in selected_gold],{"path":gold.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(gold.read_bytes()).hexdigest()})
    e=json.loads((ROOT/"cache/v9_materials_review/20261008/Moemu__Muice-Dataset.json").read_text(encoding="utf-8"))
    rev=e["revision"];url=f"https://huggingface.co/datasets/Moemu/Muice-Dataset/resolve/{rev}/train.jsonl"
    raw=read_remote(url);rows=[json.loads(x) for x in raw.decode("utf-8").splitlines() if x.strip()]
    selected=choose("Muice",list(enumerate(rows,1)))
    rec=[]
    for index,row in selected:
        turns=[]
        for pair in row["conversation"]:turns.extend([("用户",pair["human"]),("沐雪",pair["assistant"])])
        rec.append((f"train.jsonl:{index}",turns))
    emit("Muice",f"all {len(rows)} main train.jsonl records; excludes Customized",rec,{"repo":"Moemu/Muice-Dataset","revision":rev,"file":"train.jsonl","sha256":hashlib.sha256(raw).hexdigest()})
    e=json.loads((ROOT/"cache/v9_materials_review/20261008/MemorialSummer__chinese-adorable-high-emotional-intelligence-chat.json").read_text(encoding="utf-8"))
    repo=e['repo'];rev=e['revision'];filename='chinese-adorable-high-emotional-intelligence-chat.json'
    raw=read_remote(f"https://huggingface.co/datasets/{repo}/resolve/{rev}/{filename}");rows=json.loads(raw)
    if not isinstance(rows,list):raise ValueError("unexpected Memorial format")
    rec=[(f"array_index:{i}",[("用户",row['user']),("角色",row['girl'])]) for i,row in choose("Memorial",list(enumerate(rows)))]
    emit("MemorialSummer",f"all {len(rows)} JSON records",rec,{"repo":repo,"revision":rev,"file":filename,"sha256":hashlib.sha256(raw).hexdigest()})
    for label,filename in [("zhcompanion","zhcompanion__companion-roleplay-sft.json"),("LCCC","silver__lccc.json")]:
        e,rows,p=snapshot_rows(filename);sel=choose(label,list(rows))
        rec=[]
        for i in sel:
            row=rows[i]
            if label=="zhcompanion":turns=[(m['role'],m['content']) for m in row['messages'] if m['role']!='system']
            else:turns=[(f"发言{j+1}",t) for j,t in enumerate(row['dialog'])]
            rec.append((f"cached_viewer_row:{i}",turns))
        emit(label,f"{len(rows)} cached viewer rows; {'all 6 demos' if label=='zhcompanion' else 'first/middle/last preselected slices, NOT whole-corpus random'}",rec,{"repo":e['repo'],"metadata_revision":e['revision'],"path":p.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"viewer_revision_is_not_assumed_pinned":True})
    (args.out/"sampling_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("\nSAMPLES",sum(len(g['samples']) for g in manifest['groups']),"NO_STYLE_ACCEPTANCE")


if __name__=="__main__":main()
