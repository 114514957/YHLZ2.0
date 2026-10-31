#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从完整 S2 数据集切一个子集，用于 LoRA 冒烟验证。

用法:
  python tools/gsv5_make_subset.py --src GPT-SoVITS/logs/yuanheng_C \
      --dst GPT-SoVITS/logs/yuanheng_C_smoke --n 200
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--config", default=str(ROOT / "GPT-SoVITS" / "GPT_SoVITS" / "configs" / "tmp_s2_v5dev_lora.json"))
    ap.add_argument("--out-config", default=str(ROOT / "GPT-SoVITS" / "GPT_SoVITS" / "configs" / "tmp_s2_v5dev_lora_smoke.json"))
    ap.add_argument("--batch", type=int, default=2)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    src, dst = Path(a.src).resolve(), Path(a.dst).resolve()
    dst.mkdir(parents=True, exist_ok=True)

    rows = []
    for line in (src / "2-name2text.txt").read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(line)
    rows = rows[: a.n]
    names = [r.split("\t", 1)[0] for r in rows]
    (dst / "2-name2text.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")

    sem = (src / "6-name2semantic.tsv").read_text(encoding="utf-8").splitlines()
    keep = {n for n in names}
    sem_out = [sem[0]] + [l for l in sem[1:] if l.split("\t", 1)[0] in keep]
    (dst / "6-name2semantic.tsv").write_text("\n".join(sem_out) + "\n", encoding="utf-8")

    for sub, ext in (("4-cnhubert", ".pt"), ("5-wav32k", ".wav")):
        (dst / sub).mkdir(exist_ok=True)
        for n in names:
            # 4-cnhubert 是 <name>.pt（00001.wav.pt），5-wav32k 是 <name>.wav
            fname = (n + ".pt") if sub == "4-cnhubert" else n
            s = src / sub / fname
            if s.is_file():
                shutil.copy2(s, dst / sub / fname)

    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    cfg["data"]["exp_dir"] = str(dst)
    cfg["s2_ckpt_dir"] = str(dst)
    cfg["train"]["batch_size"] = a.batch
    cfg["train"]["grad_ckpt"] = True
    cfg["train"]["epochs"] = 1
    cfg["name"] = dst.name
    Path(a.out_config).write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    print(json.dumps({"dst": str(dst), "n": len(names),
                      "batch": a.batch, "config": a.out_config},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
