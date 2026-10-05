# CosyVoice 分享包与 BNB 量化：核验结果和 8GB 验证方案

日期：2026-10-05。范围：公开页面、官方资料和源码静态核对、MCP 台账查询。本轮未下载分享包/模型，未安装依赖、加载权重、运行推理或解冻语音。

## 1. 先给结论

用户转述的“BNB 量化存储，计算时恢复 FP16”有技术原理依据，准确说法是：**对受支持的权重低比特存储，计算时反量化或由相应低比特算子参与 FP16/BF16 计算。恢复的是浮点表示，不是量化前的原始精度。** 这可能降低权重占用，但不保证提高速度，也不把所有组件的显存一起缩小。

当前官方 vLLM-Omni 已有 CosyVoice3 两阶段流式服务，但 **CosyVoice3＋BNB＋当前分享包这一组合尚未核实**。不能给出“加上某一启动参数即可运行”的承诺。它适合作为语音解冻后的隔离候选，暂不替换已有 Qwen Base 小艺主路。

## 2. 分享链接能确认到什么

链接：https://pan.quark.cn/s/66cbf9410f20 。用户提供的标题只有「cosyvoic...full」。

- 分享页 HTTP 返回网页框架，未包含可核实的文件清单。
- 两个公开分享元数据接口（drive-pc.quark.cn、drive-h.quark.cn）均返回 HTTP 404，未得到目录。这个错误不能证明分享失效，只能说明本轮读取方法没获取到文件信息。
- 尚不知道 full 是整合环境、全部权重、精度标记还是发布者自定义名字。不能据名字推断 CosyVoice 版本、FP16、BNB 或 Omni 兼容。
- 已请求用户补充完整文件名、模型版本、发布者说明或启动命令。分享包本身保留待核实；没有以官方 CosyVoice3 文档冒充包内检查结果。

后续先看 README、文件目录、模型 config、依赖锁和启动命令。若是旧 CosyVoice/CosyVoice2、Windows 一键包或原生 PyTorch 包，不能直接认作 Omni CosyVoice3 的模型目录。不要为了读版本而先启动安装器或反序列化未知 .pt 文件。

## 3. 三件不同的事

| 说法 | 正确理解 | 不应推导的结论 |
|---|---|---|
| BNB 4bit 权重 | 例如 NF4/FP4 加量化状态、缩放等元数据 | 整机显存减少到四分之一 |
| FP16/BF16 计算 | 激活与受支持计算路径使用浮点，量化权重按内核需要反量化 | 量化误差消失、音质必然不变 |
| 流式 TTS | 文字/音频可按模型和接口能力分段推进 | 系统已经原生端到端、扬声器已经全双工 |

若实现每次保留整模型 FP16 副本，则会抵消大量压缩收益；若只按层/块临时反量化，仍有临时工作区。不同 batch、prefill/decode 与内核可能采用不同路径，不应笼统承诺“从不生成 FP16 权重临时量”。

bnb 的 `Linear4bit` 明确区分压缩权重和 compute_dtype。Transformers 中的 `bnb_4bit_compute_dtype` 不是可以不经映射直接复制给所有 vLLM/Omni 命令的参数；纯 HF Linear4bit 与 vLLM 的量化线性层是不同实现入口。FP16 也不一定比 BF16 快或更合适，需按模型、内核和数值表现选择。

## 4. 官方支持与源码证据

本轮继续使用 0630 固定的源码版本：vLLM `b1401e0aa7eb7803c38e4d2d306cb2a16c8828a2`；Omni `6dd0d1f9310f7598b773c796b434c8000c2816ec`。CosyVoice/bitsandbytes/plugin 的 main 内容保存 SHA256，没有把它们当锁定发布版。来源及失败记录在 `artifacts/cosyvoice_bnb_review_20261005/source_manifest.json`。

### 4.1 能确认

- vLLM 官方 BNB 文档支持预量化和加载时量化；此快照的支持由 `vllm-bnb-plugin` 提供。
- Omni 有 `CosyVoice3Model`，官方 Speech API 列 `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`，ref_audio＋ref_text 克隆，24kHz 输出。
- CosyVoice 官方 README 宣称 text-in/audio-out 双流式；台账 0049 已把 CosyVoice3 列为双流式与情绪候选。但必须验证选定服务路径是否保留原生增量文本能力，不能只引用原生库 README 为 Omni 包的行为背书。
- Omni `cosyvoice3.yaml` 使用两阶段：Talker 生成语音 token；Code2Wav 做 flow matching＋vocoder。已配置 async chunk 音频流。

### 4.2 不能直接推出

- Omni 量化指南的 Omni/TTS 表（所列例子为 Qwen3-Omni/Qwen3-TTS）把 BitsAndBytes 标记为 **Not validated**；CosyVoice3 没有在本轮取得的 BNB 已验证组合中。这是证据缺口，不是断言它绝对不支持。
- Omni 的 `DiffusionBitsAndBytesConfig` 明确针对 diffusion transformer 的受支持 `LinearBase`；支持 NF4/FP4 和 FP16/BF16 激活。存在这份实现不证明它会自动替换 CosyVoice 的任意 torch.nn 模块或声码器。
- CosyVoice3 Talker 确实使用内部 Qwen2Model，但外层 `load_weights` 直接 `torch.load(llm.pt, map_location=device)`，重映射 `llm.model.model.*` 键，再装 speech_embedding/llm_decoder；Code2Wav 另外加载。**普通 HF BNB loader 能否经过这条专用路径正确传递 quant_state、处理融合层和加载 dtype，必须验证。** 加载期间完整 checkpoint 还可能形成比稳态更高的峰值。
- 公开部署 YAML 没有提供一个本轮可确认的 CosyVoice3 BNB 成功配置。不要把 `--quantization bitsandbytes --dtype half` 当已验证命令交付。

### 4.3 项目历史要避免重复踩坑

MCP 台账 0366、0367 记录过本机 Gemma＋Transformers＋BNB 的 QLoRA 装载段错误和权重前缀不匹配，尝试多个 BNB 版本仍失败。应保留为**当时具体组合**的失败证据，不能推广成所有 BNB/CosyVoice/新版 WSL 都不可用；同样不能因为 CosyVoice 内部是 Qwen2，就宣称现有 Gemma 的 BNB 阻塞已经解决。

## 5. 对 8GB 能有多大帮助

假设某个被量化组件确实含 0.5×10^9 个参数，全部可从 FP16 转 W4：

- FP16 纯权重：约 1.00GB（0.93GiB）。
- 4bit 纯权重：约 0.25GB（0.23GiB），另加缩放、量化状态等。
- 理论上限节省约 0.75GB（0.70GiB），实际可量化层范围受限，收益通常更少。

这是算术示例，不是该包参数盘点。0.5B 名称不代表整个 TTS 管线总参数和实际常驻占用。

Gemma、LoRA、LLM KV、TTS token KV、flow/vocoder、参考音特征、CUDA Graph/workspace、Windows 桌面/数字人渲染都仍占显存。量化权重与量化 KV 是独立选项。若主要瓶颈在 Code2Wav、缓存预留或阶段等待，量化 Talker 权重并不能解决大部分延迟。

Omni CosyVoice 默认 stage0/1 的 gpu_memory_utilization 为 0.4/0.2，max_num_seqs 都是 8。源码注释明确当前 chunk/batch 配置按 H100 调优，换较慢 GPU 曾出现流式连续率下降；不能照搬到 RTX4060 8GB。0.4＋0.2 是配置占用目标，不是包含所有瞬时开销的整机硬上限。

## 6. 推荐实验：三个验收节点

### C1 包身份与原精度基线

先取得文件清单、完整模型名、权重来源/哈希、环境版本、命令；确认是 CosyVoice 哪一代、原生库还是 Omni。独立环境，优先复用可信本地资产；单 TTS、单序列，先按支持的原精度跑通原音色克隆、短长句、流式和取消。测加载峰值与稳态峰值，保留模型身份。

通过条件：模型真实匹配、无缺失权重/随机初始化、流式增量在句末前出现（分别标明音频流和文字输入流）、错误和取消有终态。若原精度基础路径就失败，先修版本/加载，不能叠加 BNB 混淆原因。

### C2 只量化适合的 Talker 层

维持相同文本、reference、采样参数和音频格式，研究 stage0 专用 BNB loader 是否可用；flow/vocoder、speech embedding/head 首轮维持基线精度。必须记录实际量化的模块、压缩权重及 quant_state、跳过层、dtype 和内存，排除“参数生效但模型回退原精度”的假成功。检查加载峰值，不能只看启动后的 nvidia-smi。

与原精度至少比较 20 条覆盖短句、长句、数字、中英混合、无标点、情绪/停顿、尾音样本，并重复关键样本。指标：TTFA（首PCM）、真实首播、RTF、音频间隙、尾部缺字、发音/音色、取消后队列/显存回收。声学量化质量用听测和适当识别对照，不能只断言同 seed 输出必须逐字节相同。

建议只在显存收益可重复、音质可接受、代表性 P95 首音没有超过基线 10% 的明显退化且 RTF/间隙符合语音目标时进入并存测试；10% 为候选评审阈值，不是官方承诺。明确失败可回到原精度/原 Qwen 后端，不开始重训。

### C3 与当前 Gemma 并存及业务接入

先总 GPU 预算，再在当前 Gemma/v7b 下测 TTS 并存，记录整机峰值、TTFA/首播、前后台争抢、长句持续播放及取消；保留至少可观察的显存余量，不接受刚好挤满且一开渲染就 OOM。

接入仍通过现有 TTSProviderPort；小艺参考音可作为克隆输入对照，但跨 TTS 音色一致不能保证。先不碰人格/记忆/QQ。CosyVoice 是 TTS，Gemma＋CosyVoice 仍是模块化链路；AEC、听说并行、代际 fence、播放清空、扬声器/蓝牙真机验收另算。只有这些证据成立才能讨论全双工，不因 BNB 生效便宣告完成。

## 7. 训练与下一步

BNB 推理量化本身通常无需训练，现有参考音克隆也不因此必需训练。质量不佳先做原精度对照、限定量化层、配置和分段修正，不把训练作为首个补救。若分享者用了专用补丁或微调权重，需其版本与方法才能复现。

当前最有价值的补充信息：**完整包名/版本、实际启动命令、加载时日志、整机显存和首音测量**。其中任意“已量化成功”的截图都不能替代层级核验和完整链路测量。本轮状态：原理可行、官方 CosyVoice3 服务存在、精确 BNB 组合和分享包未验证，C1/C2/C3 均 planned。

## 官方来源

- [vLLM BitsAndBytes 文档](https://github.com/vllm-project/vllm/blob/b1401e0aa7eb7803c38e4d2d306cb2a16c8828a2/docs/features/quantization/bnb.md)
- [Omni 量化支持矩阵](https://github.com/vllm-project/vllm-omni/blob/6dd0d1f9310f7598b773c796b434c8000c2816ec/docs/user_guide/quantization/overview.md)
- [CosyVoice3 加载实现](https://github.com/vllm-project/vllm-omni/blob/6dd0d1f9310f7598b773c796b434c8000c2816ec/vllm_omni/model_executor/models/cosyvoice3/cosyvoice3.py)
- [CosyVoice3 两阶段配置及 GPU 调优注释](https://github.com/vllm-project/vllm-omni/blob/6dd0d1f9310f7598b773c796b434c8000c2816ec/vllm_omni/deploy/cosyvoice3.yaml)
- [Omni BNB diffusion 实现](https://github.com/vllm-project/vllm-omni/blob/6dd0d1f9310f7598b773c796b434c8000c2816ec/vllm_omni/quantization/bitsandbytes_config.py)
- [CosyVoice 官方](https://github.com/FunAudioLLM/CosyVoice)、[bitsandbytes Linear4bit 实现](https://github.com/bitsandbytes-foundation/bitsandbytes/blob/main/bitsandbytes/nn/modules.py)

归档台账：**0632**（MCP 追加）。delivery_id=cosyvoice-bnb-review-20261005-v1。
