# 元亨训练方案（A100 · SFT → DPO）

> 底座：`google/gemma-4-E4B-it`（**多模态，保 vision/audio 塔**，未来端到端语音用）。
> 本机 8GB 跑不了（bf16 放不下、bnb 与 Gemma4 在 Windows 崩）→ 云上 Linux A100 跑。

## 一、总路线（顺序做，推荐）
1. **SFT**：只用**优质样本**（v3 = 真实38 + 黄金71 + 场景338 + 记忆315 = 762），训到人格立住就停（防过拟合）。
2. **DPO**：用「高分（chosen）vs 低分（rejected）」偏好对纠偏。
3. **记忆**：外挂 RAG / 记忆模块，**不混进权重**。

## 二、显存与量化
| 方式 | 显存 | A100-40G |
|---|---|---|
| **QLoRA 4bit**（Linux bnb 正常） | ~10–16GB | 轻松，首选 |
| bf16 LoRA（不用 bnb） | ~18–24GB | 可，质量更稳 |
- A100-40G 两条都能跑；**默认 QLoRA 4bit**（快、省），失败自动退 bf16。
- LoRA 目标模块 `q,k,v,o,gate,up,down_proj`——只命中语言部分，**塔冻结**。

## 三、超参（SFT）
- LoRA r=16 α=32 dropout=0.05；lr 2e-4；epochs 3；seq 2048；batch 2 × grad-accum 8（A100 40G）。
- 提示掩码（只学 assistant 段）；bf16；梯度检查点开。

## 四、DPO 数据构造（关键）
- **chosen**：v3 里的优质答案（黄金/场景/记忆 keep）。
- **rejected**：三种来源，优先级从高到低
  1. 素材里 **drop/candidate** 的旧答案；
  2. **SFT 前基座**对同一 prompt 的生成（最容易批量造，质量对照明显）；
  3. 对优质答案做**轻度劣化**（加客服腔/罗列/加长）。
- 目标 ~300–600 对；训练用 `trl.DPOTrainer` + LoRA（在 SFT adapter 之上继续训）。

## 五、验收
1. SFT loss 收敛；盲测人格题（自我介绍/心情/哲学）像元亨。
2. DPO 后：客服腔/列表/啰嗦显著减少。
3. 回归：工具调用/记忆/群聊行为不崩（跑 smoke 子集）。

## 六、产物
- `models/lora/yuanheng-sft/` → `models/lora/yuanheng-dpo/`
- 转 GGUF LoRA：`convert_lora_to_gguf.py`；服务：`llama-server --lora`
- 需要时**全量合并**（merge）成新 gguf 给 llama.cpp。
