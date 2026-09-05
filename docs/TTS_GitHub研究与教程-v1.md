# Qwen3-TTS GitHub 研究与 YHLZ 适配教程 v1

状态：只读研究记录；未下载模型、未启动设备、未修改业务链路。

## 1. 来源与版本

本轮读取了以下公开仓库的 `main`/`v0.4.0` 内容（2026-08-31）：

- 官方仓库：[QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)，`main` 提交 `022e286b98fbec7e1e916cb940cdf532cd9f488e`。
- 加速仓库：[andimarafioti/faster-qwen3-tts](https://github.com/andimarafioti/faster-qwen3-tts)，`v0.4.0` 提交 `e2a215f61984c0e72a242f8dd72333338e7672f4`。
- 官方 Python 包 `qwen-tts==0.1.1` 使用 Transformers 4.57.3；加速包默认依赖 `qwen-tts-hf` 兼容发行版和 Transformers 5。

公开仓库可以直接读取，不需要在本机保存 GitHub 凭据。本记录只引用公开 README、源码和示例。

## 2. 模型能力矩阵

| 模型 | 官方定位 | 指令/情绪 | 官方 README 的 Streaming 标记 | YHLZ 首期判断 |
|---|---|---:|---:|---|
| `Qwen3-TTS-12Hz-0.6B-CustomVoice` | 9 个预置音色、10 种语言 | 不支持（配置和加速源码都会丢弃 `instruct`） | 是 | 资源优先的基线候选 |
| `Qwen3-TTS-12Hz-1.7B-CustomVoice` | 9 个预置音色、10 种语言 | 支持自然语言风格/情绪指令 | 是 | 需要实测显存后再决定 |
| `Qwen3-TTS-12Hz-0.6B/1.7B-Base` | 参考音频克隆 | Base 的 `instruct` 属实验能力 | 是 | 不作为首个 CustomVoice 探针 |
| `Qwen3-TTS-12Hz-1.7B-VoiceDesign` | 文字描述生成音色 | 支持 | 是 | 只作后续音色设计实验 |

官方 README 的“Streaming”是模型/产品能力描述；当前官方 Python 源码的 `Qwen3TTSModel` 仍只有整段 `generate_custom_voice`、`generate_voice_clone` 等接口，`non_streaming_mode=False` 的注释也明确说明它只改变文本输入方式，不等于音频输出流。不能把 README 表格直接当作本地 Python 真流式证据。

## 3. `faster-qwen3-tts` 的实际接口

`v0.4.0` 在 `FasterQwen3TTS` 中增加：

```python
generate_custom_voice_streaming(...) -> Generator[(audio_chunk, sample_rate, timing), None, None]
generate_voice_clone_streaming(...) -> Generator[(audio_chunk, sample_rate, timing), None, None]
generate_voice_design_streaming(...) -> Generator[(audio_chunk, sample_rate, timing), None, None]
```

- 音频输出为解码后的 NumPy 浮点数组，采样率由 tokenizer 推断，通常为 24 kHz。
- `chunk_size` 是 12 Hz codec steps，不是字节数；`8` 约等于 667 ms 音频，`12` 约等于 1 秒。
- 生成器是 pull-based：调用方不继续拉取时，生成也会停在当前步骤。官方示例使用持久 `StreamPlayer` 队列，不能对每个块重新调用一次 `sounddevice.play()`。
- 源码没有 YHLZ 所需的 `cancel()`、`wait_stopped()` 或外部取消事件。停止必须由 YHLZ 的 worker/进程边界负责，不能把“停止迭代”当作物理停止证据。
- 0.6B 模型会显式把 `instruct` 置为 `None`；因此传入情绪文本不会产生已认证的情绪控制。

仓库 README 给出的 RTX 4060 Windows 示例（0.6B CUDA Graph TTFA 约 413 ms、RTF 约 2.26；1.7B 约 460 ms、RTF 约 1.83）是上游基准，不是本机结果，必须重新测量。

## 4. 官方教程要点（仅作后续探针参考）

官方推荐在独立 Python 3.12 环境中安装，并从 Hugging Face 或 ModelScope 下载权重。中国大陆网络优先考虑 ModelScope：

```text
modelscope download --model Qwen/Qwen3-TTS-Tokenizer-12Hz --local_dir <model-dir>/Qwen3-TTS-Tokenizer-12Hz
modelscope download --model Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice --local_dir <model-dir>/Qwen3-TTS-12Hz-0.6B-CustomVoice
```

加速版本地流式调用的最小形态：

```python
import torch
from faster_qwen3_tts import FasterQwen3TTS

model = FasterQwen3TTS.from_pretrained(
    "<local-model-dir>",
    device="cuda",
    dtype=torch.bfloat16,
    local_files_only=True,
)

speaker = model.get_supported_speakers()[0]
for audio, sample_rate, timing in model.generate_custom_voice_streaming(
    text="用于隔离探针的固定短句。",
    language="Chinese",
    speaker=speaker,
    chunk_size=8,
):
    # 交给 TTSProviderPort normalizer，不直接写入生产播放队列。
    pass
```

上述教程不会在本阶段执行。模型路径、下载源、权重哈希和临时输出目录必须在真实探针前单独登记。

## 5. 对 YHLZ 的适配结论

1. 保留已经确定的 `TTSProviderPort`：Provider 只输出连续 PCM 和结构化事件，Kernel 不感知 Qwen 私有对象。
2. 用独立 worker 包装 `FasterQwen3TTS` 生成器；worker 内部用有界队列把“生成”和“播放/消费”解耦。
3. `cancel` 先停止消费并关闭生成器，再在 worker 边界取得退出/停止证据；超时就标记失败并阻止切换，不能伪造 `STOPPED`。
4. 首个探针使用 0.6B CustomVoice、固定音色和固定短文本，只验证 PCM、TTFA、RTF、错误和资源指标；不宣称情绪能力。
5. 若情绪/风格是硬需求，再以同一端口隔离比较 1.7B CustomVoice；必须先测显存峰值和长句稳定性，再决定是否替换主模型。
6. 通过无设备探针后才进入 B 设备测试；AEC、常驻麦克风和 C 认证继续遵守原台账门禁。

## 6. 许可证与风险

- 官方 Qwen3-TTS 仓库为 Apache-2.0；`faster-qwen3-tts` 为 MIT。实际交付仍需保留各自许可证和模型卡要求。
- `faster-qwen3-tts` 是独立社区实现，版本更新可能改变内部 API；生产环境必须锁定版本、提交或 wheel 哈希。
- `flash-attn` 是可选优化项；Windows 当前环境缺失时使用手工 PyTorch 路径，不影响接口探针，但会影响性能预算。
