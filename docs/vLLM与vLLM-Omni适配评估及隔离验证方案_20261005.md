# vLLM 与 vLLM-Omni：YHLZ 适配评估与隔离验证方案

日期：2026-10-05。范围：官方资料研究、MCP 台账核对、源码静态检查与方案补充。本轮没有安装环境、下载模型、启动推理、改业务代码或解冻语音。下述验证均为 planned，不能计入已通过项目。

## 1. 推荐结论

**保留现有 Gemma＋v7b LoRA＋llama.cpp 主路；vLLM 作为可选 LLM 后端验证；vLLM-Omni 的 Qwen TTS 作为独立候选；原生端到端全双工作为单独研究路线。** 当前非语音六段收口照常推进，这三个研究项不成为 T2～T6、G2/G3 的新增硬依赖。

不能只看“支持 streaming”决定迁移。要同时问：支持的是文字增量、音频增量、增量文字转语音，还是持续音频输入输出？模型和人格能否保持？8GB 显存是否容纳权重、KV、解码器、CUDA Graph 和桌面渲染？

| 选项 | 对 YHLZ 的潜在价值 | 当前障碍 | 建议优先级 |
|---|---|---|---|
| vLLM 替代 LLM 推理服务 | 前缀缓存、长输入调度、流式服务、多个作业管理 | 当前 Gemma GGUF＋GGUF LoRA 组合未验证；单用户未必更快 | 可选实验，先做资产和接口核对 |
| llama.cpp Gemma＋Omni Qwen TTS | 可保持现有人格；标准音频服务、音色复用、分句输入与音频输出 | 两阶段显存开销、WSL 环境、Base 克隆质量和取消语义 | 语音解冻后的优先候选 |
| Omni 原生全双工模型 | 持续听说、会话状态、重叠输入、播放确认和恢复 | 要换匹配模型；现有人格 LoRA 不可直接移植；资源与工具能力受模型限制 | 独立实验，不替换主路 |

## 2. 项目并不是从零研究 vLLM

依据 MCP 的台账 0094、0107、0111：

- 0094 已接受“独立 WSL 服务＋可选 Provider”的方向；前缀缓存与 chunked prefill 都有过分析。
- 0107 已在 RTX 4060 Laptop、8,188 MiB 的机器上跑通 WSL vLLM，模型为 Qwen2.5-3B-Instruct-AWQ，端口 8765，单序列、上下文 2048。历史短提示预热后 3 次首包为 114.2、42.1、61.6 ms；当时占用 4,028 MiB。这不是当前 Gemma 的数据，也不是现在服务在线的证明。
- 0111 已落地 `LLMProviderPort`、`backend/llm_vllm_provider.py`、reasoner 和真实客户端探针。客户端取消成功不等于已经测到服务端 GPU 请求释放。
- 0218 的 NEKO 纪要已记载 Qwen3-TTS 经 vLLM-Omni 服务的参考方向；本轮未重新核验 NEKO 当前分支，不能把该历史纪要当作本机可用证明。

当前静态核对：

| 组件 | 当前实现/资产 | 迁移应保留的内容 |
|---|---|---|
| LLM | `models/gemma4-gguf/gemma-4-E4B_q4_0-it.gguf`＋`models/gguf-lora/yuanheng-v7b-lora.gguf`；llama-server 8081，8192 上下文、parallel=1、Jinja；mmproj 未 GPU offload | 实际基座、v7b 人格、模板、采样、工具契约和回滚入口 |
| 旧 vLLM 适配器 | SSE/OpenAI-compatible，默认 8765、qwen2.5-3b-awq | HTTP/流生命周期代码可复用，但默认配置和能力契约需更新 |
| 默认本地音色 | `target_voice_profile.py` 默认小艺：Qwen3-TTS-12Hz-0.6B-Base＋本地 reference audio/text | 继续用 Base 克隆，不能静默改成 CustomVoice 的 Vivian |
| 现有 TTS | faster-qwen3-tts 子进程；生成器先收完整文本，音频分块输出；能力声明 `text_stream=False` | 当前取消、代际隔离、播放与音色资产；不能仅更换名称就声明真增量输入 |

旧 vLLM 适配器还存在这些静态限制：只读取 `delta.content`，不组装 `delta.tool_calls`；计量中的 tokens 实际递增的是 content chunk；signal 在收到下一段时才检查；health 默认端点存在即 available，没有严格绑定目标模型；finish_reason 被写为 stop。用于纯文本探针可复用，用于带真实工具的生产主路需补契约。代码注释声称断开 HTTP 会停止远端解码，后续必须取得服务端观测证据。

## 3. 官方资料的当前结论

本轮官方源码按远端 HEAD 固定并再次获取，正文快照及 SHA256 存在 `artifacts/vllm_review_20261005/`：

- vLLM：`b1401e0aa7eb7803c38e4d2d306cb2a16c8828a2`。
- vLLM-Omni：`6dd0d1f9310f7598b773c796b434c8000c2816ec`。
- Qwen3-TTS README 保存内容哈希；未锁定其提交号。它关于 Omni “目前只支持离线”的段落，与 Omni 当前在线实现文档冲突；以下在线能力以提供服务的 Omni 对应快照为依据。

### 3.1 vLLM：有价值，但不保证单用户更快

官方支持表已列出 `Gemma4ForCausalLM`、`Gemma4ForConditionalGeneration`，标记语言主干 LoRA 支持；E2B/E4B 标记可接受音频输入。**音频输入能力不代表语音输出或原生全双工。** 本轮没有发现“把现有 Gemma＋Qwen 独立权重自动拼成原生端到端模型”的证据。

最值得吸收的是：

1. **前缀缓存**：同样的 system/prompt/tool schema 和已提交历史可以复用 prefill。把变化的时间、运行状态、召回记忆放在稳定前缀之后；不得为了缓存改变优先级、注入防护或丢失必要信息。缓存不是长期记忆，且只减少输入处理，不能缩短回答 decode 本身。
2. **chunked prefill**：把长输入分块安排，避免长记忆输入占住调度步。不是越小越低延迟：小块可能改善其他请求的输出间隔，却使本请求更晚完成 prefill。需分别测 TTFT 与 ITL。
3. **连续批处理与缓存管理**：多请求有优势，但本项目后台应服从前台优先，不能为了吞吐让复盘和当前聊天争抢。先做单前台＋受控后台场景。

官方仍不原生支持 Windows，走独立 Linux/WSL 环境。GGUF 当前在官方文档中被标为实验性、优化不足，并迁到 `vllm-gguf-plugin`。有 Gemma 和 LoRA 支持表，不等于支持当前 GGUF 基座＋GGUF LoRA＋量化＋模板的全部组合。

迁移路径先核验原训练基座、tokenizer、chat template、原始 PEFT adapter 的 `adapter_config.json`/`adapter_model.safetensors`、rank 与 target_modules。优先验证匹配的 HF/受支持量化格式＋原始 PEFT LoRA；这仍须检查量化和 LoRA 的组合支持。不可把 GGUF LoRA 改扩展名当作 PEFT，也不可换一份相似 Gemma 后继续称“同一人格模型”。原始资产缺失时，先查训练输出与备份。

### 3.2 Omni Qwen TTS：在线与音频流已存在，但双向流的含义要分清

当前官方 recipe 和 Speech API 已提供：

- `/v1/audio/speech`：完整文本输入，支持流式 PCM 输出。
- `/v1/audio/voices`：Base reference/precomputed voice 的注册、查询和删除接口。
- `/v1/audio/speech/stream`：WebSocket 接收 `input.text`，支持持久连接、多 utterance 和音频分块。

**关键默认值：`split_granularity=none` 时，WS 会等 `input.done` 后把缓冲文字作为一个 TTS 请求。** `stream_audio=true` 只影响音频输出。设为 `sentence` 或 `clause` 才会在标点边界分请求提前合成。因此当前资料证明的是服务端分句衔接＋分块音频，不能据此宣称 Qwen 模型维护一个从不重启的 token 级双流会话。

对 YHLZ 可以借鉴：LLM delta→一个确定的分句者→TTS 请求→PCM→现有播放。客户端分句和服务端分句只选一个作为权威，避免重复拆句。文本无标点的长段仍需要最大等待/最大长度设计，这不是当前 WS 文档保证的功能。Base 克隆的句首、停顿、连贯音色与尾音需分别听测。

Omni 的 `qwen3_tts.yaml` 当前是 Talker＋Code2Wav 两阶段，默认各 `gpu_memory_utilization=0.3`、各 `max_num_seqs=64`；async chunk、首块提前输出和可选 chunk ramp 已有实现。它们可以参考，但应为 8GB/单用户另制配置。12Hz 的 codec frame、prefill token budget、文本字符和播放回调块是不同单位，不能把某个 chunk_size 复制到所有层。首帧 1 个 codec frame 约对应 83ms 音频内容，不能当作 83ms 实际首音延迟。

音频错误处理必须接入代际和终态：官方 recipe 说明 Base 部分错误会要求 discard 已输出音频，raw PCM 可能在部分字节后断开。已播放的声音无法追回；不能盲目整句重试造成重复播报，应停止、清队列并记录实际播放进度。语音仍冻结，本轮不实现这些变化。

### 3.3 Omni 原生全双工：已有实现，必须匹配模型与运行能力

当前官方有 `/v1/realtime?duplex=1`，也有 `/v1/duplex` 别名。需要模型注册 duplex_plugin，部署设 `session_mode: duplex`；只换 URL 不会让普通模型变全双工。

有用机制：engine-owned session、持续音频输入输出、overlap decision、epoch/turn、`playback.ack`、断线恢复、按 session.created 的 capabilities 决定可用操作。这些非常适合对照 YHLZ 的会话、打断与播放记录设计。

官方 Full Duplex 文档当前列出 MiniCPM-o 4.5、Qwen3-Omni、Nemotron VoiceChat 对应部署；其中支持的打断、恢复、输入格式、工具调用各不相同。支持表把 PersonaPlex 写作 full duplex，但端点说明明确其尚未迁到新 plugin contract；本方案不把它登记为当前统一接口已可用。当前 Realtime 文档还指出该模型组中工具调用由 Nemotron VoiceChat 提供，不能把一般 ChatCompletion 的 tools 能力直接套到所有 duplex 模型。

MiniCPM-o recipe 的单卡说明是大显存 GPU，多卡 consumer profile 包括 8×4090；这不是 8GB 推荐部署。Qwen3-Omni 示例为 30B-A3B，A3B 是每步激活参数而不是只加载 3B 权重。现有 v7b Gemma LoRA 也不能移植给这些不同模型。

端到端可减少显式 ASR 文本转换与阶段等待，但音频编码、上下文 prefill、音频生成、解码和播放缓冲仍耗时。全双工还要求持续接收与合理处理重叠讲话。对扬声器主通道，AEC/参考音频、声学误触发和播放设备延迟仍在客户端范围；文档里回显 noise_reduction 配置不表示已执行降噪，更不能当作 AEC 证据。

## 4. 8GB 显存：先做资源账，再决定是否值得迁移

实际总占用应分别采集 Windows＋WSL 同一物理 GPU 的总量与每进程峰值：

`峰值 = LLM权重 + LoRA + KV + 推理workspace/graphs + TTS权重/codec/cache/workspace + 桌面/数字人渲染 + 其他进程`

不要用模型文件大小或 E4B 的“有效参数”直接估计全部常驻内存。把 `gpu_memory_utilization` 当服务配置预算，不能把 0.35 理解为整机不会超出 35%，也不能认为两个 stage 的比例可以忽略叠加。

历史 0107 的 4,028 MiB 加 0094 记录的旧 Qwen TTS 峰值约 2.4 GiB，只是并存假设；不是当前 Gemma/Base 克隆并存实测。

更直接的反例：Omni Qwen TTS recipe 的 0.6B CustomVoice/4090 测试，默认空闲约 13.5 GiB；调低配置后说明空闲约 5 GiB、推理峰值约 10 GiB。这是特定 24GB 卡与配置的参考数据，不是所有 Omni 的最低要求；但足以否定“0.6B 就一定适合 8GB 并存”。Base 克隆与本机还需单独测。

低显存实验应：每阶段 max_num_seqs 从 1 开始；限制上下文与缓存，关闭未用模态；先 eager 建功能基线，再决定是否用 graph；按阶段测峰值。不得为少占显存频繁装卸权重后还声称满足低延迟；若冷加载出现在每回合，单独计入首音。两个全 GPU LLM 不同时常驻。

统一调度也要分职责：LLM 前台/后台共用推理准入；TTS 有独立资源预算与播放控制。为避免 OOM 而把整回合 LLM→TTS 全部串行，会消除本想验证的流式重叠；不能只看“无 OOM”而忽略延迟退化。

## 5. 隔离验证分三节点，按障碍逐步停止

### V1：资产与协议节点，不启动业务

输出版本与路径清单：WSL 发行版、vLLM/Omni/PyTorch/CUDA、模型基座与 adapter 哈希、量化、模板、音色、端口、进程所有者。历史 0.28 环境不能直接 pip 装当前 Omni 混用；锁定相匹配版本，不能从 main Quickstart 和旧环境各取一半配置。

核验 Gemma 架构＋量化＋LoRA 的组合，而非只查架构名字；核验 tool_calls/delta/stop/cancel；Qwen 候选必须是现有 0.6B Base 克隆资产。缺资产、组合不支持、无法保留人格时，记录阻塞并结束这一路，不开启重训。

验收：现有业务和语音冻结状态不变；每项兼容都有证据或 explicit unknown；不存在“能加载旧 Qwen 就算新 Gemma 已适配”的替代证明。

### V2：同模型受控性能与质量节点

先完成 0622 的增量时间量尺，再做引擎 A/B。Gemma 比较要求相同基座/adapter/模板/prompt/上下文/输出限制/采样；如必须重数量化，则拆成引擎变量和量化变量，不能把输出差异归因给单一引擎。

计划输入短/中/长三组，区分冷启动、热启动、稳定前缀命中/未命中；每格至少 20 次，关键人格与工具题至少 3 轮；30 秒服务恢复与远端取消释放单测另记。记录：客户端请求→首个有效文本 delta（TTFT）、增量间隔、总耗时、engine真实 token 数、排队时间、GPU 总峰值与进程峰值。不得把 HTTP 首包、空 SSE、chunk 数当成首 token/真实 token 率。

迁移建议门槛：同等输出质量和工具证据下，代表性负载热态 P95 TTFT 改善至少 20%，增量间隔无明显退化；没有 OOM/显存超预算、取消残留、人格和工具语义退化。20% 是本方案的收益门槛，不是官方性能承诺。若无收益，保留 llama.cpp，吸收缓存与调度设计即可。

TTS 在语音解冻后单独比较现有 faster 与 Omni，同一 Base、reference、文本、语种。先 TTS 单独，再与生产 Gemma 并存；观测首 PCM、真实首播、RTF、最长音频空洞、尾音、音色与取消终态。RTF<1 只是平均生成追得上播放，仍可能有长空洞。要求慢设备/长文本也不突破已冻结的语音验收标准；不得用 CustomVoice 数据替代小艺克隆。

### V3：原生端到端／全双工节点，独立于非语音验收

资源和匹配模型允许后，再立专用 session adapter；不伪装成只 yield str 的 LLMProviderPort。接口需覆盖 PCM 输入、文字/音频事件、capabilities、epoch、cancel、播放确认、恢复与实际模型身份。

分别验证：持续输入时仍有输出；用户插话使旧音频终止；短应声不会全部误打断；网络恢复不重复播放；只把已播放内容写成“已说”；扬声器不自问自答；蓝牙与扬声器分别计实际延迟；工具/记忆结果经过现有权限和效果发布协议。输出工具能力不匹配时保持明确不可用，不能偷偷把业务执行权交给新语音模型。

成功标准按现有冻结语音标准复核；节点失败时保留测量产物，不影响非语音 G2/G3。这一节点没有本轮已通过内容。

## 6. 是否要训练

**使用 vLLM/Omni 本身不需要训练。** 用当前人格换推理后端，先解决权重格式、原始 adapter 和模板一致性。原始训练资产不足是资产恢复问题，不能先认定必须重训。

现有 Qwen Base 克隆主要是推理时参考音色，也不因迁移服务就必然需要训练。要把元亨人格做进新的原生语音模型，prompt 能力先测；保持 Gemma v7b 的同等行为不能自动保证，可能另需该模型自己的微调和评测。给 Gemma 接一个 Omni 服务不会训练出原生全双工能力，也不会凭空生成音频 decoder。

## 7. 与当前收口计划的关系

0622 六段保持不变。当前可直接吸收：稳定提示前缀、分别记录 TTFT/间隔/排队、明确工具与取消契约、模型身份核验、前后台准入和资源账。不要趁换服务跳过 T2 精确读回、T3 投递生产接线、T4 持久复盘或 T5 调度收口。

定稿前 MCP 又读取了并行开发的 0627～0629：0627 已登记前台 enter/exit 接线、拿槽后二次复核及部分效果读回；0628 已登记 T4 job 存储和统一发送适配器；0629 已登记主动 outbox 真实入口工作树接线。这些新成果保留，不因本研究重做。0628/0629 仍明确 T4 真实窗口未接；0629 不代表所有回复/通知均已完成生产验收。本轮没有重跑其 490/0 报告，也未审计新业务实现。

新增实验 V1/V2/V3 单列 planned；当前优先完成 V1 的文档化资产核验，实际基准和语音实验另按项目执行计划开展。

## 8. 官方来源

以下链接是本轮阅读的固定源码版本；完整来源清单含获取成功/失败、大小与 SHA256，见 artifacts 下 source_manifest.json。探索中的两个不存在文件、最初 GitHub API 限流未作为结论证据。

- [vLLM 支持模型与 Gemma/LoRA 表](https://github.com/vllm-project/vllm/blob/b1401e0aa7eb7803c38e4d2d306cb2a16c8828a2/docs/models/supported_models.md)
- [vLLM Windows/WSL 安装边界](https://github.com/vllm-project/vllm/blob/b1401e0aa7eb7803c38e4d2d306cb2a16c8828a2/docs/getting_started/installation/gpu.md)
- [GGUF 实验状态与插件](https://github.com/vllm-project/vllm/blob/b1401e0aa7eb7803c38e4d2d306cb2a16c8828a2/docs/features/quantization/gguf.md)
- [前缀缓存](https://github.com/vllm-project/vllm/blob/b1401e0aa7eb7803c38e4d2d306cb2a16c8828a2/docs/features/automatic_prefix_caching.md)、[调度优化](https://github.com/vllm-project/vllm/blob/b1401e0aa7eb7803c38e4d2d306cb2a16c8828a2/docs/configuration/optimization.md)
- [Omni Qwen TTS recipe 与显存数据](https://github.com/vllm-project/vllm-omni/blob/6dd0d1f9310f7598b773c796b434c8000c2816ec/recipes/Qwen/Qwen3-TTS.md)
- [Omni Speech API：Streaming Text Input](https://github.com/vllm-project/vllm-omni/blob/6dd0d1f9310f7598b773c796b434c8000c2816ec/docs/serving/speech_api.md)
- [Omni 全双工端点与模型边界](https://github.com/vllm-project/vllm-omni/blob/6dd0d1f9310f7598b773c796b434c8000c2816ec/docs/serving/full_duplex_api.md)
- [Omni Realtime Duplex 协议与 Known Limitations](https://github.com/vllm-project/vllm-omni/blob/6dd0d1f9310f7598b773c796b434c8000c2816ec/docs/serving/realtime_duplex_api.md)
- [MiniCPM-o 部署与硬件布局](https://github.com/vllm-project/vllm-omni/blob/6dd0d1f9310f7598b773c796b434c8000c2816ec/recipes/OpenBMB/MiniCPM-o-4_5.md)
- [Qwen3-TTS README](https://github.com/QwenLM/Qwen3-TTS)（其中旧 Omni 离线说明已按服务端新文档校正）

台账记录：**0630**，已通过 MCP 追加；delivery_id=vllm-omni-review-20261005-v1。
