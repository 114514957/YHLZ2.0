"""Download google/gemma-4-E4B-it (safetensors) via HF hub, resumable."""
import os
import sys
import time

os.environ.setdefault("HF_HOME", r"C:\Users\ACE_WAN——PROJECT\.cache\huggingface")
# HF_TOKEN: leave unset in file — huggingface_hub auto-reads
# ~/.cache/huggingface/token (already saved there). Never commit secrets.
os.environ["HF_HUB_ENABLE_XET"] = "0"   # xet CDN unstable here; plain https
os.environ["HF_HUB_DISABLE_XET"] = "1"
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ")
sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

from huggingface_hub import snapshot_download  # noqa: E402

t0 = time.time()
last = None
for attempt in range(1, 6):  # retry up to 5x (network flakes)
    try:
        p = snapshot_download(
            repo_id="google/gemma-4-E4B-it",
            allow_patterns=["*.safetensors", "*.json", "*.model", "tokenizer*", "*.txt"],
            local_dir=None,  # goes to HF cache
        )
        print("downloaded to:", p, "in", round((time.time() - t0) / 60, 1), "min")
        break
    except Exception as e:
        last = e
        print(f"attempt {attempt} failed: {type(e).__name__}; retrying...", flush=True)
        time.sleep(5)
else:
    raise SystemExit(f"download failed after retries: {last}")
