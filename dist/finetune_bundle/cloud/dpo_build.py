"""Build DPO preference pairs: chosen = dataset answer, rejected = base-model reply.

For each SFT sample (up to --n), generate a reply with the *base* model (pre-SFT)
as the rejected one; the dataset assistant answer is the chosen one. Output:
{"prompt": [messages up to last assistant], "chosen": "...", "rejected": "..."}

Usage:
    python dpo_build.py --base models/gemma4-hf/gemma-4-e4b-it \
        --data sft_persona_v3_train.jsonl --n 400 --out dpo_pairs.jsonl
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path


def read_jsonl(p):
    out = []
    for line in Path(p).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try: out.append(json.loads(line))
            except Exception: pass
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--max-new", type=int, default=160)
    ap.add_argument("--out", default="dpo_pairs.jsonl")
    args = ap.parse_args()

    import torch
    from transformers import AutoTokenizer
    try:
        from transformers import Gemma4ForConditionalGeneration as LM
    except Exception:
        from transformers import Gemma4ForCausalLM as LM

    tok = AutoTokenizer.from_pretrained(args.base, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    # bf16 (no bitsandbytes: incompatible with Gemma4).
    model = LM.from_pretrained(args.base, dtype=torch.bfloat16, device_map={"": 0},
                               low_cpu_mem_usage=True, trust_remote_code=True)
    model.eval()

    rows = read_jsonl(args.data)[: args.n]
    written = 0
    with Path(args.out).open("w", encoding="utf-8") as f:
        for i, r in enumerate(rows, 1):
            msgs = r["messages"]
            # v6: 跳过工具轨迹（含 tools 或 tool_calls/role=tool），
            # 只在纯 chat 上做风格 DPO，避免伤到工具能力。
            if r.get("tools") or any(
                    (m.get("tool_calls") or m.get("role") == "tool") for m in msgs):
                continue
            chosen = next((m["content"] for m in msgs if m["role"] == "assistant"), "")
            prompt = msgs[:-1]
            if not chosen or not prompt:
                continue
            text = tok.apply_chat_template(prompt, tokenize=False, add_generation_prompt=True)
            ids = tok(text, return_tensors="pt").to(model.device)
            with torch.no_grad():
                out = model.generate(**ids, max_new_tokens=args.max_new, do_sample=True,
                                     temperature=0.9, top_p=0.9, pad_token_id=tok.pad_token_id)
            rejected = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
            if not rejected or rejected == chosen:
                continue
            f.write(json.dumps({"prompt": prompt, "chosen": chosen, "rejected": rejected},
                               ensure_ascii=False) + "\n")
            written += 1
            print(f"[{i}/{len(rows)}] pair ok")
    print(json.dumps({"pairs": written, "out": args.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
