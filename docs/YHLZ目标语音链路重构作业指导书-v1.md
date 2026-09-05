# YHLZ 目标语音链路重构作业指导书 v1

> 文档状态：执行版 v1.0（先验证，后接入）  
> 编制时间：2026-08-31（Asia/Shanghai）  
> 适用项目：`C:\Users\ACE_WAN——PROJECT\YHLZ`  
> 目标：在不改写业务数据、`memory`、声音缓存、WebUI 和现有入口行为的前提下，把目标语音链路逐步收敛到唯一运行时边界。

## 1. 执行原则

1. 先建立证据，再改变调用路径；没有真实证据的能力一律标为“未认证”。
2. 先隔离 Provider，再重构组装根；不在生产入口内试验模型。
3. 只允许一条目标链路拥有 turn、取消、事件和媒体交接权。
4. 旧模块先保留为兼容适配器，确认回放和回滚后才允许退出。
5. 每个阶段都有独立停止点、可复核输出和回滚点。
6. 本作业不迁移、不清理、不重写现有 `memory`、数据库、声音缓存或对话备份。

## 2. 当前边界和基线

### 2.1 目标链路组件

```text
组合根（待建立）
  -> SessionKernel
  -> TargetVoiceChain
  -> ASRBridge + MediaAdapter
  -> TTSProviderPort + PersistentTTSProvider
  -> 播放端口（后续）
```

当前 `TargetVoiceChain`、`TargetVoiceRuntime`、`SessionKernel`、`ASRBridge`、`MediaAdapter`、`TTSProviderPort` 和 Worker 已有标准库契约测试，但尚未替代 `backend/main.py` 中的旧全局链路。

### 2.2 现状风险

- `backend/main.py`、`conversation_manager.py`、`conversation_controller.py` 各自保留部分状态/播放职责。
- `backend/tts_engine.py`、`backend/tts/` 和 `backend/voice_identity/adapter/` 存在并行 TTS 接口。
- 旧入口直接调用 `tts_engine.synthesize` / `stream_synthesize_text`，绕过目标端口。
- 真实 Qwen、设备、AEC、Edge、TTFA/RTF 和显存证据尚未建立。

## 3. 固定决策

| 项目 | 固定值 |
|---|---|
| 主模型 | `Qwen3-TTS-12Hz-0.6B-CustomVoice` |
| 主运行时 | `faster-qwen3-tts==0.4.0` + `qwen-tts-hf==0.1.1.post1` |
| 模型来源 | ModelScope（失败时记录，不静默切源） |
| 模型目录 | `C:\Users\ACE_WAN——PROJECT\YHLZ\models\qwen3-tts` |
| 默认音色 | `Vivian`（以模型实际枚举为准） |
| 音频契约 | 24 kHz、单声道、`s16le` PCM；播放侧 20 ms/480 samples |
| 文本契约 | `push_text(delta)` + `commit_text()` |
| 取消契约 | `cancel(reason)` + `wait_stopped(timeout_s)` 或 worker 退出证据 |
| 回退 | Edge 仅作为下一句受控 B 回退/对照，不并行、不预热 |
| 设备 | 首轮只读枚举；获准后采用系统默认输入/输出做有界短测 |
| 保护预算 | 单项 5 s、总计 60 s、停止观察 3 s；不把配置当认证结果 |

## 4. 分阶段作业

### 阶段 A：基线登记（必须先做）

**动作**

1. 记录 `git status`、`git log -1`、Python、CUDA、关键包版本和可用空间。
2. 确认模型目录不在 `memory` 或“记忆及其他备份”目录内。
3. 记录当前运行进程，但不强制终止用户进程。
4. 将本阶段结果追加到 `docs/上下文台账.md`。

**通过条件**：基线可复核，回滚提交/工作树位置明确。  
**停止条件**：路径不明确、磁盘不足、GPU 被其他推理任务占用且无法确认。  
**回滚点**：不产生业务代码或数据变更。

### 阶段 B：模型和 Provider 隔离探针

**动作**

1. 从 ModelScope 下载 Tokenizer 和 0.6B CustomVoice 到固定模型目录。
2. 在 `.venv` 中以 `local_files_only=True` 加载模型；不接入口、不接 WebUI、不打开设备。
3. 以固定中文短句、`Vivian` 运行一次正常生成和一次取消/停止探针。
4. 将模型输出先交给端口 normalizer，验证 PCM 格式、序号、连续性、`DONE` 时序。
5. 记录 TTFA、总时长、RTF、CPU/显存峰值、错误码和 worker 停止证据。

**通过条件**：模型可加载；至少一个有效 PCM 块；采样率/通道/格式符合契约；`DONE` 在 commit 后；取消后取得停止证据；无旧 epoch 输出泄漏。  
**停止条件**：模型下载校验失败、OOM、生成器异常、取消无停止证据、PCM 不连续。  
**回滚点**：删除本阶段生成的临时探针输出和模型缓存（仅在明确需要时）；不触碰项目数据。

### 阶段 C：目标端口适配（首个代码重构）

**动作**

1. 新增独立 Qwen Provider adapter/worker，不改旧 `backend/tts/` 实现。
2. adapter 只负责 Qwen 私有 API 到 `TTSProviderPort` 的转换；模型对象不向 Kernel 泄漏。
3. worker 负责生成器关闭、取消、停止观察、代际和资源快照。
4. 为正常结束、空文本、生成异常、重复/缺失 chunk、取消超时补充契约测试。

**通过条件**：隔离测试全通过，真实探针证据可复现。  
**停止条件**：需要修改数据结构、memory 或入口才能通过；此时回到设计评审。

### 阶段 D：组合根/运行时门面

**动作**

1. 建立一个应用组合根，唯一创建 `SessionKernel`、链路、Provider 和媒体适配器。
2. 先提供显式门面 API，旧入口通过兼容适配器调用，不做大面积重写 `main.py`。
3. 将 `conversation_manager` / `conversation_controller` 的核心状态映射到 Kernel；禁止第二套 turn 所有权。
4. 以特征测试和回放样本逐端点切换，单次只切换一个入口。

**通过条件**：文本 Golden Path 和一条语音 Golden Path 都只经过同一 Kernel；中断、旧 chunk 丢弃、正常提交和错误日志可观察。  
**停止条件**：出现双写、双播、旧 turn 泄漏或回滚困难。

### 阶段 E：设备 B 基线和 C 评估

**动作**

1. 先只读枚举设备，再按系统默认路由做短时输入/输出测试。
2. 记录 VAD、ASR、TTS、播放、AEC、取消和资源指标。
3. 无 AEC 时明确降级 B；不得把设备枚举或配置阈值当作 C。
4. Edge 只在主链失败后的下一句或空闲对照中测试。

**通过条件**：B 证据完整；若要报告 C，所有 C 检查和停止收尾均通过。  
**停止条件**：回声失控、设备独占冲突、常驻录音无法停止、资源超过阈值。

### 阶段 F：入口收敛和冻结交付

只有阶段 A-E 全部有证据后才执行：

- `start.bat` 成为唯一正式入口；
- 健康检查、异常检查、错误码和资源指标纳入启动流程；
- WebUI 由其负责人按同一门面接入；
- 外围模块按重要性降级或隔离；
- 生成冻结清单、回滚手册和版本标签。

## 5. 验收记录模板

每次探针/迁移必须记录：

```text
日期/操作者：
阶段与变更编号：
基线提交/工作树：
Provider/模型/来源/权重目录：
设备与路由：
命令与结果：
TTFA/RTF/PCM/停止证据：
错误码与降级：
未解决风险：
回滚点：
是否触碰 memory/业务数据：否/是（说明）
```

## 6. 本轮执行范围

本轮执行阶段 A 和 B；阶段 C 只有在 B 的真实证据通过后才开始。默认不打开麦克风/扬声器，不启动常驻服务，不修改 WebUI、入口、数据库、业务数据、声音缓存或 `memory`。所有探针输出写入项目外的临时目录或明确的 `artifacts/tts_probe`，不写入记忆目录。

### 执行补充 C.1：独立进程 Provider transport 验真

阶段 B 的模型生成与线程适配证据通过后，先完成本项，才允许考虑设备 B 短测。

1. 用 Windows `spawn` 启动单一 Qwen 子进程；父进程只持有 `TTSProviderPort` 代理，不加载模型。
2. 正常路径必须验证 `READY -> PCM_CHUNK... -> DONE`、24 kHz/单声道/`s16le`、序号连续、TTFA、RTF、显存快照和严格空闲。
3. 取消路径必须验证 `READY -> PCM_CHUNK -> STOPPED`、`wait_stopped`、无 `DONE`、无旧 epoch 事件，以及子进程可控退出。
4. 命令必须从真实 `.py` 文件或 `-m backend.tts_qwen_adapter_probe` 运行；不得从标准输入执行，以免 Windows `spawn` 失去可导入主模块。
5. 保持离线标志；不得打开麦克风、扬声器、WebUI、`main.py` 或写入 `memory`、业务数据和声音缓存。

**通过条件**：进程启动、正常事件、协议级取消/停止、严格空闲和有界退出均取得独立证据。  
**停止条件**：启动超时、IPC 断连、事件丢失/乱序、取消后无停止证据、子进程无法退出或超出资源预算。  
**回滚点**：仅删除该轮 `artifacts/tts_probe/<run-id>`；不修改运行时入口和持久化数据。

### 执行补充 D.1：播放端口接入与有界输出短测

1. 先以 fake `OutputStream` 验证 24 kHz `s16le` PCM、预缓冲、背压、`finish()` 物理排空、`interrupt()` 与 `wait_stopped()`；正常 `AUDIO_DONE` 必须晚于 `finish()` 返回。
2. `TargetVoiceRuntime.start()` 必须显式打开播放端口；关闭顺序固定为停止 turn → 停止/关闭播放流 → 同步播放空闲状态 → `wait_idle_stopped()` → 回收 Provider。
3. 仅在端口与目标链路套件全部通过后，可对已核验的系统输出端点执行一次固定短句输出测试；不打开麦克风、不保存 PCM、不导入 `main.py`，单次 turn 上限 45 s。
4. 记录设备 ID、格式预检、端口事件类别、队列/错误指标、Provider 首块与资源指标、关闭与子进程收尾；不能依据“流已打开”或“回调排空”报告 B/C。

**通过条件**：目标端口的契约测试通过；真实输出端口可打开、正常回合在物理排空后完成、无端口错误、关闭后无遗留 Provider 进程。  
**停止条件**：设备格式不支持、PortAudio/队列错误、排空超时、GPU OOM、Provider 停止未确认或超过保护预算。  
**回滚点**：仅保留 `artifacts/tts_probe/<run-id>/summary.json`；不写 PCM、声音缓存、业务数据或 `memory`。

### 执行补充 E.1：输入 VAD/ASR 端口收敛与 B 基线

本补充在真实 TTS 到扬声器的短测通过后执行。它只补齐输入侧的可观察边界，不接生产入口，也不把设备可见性误写成全双工认证。

1. 先执行只读预检：VAD/ASR 的处理格式必须是 `16 kHz / 1 声道 / float32`。若端点原生支持该格式，可直接捕获；若经过明确预检只支持原生 `48 kHz / 1 声道 / float32`，只允许经过本补充 E.2 的有状态重采样器进入 16 kHz 处理域。`DeviceProbe` 的最大通道数不是实际捕获通道；目标 `DeviceDescriptor` 必须明确选择单声道，超出设备能力即失败关闭。
2. VAD 必须独立实现 `TargetVADProvider`：使用 CPU `onnxruntime`，仅从本地已核验的 `models/voice/vad/silero_vad.onnx` 加载。对应来源、许可证、版本、SHA-256、输入/输出契约写入 `assets/voice/vad/silero-vad-v6.2.1.manifest.json`；运行时只验证，不自动联网下载。
3. VAD 输入为 `float32` 单声道 16 kHz；每个 512-sample 模型窗口保留 64-sample 上下文和 LSTM state。门限使用显式 onset/offset 与最小连续语音、静音窗口，输出只为当前帧的布尔活动状态；日志、健康与台账只能保存概率汇总和计数，不保存原始样本。
4. VAD 生命周期必须提供 `start()`、`detect_speech()`、`reset_stream()`、`stop()`、`wait_stopped(timeout_s)` 和 `health()`。格式错误、资产校验失败、ONNX 推理失败或停止未确认均应给出稳定错误码，并令媒体链路降级/失败关闭。
5. ASR 不复用 `backend/asr_engine.py`、`backend/asr_engine_qwen.py` 或其全局对象。先固定 `ASRProviderPort`：`transcribe(segment, signal)`、`interrupt(reason)`、`wait_stopped(timeout_s)`、`health()`；无已核验本地模型时必须报告不可用，禁止 Mock 文本、静默网络回退或把模型下载隐含在首个转写中。
6. 先以 fake ONNX 会话、合成帧和取消信号完成契约测试，再下载并校验单一 VAD ONNX 资产。VAD 资产通过后，只允许一次上限 5 秒、无音频落盘的输入短测：记录设备 ID、格式、帧数、VAD 计数、错误码、停止耗时和健康快照；不得保存 PCM/WAV/转写文本。
7. 通过输入短测只能得到“持续采集/VAD 输入路径可工作”的 B 证据。没有真实 ASR、播放与输入并发、回声处理和验收执行器的逐项实测时，绝不能标记 C，也不能冻结或切换 `start.bat`。

**通过条件**：VAD 资产的来源与 SHA-256 可复核；所有 VAD/ASR 端口契约测试通过；输入短测可启动、停止、无原始音频落盘，且 `wait_stopped()` 有证据。  
**停止条件**：资产哈希不匹配、输入格式不支持、ONNX 推理/停止异常、设备短测超过 5 秒、检测到任何写入 `memory`/声音缓存/业务数据，或 ASR 需要未确认的模型下载。  
**回滚点**：仅删除本轮 `models/voice/vad/silero_vad.onnx` 和相应探针摘要（如明确需要）；保留 manifest、测试、ADR 和台账以保持可审计性。

### 执行补充 E.2：原生 48 kHz 捕获到 16 kHz 处理域

仅在系统默认 MME 输入端点无法真实打开、且同一物理输入的明确原生主机端点（例如 WASAPI 或 DirectSound）通过原生 48 kHz 格式预检并能真实打开时使用。本补充不改变 VAD/ASR 的逻辑音频契约，也不把 48 kHz 捕获本身当作 B/C 认证。

1. 捕获端显式使用已核验的原生主机设备 ID、`48 kHz / 1 声道 / float32` 和 100 ms（4,800 samples）帧；不依据设备名称推断路由或 AEC 能力。
2. `TargetInputResampler` 是唯一允许的格式桥接：它使用 CPU 多相低通/抽取，保持有限滤波状态与相位，把连续 48 kHz 单声道帧转换为连续 16 kHz 单声道 float32 帧。它必须公开 capture/processing 采样率、输入/输出 samples、调用次数和异常，且不保存原始音频。
3. `MediaAdapter` 必须在 AEC（若有）之后、VAD/分段/ASR 之前调用重采样器；传递下游的 `ProcessedAudioFrame` 元数据必须改为 16 kHz，捕获队列的时长仍以原始时间轴计算。无重采样器、格式不符、滤波异常或输出格式异常均 fail-closed 并记录 `MEDIA-RESAMPLER-*`。
4. 先完成合成 48 kHz 帧的长度、相位连续性、单声道、元数据和错误测试；再进行一次上限 5 秒、无音频落盘的 WASAPI 输入短测。它的通过只表示“原生捕获到 VAD 处理域”可运行，不能替代真实 ASR、AEC、并发打断或 C 验收。

**通过条件**：48 kHz 端点预检/打开成功；每个 4,800-sample 捕获帧得到 1,600-sample 16 kHz 处理帧；VAD 无格式/推理错误；停止和健康快照可观察。  
**停止条件**：所选原生主机流无法打开、重采样连续性/格式错误、VAD 失败、队列排空超时或任何持久化音频写入。  
**回滚点**：移除 `TargetInputResampler` 对实时 probe 的注入；不触碰模型、数据、声音缓存、`memory` 或入口。

### 执行补充 E.3：会话化流式 ASR Provider 与 VAD 闭环

本补充落实 ADR-005。它只替换目标链路中的 ASR 边界，不改变旧入口、业务数据、声音缓存或 `memory`；真实设备输入未验证前，所有结论都只能是无设备链路证据。

1. 采用 `StreamingASRProviderPort`：`open_stream(stream_id, generation)`、`push_audio(...)`、`finish_stream(...)`、`interrupt(reason)`、`wait_stopped(timeout_s)`、`stop(reason)` 与脱敏 `health()`。旧 `ASRProviderPort.transcribe(segment, signal)` 只保留给既有隔离测试，不能代替流式认证。
2. 主 Provider 固定为本地 CPU `sherpa-onnx==1.13.6` 和已校验的官方双语 Zipformer 资产。输入必须是连续 `16 kHz / 单声道 / float32` PCM；运行时逐文件验证 manifest，资源预检要求至少 2 GiB 可用物理内存，禁止隐式联网下载。
3. `StreamingASRBridge` 在 VAD 首个活动帧时先登记会话、再打开 ASR stream，并将有限预滚和后续帧以有界队列送入单工作者。队列容量为 2 s，默认 100 ms 块、200 ms partial 节流、2 个解码线程；队列溢出、格式变化、过期 generation、模型错误或取消未确认均 fail-closed 并生成稳定错误码。
4. partial 仅能作为短生命周期 `ASR_PARTIAL` 事件存在，不能进入 WakeWordGate、SessionKernel、reasoner、`memory`、持久日志或 WebUI 的业务历史。仅 VAD 结束、`finish_stream()` 取得的 final 文本才可进入既有“元亨”唤醒门控；未命中时不得创建回合。
5. 关闭/插话时必须先阻止新帧、二次幂等 `interrupt()` 活跃 stream、等待 Provider 停止证据，再释放 bridge/Provider。停止超时、worker 未退出或仍有活跃 stream 时不得切换入口、重启核心链路或冻结。
6. 验证顺序固定为：单 Provider 正常流、单 Provider 取消、固定样本 VAD、固定样本 `VAD -> StreamingASRBridge -> final 门控`，最后才允许在可实际打开的输入端点进行一次不落盘、上限 5 秒的输入短测。固定样本可来自上游模型包，但摘要只能保存哈希/长度/计数/时延/资源和错误码。

**通过条件**：本地资产、依赖和资源门禁通过；正常流得到连续 partial/final 和停止证据；取消无 final 且 `wait_stopped()` 成功；VAD 到 ASR 贯通无背压/错误且 partial 未越界。  
**停止条件**：资产哈希不匹配、资源不足、连续 PCM 格式错误、队列溢出、取消未确认，或探针尝试保存用户音频/转写。  
**回滚点**：移除该 Provider 对组合根的注入并保留 manifest、ADR、测试和台账；不删除业务数据、声音缓存或 `memory`。

## 7. 失败处置

- 依赖/模型失败：保留错误码和版本，停止，不自动换模型。
- OOM：停止当前探针，记录峰值和其他 GPU 进程，不强杀进程。
- Provider 取消失败：标记 `VOICE-TTS-WORKER-STOP-UNCONFIRMED`，禁止切换和冻结。
- 数据或入口意外被触碰：立即停止，记录路径和时间，等待人工确认。

## 8. 参考文件

- `docs/TTSProviderPort-v1_目标链路设计.md`
- `docs/TTSWorkerLifecycle-v1_目标链路设计.md`
- `docs/TTS_GitHub研究与教程-v1.md`
- `docs/YHLZ2.0_架构收敛与全双工_工程计划书_初稿.md`
- `docs/上下文台账.md`
