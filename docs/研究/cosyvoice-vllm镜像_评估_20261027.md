# 那个 17 GiB 的 tar 是什么，以及里面能拿走什么

> 2026-10-27 · 利贞
> 文件：`C:\Users\ACE_WAN——PROJECT\新建文件夹\cosyvoice-vllm-full(1).tar`（18,748,762,112 B ≈ 17.46 GiB）
> 结论先说：**它不是源码包，是一个 Docker/OCI 镜像**；**跑不了**，但里面的 `server.py` 是 CX-O 项目写的 CosyVoice3 服务层，工程细节很值钱。

---

## 1. 它是什么

`oci-layout` + `blobs/sha256/*` + `manifest.json` 的结构 = `docker save` 出来的镜像。

| 项 | 值 |
|---|---|
| 镜像名 | `docker.io/library/cosyvoice-vllm-full:latest` |
| 架构 | linux/amd64 |
| 大小 | 17.46 GiB，**46 层** |
| 基底 | `vllm/vllm-openai:v0.26.0`（`VLLM_BUILD_COMMIT=ffd46bf…`） |
| CUDA | **13.0.2**（`NVIDIA_REQUIRE_CUDA=cuda>=13.0`，驱动 ≥575/580） |
| 模型 | `Fun-CosyVoice3-0.5B-2512`（打进镜像，`MODEL_DIR=/workspace/models/...`） |
| 服务 | `python /workspace/server.py --port 8094`，健康检查 `curl /health` |
| 关键参数 | `BF16=true`、`STREAM_HOP_LEN=10`、`FLOW_STEPS=3`、`VLLM=true` |

构建过程（镜像 history）里几条关键步骤：

```
uv pip install ./vllm-omni                       # 在 /app/vllm-omni 装 vllm-omni
COPY third_party/cosyvoice-official/ ./cosyvoice-official/
COPY docker/llm/cv3plugin/ ./cv3plugin/          # vLLM 插件
pip install -e ./cv3plugin
COPY docker/llm/cosyvoice_server.py /workspace/server.py
COPY . /workspace/models/Fun-CosyVoice3-0.5B-2512
```

**为什么跑不了**：Linux + Docker + CUDA ≥13 驱动 + vLLM；17.5 GB 镜像；目标硬件是数据中心卡。一张 4060 8GB 笔记本不在它的设计范围里。

---

## 2. 里面最值钱的东西：`server.py`

19,331 字节，已在 `research/cosy_extract/server/workspace/server.py` 解出。文件头注释直接写着 `--model_dir C:\CX-O\models\Fun-CosyVoice3-0.5B-2512`——**这是 CX-O 项目的产物**（我们之前研究过那个仓库）。

它是一个 OpenAI 兼容的 TTS 服务：`POST /v1/audio/speech`，支持零样本克隆（`ref_audio` + `ref_text`）、情感指令（`instructions` → `inference_instruct2`）、流式输出。

### 2.1 可以直接搬的五条经验

**① 首包 8.4 秒的坑（Windows + uvicorn）**

> "sync generator 在 Windows/uvicorn 下首个 send 有线程池+缓冲延迟（**实测 headers 首包 8.4s**），async 迭代直接在事件循环中执行，首包即时下发。"

他们把同步 generator 改成 `async def` + `await asyncio.sleep(0)` 让出事件循环。**我们也在 Windows + asyncio 上跑语音链路**——这条值得立刻自查：如果 TTS provider 是同步生成器套在 async 服务里，就是同一个 bug。

**② 流式 WAV 的写法**

先发 44 字节 WAV 头，长度写 `0xFFFFFFFF`（未知），之后逐段发 PCM16。客户端"跳过前 44 字节只吃 PCM"。简单、兼容、不依赖容器格式。

**③ 流式响度：固定增益，别逐块归一化**

> 非流式：峰值归一化到 **0.85**（-1.4 dBFS）。
> 流式：**固定增益 45.0**——CosyVoice3 原生 peak ≈0.01~0.02，×45 后 ≈0.45~0.90，块间一致、**无"呼吸效应"**。静音阈值 0.0001（低于不放大，防底噪抬升），最终硬 clamp ±0.98 防削波。

这是"逐块归一化会让音量随内容忽大忽小"的教科书式解法。

**④ 参考音频缓存**

用参考音频的 sha1 前 16 位命名 speaker（`spk_{hash}`），通过 `add_zero_shot_spk` 注册进 `frontend.spk2info`，重复的参考音频跳过 campplus + speech_tokenizer 的特征重提取。

**⑤ CosyVoice3 的两个硬适配**

- `prompt_text` 必须含 `<|endofprompt|>`（token 151646），服务层自动补 `"You are a helpful assistant.<|endofprompt|>"`，否则前端断言报错；
- 预热要用 **1 秒正弦波**做参考音频：静音提取的 speech token 太短，会让 flow 的 Conv 直接失败。

### 2.2 vLLM 集成的坑（`cv3plugin`）

插件只有两个文件，但解决了一个真问题：

> vLLM 0.26 的 EngineCore 是**独立进程**，主进程 `ModelRegistry.register_model` 不会传播。
> 通过 `vllm.general_plugins` entry point 让每个 vLLM 进程 import 本模块时完成注册。

```toml
[project.entry-points."vllm.general_plugins"]
cv3_vllm_plugin = "cv3_vllm_plugin:register"
```

另外 server 里注明：**流式输入文本（bistream）不支持 vllm，输出流式正常**——这也是个容易踩的边界。

---

## 3. 对我们的用法建议

| 想做的事 | 能不能用这个包 |
|---|---|
| 在元亨上直接跑 CosyVoice3 服务 | **不能**（Docker+CUDA13+vLLM+17.5GB） |
| 换更好的 TTS 音色/克隆 | 要单独装 CosyVoice3（0.5B 在 8GB 上跑得动，但要自己搭 Python 环境，不用这个镜像） |
| 改善语音链路的延迟 | **能**——第 2.1 ① 的 async generator 自查最值得做 |
| 改善音量一致性 | **能**——固定增益 + 静音阈值 + clamp 这套参数可直接照搬 |
| 参考 OpenAI 兼容 TTS 接口设计 | **能**——`/v1/audio/speech` 的字段（voice/ref_audio/ref_text/instructions/response_format/stream/speed）可直接对齐 |

**不建议**为了跑这个镜像去装 Docker + 折腾 CUDA 13——投入产出比不对。

---

## 4. 已解出的文件

```
research/cosy_extract/
├── 01366a30/workspace/cv3plugin/          # vLLM 插件源码（__init__.py + pyproject.toml）
├── 0484c6ab/…                             # egg-info（entry_points 等）
└── server/workspace/server.py             # 1,181 行的 CosyVoice3 服务层
```

原 tar 未改动。

---

*方法：直接解析 OCI 布局（`oci-layout`/`index.json`/`manifest.json`），按 manifest 的 blob 摘要定点读取，只解了 3 个小层，没有展开 17 GiB。*
