# v8 训练包说明（2026-09-26）

数据：`sft_persona_v8_train.jsonl`（3440 条）/ `sft_persona_v8_val.jsonl`（607 条）/ `sft_persona_v8.stats.json`

组成（4047 条）：场景 1978 ｜ 工具 626（真实工具名）｜ 记忆 588 ｜ 利贞 300 ｜ 诚实边界 180 ｜ 承认不确定 155 ｜ 安全拒绝 120 ｜ 黄金 69 ｜ 真实对话 31

## 一键训练（A800 80G）
```bash
cd cloud
export HF_TOKEN=...            # huggingface token（走 hf-mirror）
TAG=v8 SKIP_DPO=1 bash run_qat.sh
```
- `SKIP_DPO=1`：与 v6 同策略（含工具样本，避免风格 DPO 造成工具回归）
- 基座：`google/gemma-4-E4B-it-qat-q4_0-unquantized`（与部署 GGUF 同源）
- 预计：SFT 约 30–60 分钟（3440 条 × 3 epoch，bf16 LoRA r16/α32，seq 2048）

## 完了之后
```bash
tar czf yuanheng-qat-v8.tar.gz -C /root/autodl-tmp/models/lora yuanheng-v8-sft
```
回传本地 → `tools/llama_lora_up.py` 挂 v8 → `tools/persona_regression.py --live --version v8 --save-answers`
