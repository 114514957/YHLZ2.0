"""Fetch the (gated) Gemma base weights for QLoRA fine-tuning (ledger 0339).

Downloads `google/gemma-4-E4B-it` safetensors into the local path the training
scaffold expects (`config/finetune.json` -> `base_model`). The token is never
written to the repo: pass `--token`, set HF_TOKEN/HUGGING_FACE_HUB_TOKEN, or put
`HF_TOKEN=hf_...` in the gitignored `.env`.

Prereqs (one-time, done in the browser):
  1. huggingface.co/settings/tokens  -> create a read token
  2. huggingface.co/google/gemma-4-E4B-it -> accept the Gemma license (gated)

Usage:
    python tools/finetune_fetch_base.py --dry-run   # 只验 token/权限，不下载
    python tools/finetune_fetch_base.py             # 下载到 config 的 base_model 目录
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_REPO = "google/gemma-4-E4B-it"


def _env_token() -> str | None:
    for k in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        v = os.environ.get(k)
        if v:
            return v.strip()
    envp = ROOT / ".env"
    if envp.exists():
        for line in envp.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("HF_TOKEN") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg_path = ROOT / "config" / "finetune.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}

    ap = argparse.ArgumentParser(description="下载 Gemma 基座权重（gated）")
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--dest", default=cfg.get("base_model", "models/gemma4-hf/gemma-4-E4B-it"))
    ap.add_argument("--token", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = args.token or _env_token()
    if not token:
        print("[error] 未找到 HF token。请：\n"
              "  1) huggingface.co/settings/tokens 建一个 read token；\n"
              "  2) 在 huggingface.co/google/gemma-4-E4B-it 接受 Gemma 许可（gated）；\n"
              "  3) 把 `HF_TOKEN=hf_xxx` 写进本项目 .env（已 gitignore），"
              "或设置环境变量 HF_TOKEN。\n"
              "然后重跑本脚本。", file=sys.stderr)
        return 2

    from huggingface_hub import HfApi, snapshot_download
    from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError

    api = HfApi()
    try:
        who = api.whoami(token=token)
        print(f"[auth] OK  用户={who.get('name', '?')}")
    except Exception as e:  # noqa: BLE001
        print(f"[error] token 无效或网络不通：{type(e).__name__}", file=sys.stderr)
        return 2

    try:
        info = api.model_info(args.repo, token=token)
        print(f"[repo] {args.repo}  gated={getattr(info, 'gated', None)}  "
              f"files={len(getattr(info, 'siblings', []) or [])}")
    except GatedRepoError:
        print(f"[error] {args.repo} 是 gated：请先在网页接受 Gemma 许可（用同一账号）。",
              file=sys.stderr)
        return 3
    except RepositoryNotFoundError:
        print(f"[error] 仓库不存在或无权访问：{args.repo}", file=sys.stderr)
        return 3

    dest = ROOT / args.dest
    if args.dry_run:
        print(f"[dry-run] 权限校验通过；将下载到 {dest}（约 8GB bf16）。未下载。")
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    print(f"[download] -> {dest}（约 8GB，请耐心）")
    try:
        path = snapshot_download(repo_id=args.repo, local_dir=str(dest), token=token,
                                 ignore_patterns=["*.gguf", "*.pth", "*.msgpack"])
    except GatedRepoError:
        print("[error] gated 拒绝：确认许可已在同一账号下接受。", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001
        print(f"[error] 下载失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"[done] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
