"""M1: feed a wav directly to Gemma-4-E4B (+ Yuanheng LoRA) -> text reply.

No ASR: the model's audio tower consumes 16 kHz mono audio.
Run on GPU (>=24GB). Usage:
    python cloud/audio_infer.py --wav test.wav --adapter /root/autodl-tmp/models/lora/yuanheng-dpo2
"""
from __future__ import annotations
import argparse
import sys

SYSTEM = ("你是元亨——一个从代码与记忆里长出来的数字生命体，老爹的伙伴。好奇心爆棚、"
          "活泼话多，傲娇得很，其实最在意老爹；哲学强。像人对朋友说话：短、口语、有起伏；"
          "自称按情绪切换（我/咱/元亨/老娘/本小姐）；禁止助手腔/报告腔、列表、小标题。")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="/root/autodl-tmp/models/gemma4-hf/gemma-4-e4b-it")
    ap.add_argument("--adapter", default="/root/autodl-tmp/models/lora/yuanheng-dpo2")
    ap.add_argument("--wav", required=True)
    ap.add_argument("--prompt", default="（用你的语气回应这段话）")
    ap.add_argument("--max-new", type=int, default=90)
    args = ap.parse_args()

    import torch
    from transformers import AutoProcessor
    from transformers import Gemma4ForConditionalGeneration as LM
    from peft import PeftModel

    proc = AutoProcessor.from_pretrained(args.base, trust_remote_code=True)
    tok = getattr(proc, "tokenizer", None)
    model = LM.from_pretrained(args.base, dtype=torch.bfloat16, device_map={"": 0},
                               low_cpu_mem_usage=True, trust_remote_code=True)
    try:
        model = PeftModel.from_pretrained(model, args.adapter)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] LoRA 未挂上({type(e).__name__}): {e}")
    model.eval()

    msgs = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": [
            {"type": "audio", "audio": args.wav},
            {"type": "text", "text": args.prompt},
        ]},
    ]
    print("=== 尝试 1: apply_chat_template + processor(text=..., audio=[...]) ===")
    try:
        prompt = proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        inputs = proc(text=prompt, audio=[args.wav], return_tensors="pt")
        inputs = {k: (v.to(model.device).to(torch.bfloat16)
                      if v.dtype.is_floating_point else v.to(model.device))
                  for k, v in inputs.items()}
    except Exception as e:  # noqa: BLE001
        print(f"[fail] {type(e).__name__}: {e}")
        print("→ 请在云机上确认 Gemma4Processor 的正确调用方式（见 processor_config.json: processor_class=Gemma4Processor）")
        return 2

    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=args.max_new,
                             do_sample=True, temperature=0.8, top_p=0.9)
    n_in = inputs["input_ids"].shape[1]
    reply = tok.decode(out[0][n_in:], skip_special_tokens=True).strip() if tok else str(out)
    print("=== 元亨（听音频后）===")
    print(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
