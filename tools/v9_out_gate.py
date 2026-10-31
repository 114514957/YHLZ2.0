"""④ 出集门：pending / 双签 / 候选稿 / 利贞分池（ledger 0839）。

2026-10-18 老爹裁定：QQ 同意路径通过（D-1 关闭）；**利贞先不管、只做元亨**；
「pending / 双签 / 候选稿出集」三道硬门由 agent 落地。

四道判据（任一不过 → 进隔离池，**不进正式训练集**）：
  G1 利贞分池：source 以 lizhen 开头 → lizhen_pool（元亨集不含）
  G2 同意状态：consent_status == pending → 隔离（个人信息同意未定）
  G3 双签：annotator_review 为空 → 隔离；若 content_hash / 块 ID 在已签批次里则盖章
  G4 候选稿：素材块 status != keep（含查不到）→ 隔离

用法：
    python tools/v9_out_gate.py --scan-status
    python tools/v9_out_gate.py --in data/finetune/sft_persona_v8r4t_train.jsonl \\
        --in data/finetune/sft_persona_v8r4t_val.jsonl --out-prefix data/finetune/sft_persona_v9
    python tools/v9_out_gate.py --in ... --sign-file cache/v9_materials_preparation/sign_batches.json
    python tools/v9_out_gate.py --make-batch-manifest --out cache/.../sign_batches.json

原则：**门不过就出空集也不放行**；报告写清每条规则卡了多少、卡在哪个来源。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
MATERIALS_DIR = ROOT / "docs" / "素材"
CACHE_DIR = ROOT / "cache" / "v9_materials_preparation"

BLOCK_RE = re.compile(r"^##\s+(?P<id>[^｜|]+?)\s*[｜|]\s*(?P<label>.+)$")
FIELD_RE = re.compile(r"^-\s*(?P<k>[a-z_]+)\s*:\s*(?P<v>.+?)\s*$")
SPLIT_RE = re.compile(r"_(train|val|test)\.jsonl$")

STATUS_OK = {"keep"}


def scan_materials(root: pathlib.Path = MATERIALS_DIR) -> dict[str, dict]:
    """块 ID → {status, file, label}。只读，不改素材；跳过 _草稿/_修订/_归档。"""
    out: dict[str, dict] = {}
    for p in root.rglob("*.md"):
        parts = p.relative_to(root).parts[:-1]
        if any(x.startswith("_") for x in parts):
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        cur = None
        for line in lines:
            m = BLOCK_RE.match(line)
            if m:
                bid = m.group("id").strip()
                cur = {"status": None, "file": str(p.relative_to(ROOT)),
                       "label": m.group("label").strip()[:40]}
                out[bid] = cur
                continue
            if cur is None:
                continue
            f = FIELD_RE.match(line)
            if f and f.group("k") == "status":
                cur["status"] = f.group("v").strip().lower()
    return out


def block_id_of(rec: dict) -> str:
    raw = str(rec.get("source_id") or rec.get("source") or "")
    if "#" in raw:
        raw = raw.split("#", 1)[1]
    return raw.split("｜")[0].split("|")[0].strip()


def load_signatures(path: pathlib.Path | None) -> dict:
    if not path or not path.exists():
        return {"hashes": {}, "blocks": {}, "batches": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    hashes: dict[str, str] = {}
    blocks: dict[str, str] = {}
    batches = data.get("batches") or []
    for b in batches:
        bid = str(b.get("batch_id") or "")
        stamp = f"dad:{bid}@{str(b.get('signed_at') or '')[:10]}"
        for h in b.get("content_hashes") or []:
            hashes[str(h)] = stamp
        for x in b.get("block_ids") or []:
            blocks[str(x)] = stamp
    return {"hashes": hashes, "blocks": blocks, "batches": batches}


def judge(rec: dict, status_map: dict, sig: dict, *,
          allowed_tools: set[str] | None = None,
          allow_generated_tools: bool = False) -> tuple[str, str]:
    """返回 (去向, 理由)。去向 ∈ pass / lizhen_pool / quarantine。"""
    src = str(rec.get("source") or "")
    if src.split(":", 1)[0].lower() == "lizhen":
        return "lizhen_pool", "lizhen-pool"
    # 工具必须真实（ledger 0886）：假工具名 / 生成轨迹 不进正式集
    names = []
    for m in rec.get("messages") or []:
        for c in (m.get("tool_calls") or []):
            fn = (c.get("function") or {}).get("name")
            if fn:
                names.append(str(fn))
        if m.get("role") == "tool" and m.get("name"):
            names.append(str(m["name"]))
    if allowed_tools is not None:
        fake = [n for n in names if n not in allowed_tools]
        if fake:
            return "quarantine", "fake-tool:" + ",".join(sorted(set(fake))[:3])
    is_sim = bool(rec.get("simulation"))
    if not is_sim and src.split(":", 1)[0].lower() == "tooluse" and not allow_generated_tools:
        return "quarantine", "generated-tool-trace"
    if str(rec.get("consent_status") or "").lower() == "pending":
        return "quarantine", "consent-pending"
    bid = block_id_of(rec)
    signed = False
    if not str(rec.get("annotator_review") or "").strip():
        stamp = sig["hashes"].get(str(rec.get("content_hash") or "")) or \
            sig["blocks"].get(bid)
        if not stamp:
            return "quarantine", "no-double-sign"
        rec["annotator_review"] = stamp
        signed = True
    else:
        signed = True
    st = (status_map.get(bid) or {}).get("status")
    if st not in STATUS_OK:
        # 已签名的行：块 ID 对不上素材 md（导出用 b<hash>、素材用 mem-1）时以签字为准；
        # 明确 drop 的仍然拦；未签名的一律拦（候选稿不出集）。
        if st == "drop":
            return "quarantine", "material-status=drop"
        if signed and st is None:
            return "pass", "ok-signed-unknown-block"
        return "quarantine", f"material-status={st or 'unknown'}"
    return "pass", "ok"


def make_manifest(inputs: list[pathlib.Path], status_map: dict,
                  out: pathlib.Path) -> int:
    """生成一份"可签批次"清单：块 ID + 内容指纹（老爹签完即可放行）。"""
    by_block: dict[str, dict] = {}
    for p in inputs:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if str(rec.get("source") or "").startswith("lizhen"):
                continue
            if str(rec.get("consent_status") or "") == "pending":
                continue
            bid = block_id_of(rec)
            entry = by_block.setdefault(bid, {"block_id": bid,
                                              "status": (status_map.get(bid) or {}).get("status"),
                                              "hashes": [], "rows": 0})
            entry["hashes"].append(rec.get("content_hash"))
            entry["rows"] += 1
    data = {"generated_at": datetime.now().isoformat(timespec="seconds"),
            "note": "老爹签一批：填 reviewer/signed_at 后作为 --sign-file 传入",
            "batches": [{"batch_id": "B01-core", "reviewer": "",
                         "signed_at": "", "rows": sum(e["rows"] for e in by_block.values()),
                         "block_ids": sorted(by_block),
                         "content_hashes": sorted({h for e in by_block.values() for h in e["hashes"] if h})}]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[manifest] {out} · 块 {len(by_block)} · 行 {data['batches'][0]['rows']}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="④ 出集门：pending/双签/候选稿/利贞分池")
    ap.add_argument("--in", dest="inputs", action="append", default=[])
    ap.add_argument("--out-prefix")
    ap.add_argument("--sign-file")
    ap.add_argument("--scan-status", action="store_true")
    ap.add_argument("--make-batch-manifest")
    ap.add_argument("--materials-dir", default=str(MATERIALS_DIR))
    ap.add_argument("--tool-snapshot", default="data/tool_registry/snapshot_latest.json",
                    help="真实工具白名单快照（默认取最新）")
    ap.add_argument("--allow-generated-tools", action="store_true",
                    help="允许生成轨迹进正式集（默认不许：工具必须真实）")
    args = ap.parse_args()

    status_map = scan_materials(pathlib.Path(args.materials_dir))
    dist = Counter((v.get("status") or "unknown") for v in status_map.values())
    if args.scan_status or not args.inputs:
        print(f"[status] 主素材块 {len(status_map)} 个，status 分布：{dict(dist)}")
        return 0

    paths = []
    for s in args.inputs:
        p = pathlib.Path(s)
        paths.append(p if p.is_absolute() else ROOT / p)

    if args.make_batch_manifest:
        out = pathlib.Path(args.make_batch_manifest)
        return make_manifest(paths, status_map,
                             out if out.is_absolute() else ROOT / out)

    if not args.out_prefix:
        print("需要 --out-prefix", file=sys.stderr)
        return 2
    allowed_tools = None
    snap_path = pathlib.Path(args.tool_snapshot)
    if not snap_path.is_absolute():
        snap_path = ROOT / snap_path
    harness_path = ROOT / "data" / "tool_registry" / "harness_tools_latest.json"
    if snap_path.exists():
        try:
            snap = json.loads(snap_path.read_text(encoding="utf-8"))
            allowed_tools = {t["name"] for t in snap.get("tools") or []}
            for extra in ("harness_tools_latest.json", "dsh_tools_latest.json"):
                ep = ROOT / "data" / "tool_registry" / extra
                if ep.exists():
                    try:
                        es = json.loads(ep.read_text(encoding="utf-8"))
                        allowed_tools |= {t["name"] for t in es.get("tools") or []}
                    except Exception:
                        pass
            print(f"[tools] 白名单 {len(allowed_tools)} 项 "
                  f"(元亨+harness, sha16={snap.get('sha16')})")
        except Exception:
            allowed_tools = None
    sig = load_signatures(pathlib.Path(args.sign_file) if args.sign_file else None)
    print(f"[sign] 已签批次 {len(sig['batches'])} 个 · 覆盖 hash {len(sig['hashes'])}"
          f" / 块 {len(sig['blocks'])}")

    prefix = pathlib.Path(args.out_prefix)
    if not prefix.is_absolute():
        prefix = ROOT / prefix

    by_split: dict[str, list] = {"train": [], "val": [], "test": []}
    lizhen: list = []
    quarantine: list = []
    per_file: dict[str, dict] = {}
    totals = Counter()

    for p in paths:
        m = SPLIT_RE.search(p.name)
        split = m.group(1) if m else "train"
        rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
                if l.strip()]
        cnt = Counter()
        for rec in rows:
            dest, reason = judge(rec, status_map, sig,
                                 allowed_tools=allowed_tools,
                                 allow_generated_tools=args.allow_generated_tools)
            cnt[reason] += 1
            totals[reason] += 1
            rec["gate_reason"] = reason
            if dest == "pass":
                by_split[split].append(rec)
            elif dest == "lizhen_pool":
                lizhen.append(rec)
            else:
                quarantine.append(rec)
        per_file[p.name] = {"split": split, "in": len(rows), "reasons": dict(cnt)}

    written: dict[str, dict] = {}
    for split, recs in by_split.items():
        if not recs:
            continue
        path = prefix.with_name(f"{prefix.name}_{split}.jsonl")
        with path.open("w", encoding="utf-8") as fh:
            for rec in recs:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        written[split] = {"path": str(path.relative_to(ROOT)) if path.is_absolute()
                          else str(path), "rows": len(recs)}
    for name, recs in (("lizhen_pool", lizhen), ("quarantine", quarantine)):
        if not recs:
            continue
        path = prefix.with_name(f"{prefix.name}_{name}.jsonl")
        with path.open("w", encoding="utf-8") as fh:
            for rec in recs:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        written[name] = {"path": str(path.relative_to(ROOT)) if path.is_absolute()
                         else str(path), "rows": len(recs)}

    report = {"generated_at": datetime.now().isoformat(timespec="seconds"),
              "inputs": per_file, "totals": dict(totals),
              "material_status_dist": dict(dist),
              "signed_batches": len(sig["batches"]),
              "written": written,
              "ready_to_train": bool(by_split["train"] or by_split["val"]),
              "verdict": _verdict(totals, by_split)}
    rep_path = prefix.with_name(f"{prefix.name}_gate_report.json")
    rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(json.dumps({"totals": report["totals"], "written": written,
                      "ready_to_train": report["ready_to_train"],
                      "verdict": report["verdict"]}, ensure_ascii=False, indent=1))
    print(f"[report] {rep_path.relative_to(ROOT) if rep_path.is_absolute() else rep_path}")
    return 0


def _verdict(totals: Counter, by_split: dict) -> str:
    passed = sum(len(v) for v in by_split.values())
    if passed == 0:
        if totals.get("no-double-sign", 0) and not totals.get("material-status=keep", 0):
            return "BLOCKED: 全部待双签且素材块未 keep——需老爹签批次 + 批 keep"
        return "BLOCKED: 无任何记录通过四道门"
    if totals.get("no-double-sign"):
        return f"PARTIAL: 过 {passed} 条；{totals['no-double-sign']} 条待双签被隔离"
    return f"PASS: 过 {passed} 条"


if __name__ == "__main__":
    raise SystemExit(main())
