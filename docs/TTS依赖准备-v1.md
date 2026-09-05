# YHLZ TTS 依赖准备 v1

## 结论

Qwen3-TTS 是模型家族选择；目标链路的主运行时固定为 `faster-qwen3-tts==0.4.0`，使用 `Qwen3-TTS-12Hz-0.6B-CustomVoice` 模型。原因是 YHLZ 当前 CustomVoice 适配器调用 `FasterQwen3TTS.generate_custom_voice_streaming`，而官方 `qwen-tts==0.1.1` 的 `non_streaming_mode=False` 仍只是逐步送入文本，并不等于真正的音频输出流。

## 隔离原则

- 环境目录：`C:\Users\ACE_WAN——PROJECT\YHLZ\.venv`
- 不复用或修改 `C:\Users\ACE_WAN——PROJECT\.qwenpaw-venv`。
- 不把本配置追加到根目录的宽泛 `requirements.txt`。
- `qwen-tts` 与 `qwen-tts-hf` 不能在同一环境安装；官方包只作为后续对照环境候选。
- 模型权重、参考音频、麦克风、扬声器和 Edge 网络均不在依赖准备阶段启用。

## 锁定的关键组合

| 层 | 版本/来源 |
|---|---|
| Python | 3.12.10 |
| PyTorch | `2.7.1+cu128` |
| torchaudio | `2.7.1+cu128` |
| 主运行时 | `faster-qwen3-tts==0.4.0` |
| Qwen 兼容包 | `qwen-tts-hf==0.1.1.post1` |
| Transformers | `5.15.1` |
| B 回退 | `edge-tts==7.2.8` |

## 系统辅助依赖

- Python 包 `sox==1.5.0` 是 SoX 的调用封装，不包含 `sox.exe` 本体。
- 已在当前用户范围安装 SoX `14.4.2`（winget `ChrisBagwell.SoX`），并登记到用户 `PATH`；在新 shell 中可直接执行 `sox --version`。
- 12Hz CustomVoice 主路径不主动使用 25Hz/X-vector 归一化分支，但保留该可执行文件可避免导入告警并满足后续音频参考/克隆探针的前置条件。
- `flash-attn` 未安装。它是可选的 CUDA 加速项，在 Windows/PyTorch 2.7.1 下不作为本轮硬依赖；缺失时 faster provider 会回退到手工 PyTorch 路径。

完整解析版本清单见 `requirements-tts-primary.lock.txt`。锁文件只描述 Python 环境，SoX 可执行文件版本和安装范围以本节为准。

## 验证顺序

1. `pip install -r requirements-tts-primary.txt`。
2. `pip check`，确认没有混入官方 `qwen-tts`。
3. 仅导入 `torch`、`torchaudio`、`faster_qwen3_tts`、`qwen_tts`、`edge_tts`，读取 CUDA 可见性。
4. 记录 `pip freeze` 锁文件和安装日志。
5. 依赖通过不代表模型可用，也不代表 B/C、AEC、情绪、TTFA、RTF 或连续 PCM 已认证；这些必须在单独的模型/设备测试阶段完成。
