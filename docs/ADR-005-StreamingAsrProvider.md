# ADR-005: 流式 ASR Provider 与 VAD 协作边界

## 状态

已接受；会话化 Provider、Bridge 和无设备固定样本验真已完成。真实输入端点、输入输出并发、AEC、B/C 认证与冻结仍未完成。该决策不授权切换 `main.py`、`start.bat` 或 WebUI。

## 结论

1. 继续使用现有 `TargetVADProvider`：Silero v6.2.1、CPU ONNX Runtime、16 kHz 单声道 float32、512-sample 窗口和本地校验资产。没有真人声/实际设备证据前，不调高或调低 VAD 门限，也不改写 VAD 资产。
2. ASR 主 Provider 选用 `sherpa-onnx==1.13.6` 的 `OnlineRecognizer`，模型候选固定为官方 GitHub Release 的 `sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20`。该方案提供原生连续 PCM 的 `create_stream -> accept_waveform -> is_ready/decode_stream -> get_result` 接口，可在 CPU 上运行，从而为 Qwen TTS 保留 GPU。
3. `ASRProviderPort` 不再只描述完整 `SpeechSegment` 的 `transcribe`。新增的流式扩展必须提供 `open_stream`、`push_audio`、`finish_stream`、`interrupt`、`wait_stopped`、`stop` 与脱敏 `health`。每个调用都带 stream id 与 media generation；旧的整段 Port 只保留给现有隔离测试，不得伪称为流式实现。
4. 新 `StreamingASRBridge` 在首个 `speech=true` 帧建立会话，带有限预滚把后续 16 kHz PCM 逐帧送入 Provider，并只把 `partial` 送到短生命周期事件通道。它不得将 partial 文本传入 WakeWordGate、SessionKernel、reasoner、memory 或持久日志。仅 VAD 结束后的 `final` 文本可进入既有唤醒/回合链路。
5. ASR 计算从媒体回调解耦，使用有界队列和单工作者；队列超限、流格式变化、重复/过期 generation、模型错误或取消未确认均 fail-closed 并生成稳定错误码。`interrupt` 仅允许等待当前有界解码步骤结束，不允许强杀用户进程；超过停止预算即禁止重叠会话。
6. 初始配置采用 CPU、`num_threads=2`、16 kHz、单声道、100 ms 输入块、200 ms partial 发布节流和 2 s ASR 队列上限。线程数、partial 节流和队列上限都只是待测初值；必须根据 RTF、首个 partial、取消延迟、CPU/RAM 峰值和实际输入帧再调整。

## 上游比对依据

| 候选 | 原生流式事实 | 适配本机全双工的结论 |
| --- | --- | --- |
| `QwenLM/Qwen3-ASR` | 官方 README 说明 streaming 仅支持 vLLM；示例使用 `gpu_memory_utilization=0.8`。 | 暂不作为主链：本机 RTX 4060 Laptop 为 8 GB，Qwen TTS 已测约 2.4 GB，加上当前 GPU 占用无法可靠并发。保留为未来离线质量对照。 |
| `modelscope/FunASR` | 官方 README 给出 `paraformer-zh-streaming` 的 600 ms 分块、cache 和 final 标志。 | 可作为后备评审对象，但 220M PyTorch 路径会增加 GPU/内存竞争和依赖面，不作为首个全双工基础。 |
| `k2-fsa/sherpa-onnx` | 官方 Python 示例给出 OnlineRecognizer 的连续 `accept_waveform`、就绪检查、解码和结果读取；发布 Windows CPython 3.12 wheel。 | 选为主链：CPU 原生在线识别、Windows/Python 3.12 可装、与 Qwen TTS GPU 隔离。 |

## 资产与运行边界

- 模型只能预先下载至 `models/voice/asr`，来源 URL、归档和运行文件 SHA-256、许可和接口版本记录在 `assets/voice/asr` manifest；运行时绝不按模型名隐式联网下载。
- 下载、解包和安装不能触碰 `memory`、数据库、业务数据、声音缓存、旧 ASR 引擎、入口或 WebUI。
- 无设备测试只可使用上游随模型附带的固定测试样本或合成静音，并只记录文本长度/哈希、计数、时延、资源和错误码；不保存音频、PCM、WAV、用户转写或 partial/final 原文。
- 当前空闲内存约 1.3 GB。安装/下载可以继续；真实模型加载必须先经过资源预检，内存不足时记录 `ASR-RESOURCE-BUDGET` 并停止，不结束任何用户进程。

## 后果

该选择先保证持续 PCM、增量结果、取消和 GPU 隔离，再以实测决定准确率是否足够。若以后以 Qwen3-ASR 或 FunASR 替换，只替换 Provider 层和单独资产 manifest；流式端口、VAD、媒体、唤醒、数据和 `memory` 边界不变。
