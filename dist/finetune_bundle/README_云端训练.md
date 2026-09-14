# 元亨微调 · 开箱即训包（GPU ≥24GB）

> 目标：在 GPU（≥24GB）上对 **Gemma-4-E4B 多模态** 做 **bf16 LoRA**（不用 bitsandbytes，
> 因为它与 Gemma4 架构不兼容；塔冻结，语言部分可训——保住未来端到端语音所需的 audio/vision 塔）。
> 数据：本包自带 v3 训练/验证集（762 条，真实38+黄金71+场景338+记忆315）。

## 1. 环境
```bash
# Python 3.12；装 PyTorch（按 CUDA 版本）+ 训练依赖
pip install torch --index-url https://download.pytorch.org/whl/cu124   # 或对应 CUDA
pip install "transformers==5.15.1" peft datasets accelerate safetensors
```

## 2. 基座权重
```bash
# gated：先接受 Gemma 许可，再设 HF_TOKEN
export HF_TOKEN=hf_xxx            # Windows: setx HF_TOKEN hf_xxx
huggingface-cli download google/gemma-4-E4B-it --local-dir models/gemma4-hf/gemma-4-e4b-it
```

## 3. 训练（bf16 LoRA，保多模态）
```bash
python finetune_train.py --tag v3 --multimodal --no-4bit \
  --base models/gemma4-hf/gemma-4-e4b-it \
  --config config/finetune.cloud.json
```
- `--multimodal`：加载 `Gemma4ForConditionalGeneration`（含 vision/audio 塔，冻结）。
- `--no-4bit`：bf16 全模型 + LoRA（不经过 bnb）。
- 产物：`models/lora/yuanheng-gemma4-e4b-v3/`（LoRA adapter）。

## 4.（可选）转 GGUF 供 llama.cpp 服务
```bash
python llama.cpp/convert_lora_to_gguf.py models/lora/yuanheng-gemma4-e4b-v3 --outtype q8_0
# 挂载（服务时）
llama-server -m gemma4-e4b-aggr-q4km.gguf --mmproj mmproj-gemma4-e4b.gguf --lora adapter.gguf
```

## 5. 顺序建议（SFT → DPO）
1. 先按本包做 **SFT**（只用优质样本；训到人格立住就停，别过拟合）。
2. 再用「高分 vs 低分」构造偏好对做 **DPO** 纠偏。
3. 记忆仍走 **RAG/记忆模块**，不混进权重。

## 6. 文件清单
| 文件 | 说明 |
|---|---|
| `sft_persona_v3_train.jsonl` / `_val.jsonl` | 训练/验证集（chatml messages） |
| `finetune_train.py` | 训练脚本（支持 `--multimodal` / `--no-4bit`） |
| `config/finetune.cloud.json` | 24GB+ 预设（bf16、LoRA r16、seq2048） |
| `sft_persona_v3.stats.json` | 数据来源统计 |

## 7. 注意
- 本机（8GB 显存 / 15.8GB 内存）**跑不了**：bf16 放不下、bnb 与 Gemma4 不兼容。故上 GPU。
- LoRA `target_modules` 为 `q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj`，只命中语言部分；塔不被训练。
- 若显存吃紧：调小 `max_seq_len` / `batch_size`，或用 `gradient_checkpointing`（默认开）。
