# 元亨 · 本地部署（llama.cpp CUDA + 多模态 + LoRA）

> 已验证：**保留多模态（不裁塔）**、**CUDA 后端 33.1 t/s**（Vulkan 仅 3 t/s）。

## 一、目录与资产

| 路径 | 内容 |
|---|---|
| `models/llama-cuda/` | **CUDA 版** llama.cpp（b10991，含 `llama-server.exe` / `llama-cli.exe` / `llama-quantize.exe`） |
| `models/llama-cuda/src/llama.cpp-b10991/` | llama.cpp 源码（GGUF 转换脚本 `conversion/`、`gguf-py/`） |
| `models/gemma4-gguf/gemma-4-E4B_q4_0-it.gguf` | 基座 GGUF（**QAT-Q4_0**，4.80 GB） |
| `models/gemma4-gguf/gemma-4-E4B-it-mmproj.gguf` | 多模态投影器（0.92 GB，**视觉+音频**） |
| `models/gguf-lora/yuanheng-lora.gguf` | （待生成）元亨 LoRA |

## 二、起服务

```powershell
# 完整（多模态 + 人格）
powershell -File dist\local_serve\serve_yuanheng.ps1

# 先验基座（不挂 LoRA）
powershell -File dist\local_serve\serve_yuanheng.ps1 -NoLora
```
默认 `127.0.0.1:8080`，OpenAI 兼容：`POST /v1/chat/completions`。

**必须 `-rea off`**（已在脚本里）：Gemma4 默认思考模式会输出 `<|channel>thought`，毁掉人设。

## 三、转换 LoRA → GGUF

```bash
bash dist/local_serve/convert.sh lora  <peft_adapter_dir>  models/gguf-lora/yuanheng-lora.gguf
```

## 四、显存与实测（RTX 4060 Laptop 8GB）

| 项 | 值 |
|---|---|
| 桌面占用后空闲 | ~6.9 GB |
| 基座 + mmproj | ~5.95 GB |
| 生成速度（CUDA，`-c 2048`） | **33.1 t/s** |
| Prompt 速度 | 27.5 t/s |

> ⚠️ 启动前确认没有残留 `llama-server` 进程（会各占一份显存）。
> `Get-Process llama-server | Stop-Process -Force`

## 五、多模态实测结论（b10991 + QAT-Q4 + mmproj）

| 能力 | 结果 |
|---|---|
| 文本 | ✅ |
| 视觉 | ✅（正确描述图片） |
| **音频** | ✅（**转写中文语音成功**） |
| `llama-server` 声明 | `modalities: text, vision, audio, video` |

## 六、接项目
把 provider 的 `base_url` 指到 `http://127.0.0.1:8080/v1`、模型名任意（如 `yuanheng`）即可。
（现用 `backend/llm_vllm_provider.py`，默认 `127.0.0.1:8765`。）
