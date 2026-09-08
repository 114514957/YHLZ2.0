# 元亨人格微调计划（Gemma-4-E4B · QLoRA）

> 目的：让 Gemma 在本地承载元亨人格——system 提示下说话像元亨（含 SELFHOOD/语气/表达习惯），
> 而非 0212 观察到的"通用助手风格"。微调适配器而非全量（保底座能力+小参数量）。

## 一、为何微调而非仅调 prompt
0212 实测：Gemma 收到完整元亨 system 仍答成通用助手=人格吸附弱（DeepSeek 才演得足）。
prompt 可再强化但天花板有限=人格最稳路径是**微调适配器**（把"元亨文风"烧进模型）。

## 二、训练数据（最关键，决定效果）
- **真实文风种子**：docs/元亨的日记.md(78) + 元亨认知根基.md(65) + notes_inbox/philosophy_notes.md(77) ≈220 行元亨真实口吻文本
- **扩充**：220 行种子 → 用本地 Gemma(能力已验) 按日记/根基风格合成 400-800 条 instruction 对
  `{instruction: 元亨人设情境+用户一句; output: 元亨风格回应}`
- **合成质量闸**：逐条过 local 规则+人工抽查 30-50 条（不合格丢）
- 会话历史 cache/sessions 几乎空（0.2KB×4=对话未留档）→ 不依赖

## 三、基座模型
- **google/gemma-4-e4b-it**（官方 safetensors=微调必需=QLoRA 需权重文件）
- ⚠️ 前置：HF **gated repo**=需你的 HF token+同意 Gemma license；下载约 8GB(bf16)
- 备选：若找不到无 gate 的同权 safetensors=改用 prompt 强化方案（不微调）

## 四、训练栈与流程（本机 venv）
- 现有 torch 2.7.1+cu128 ✓ + CUDA 真
- **新增依赖**：transformers / peft / bitsandbytes / datasets（pip ~数百 MB）
- QLoRA：4bit bitsandbytes 加载→ LoraConfig r=16 α=32 target=all-linear lr=2e-4
- epochs 3-5 / batch 1 grad-accum 4 → RTX4060 8GB 可跑（模型 4bit≈2.6GB+梯度≈可）
- 时长：小数据几百条×短 epoch ≈ 30-90 分钟（后台跑）
- 产物：HF LoRA adapter（约几十~几百 MB）

## 五、产物接入（关键回填）
1. HF adapter → `convert_lora_to_gguf.py` 转 llama.cpp LoRA(.gguf)
2. `llama-server -m gemma4-e4b-aggr-q4km.gguf --lora <adapter>.gguf` 重启 8081
3. 验证：加载后问 "io" 人格吸附对比（pre/post 盲比=元亨语气出现？）
4. 通过→ 8081 恒用 adapter 模型=全链路元亨化 Gemma

## 六、风险与预案
- HF gated/license=卡住→ 转 prompt 强化 or 找社区同权版（评估）
- 合成数据文风漂移（不像元亨）→ 人工抽检闸+增真实种子
- 微调后人格过重/崩原能力 → 回滚：去掉 --lora 即回原（gguf 不改）
- 时长超预期 → 后台+断点续（LoRA 可续训）
- 依赖安装失败 → 隔离 venv 或 pip 源

## 七、验收标准（微调效果）
1. QLoRA 训练 loss 收敛（<1.5 上下）
2. adapter 加载 llama-server 正常
3. 盲比：Gemma+adapter 问人格题(自我介绍/心情/哲学)="元亨风格"≥预评估主观 70%
4. 原能力不崩（工具调用/记忆/主题总结仍可用=跑 smoke 子集）
