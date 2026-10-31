# GPT-SoVITS v5 研究：原理 / 工作流 / 生态 / 价值
## ——兼论「元亨语音包」为什么性能不好、v5 能不能治

- 时间：2026-10-18
- 触发：老爹「研究 GPT-SoVITS-v5 原理、工作流、生态、价值；现在的元亨语音包性能不太好」
- 证据等级标注：**[实测]** 本机测得 ｜ **[代码]** 上游源码/配置 ｜ **[官方]** README/Changelog/模型卡 ｜ **[推算]** 由结构推得，待实测
- 未做：未安装 v5、未下载权重、未跑任何 TTS、未改生产配置（按台账 0124：真机发声类测试先问老爹）
- **口径更正（2026-10-18 20:17）**：老爹所指的「元亨语音包」是**翻唱嗓**，不是 TTS 克隆。本文第 5 节的 TTS 诊断仍然成立（对 `/tts` 链路有效），但**翻唱结论以后续专项报告《翻唱嗓诊断_GPT-SoVITS定位与升级路线_20261018.md》为准**；GPT-SoVITS 是 TTS，不能替代 SVC，翻唱里它只能做「音色母版/语料工厂」。

---

## 0. 一页纸结论

1. **v5 是真的，但很新**：2026-10-05 发布，代码在 `cuda_graph_accel_v5` 分支，**main 还没合并**（main 的 `tts_infer.yaml` 里没有 v5 条目）[代码]。三条正式卖点：零样本音色相似度大幅提升、新 vocoder 压高频镜像/混叠、CUDA Graph + FlashAttention 加速 [官方]。
2. **v5 只换了「声学模型 + 声码器」，没换 GPT**：`gsv-v5-pretrained` 里只有 `s2Gv5dev.pth`、`s2Gv5turbo.pth`、`vocoder.pth`，**没有 S1**（GPT）[官方/代码]。所以**重复、漏字、语调飘这类 GPT 侧毛病，v5 不会治**。
3. **v5 的两种形态**：`v5dev`＝32 步 + CFG 1.30（质量档）；`v5turbo`＝4 步 + CFG 0（速度档）。Euler 步数只允许 4/8/16/32，CFG 限制在 0–2 [代码]。
4. **元亨语音包的病根不在引擎，在「参考音」**：现役是 `Qwen3-TTS 0.6B-Base` 零样本克隆 `refs/xiaoyi/ref01.wav`——**7.20 秒、24 kHz、Edge 合成音**[实测]。等于「克隆的克隆」，频率上限 12 kHz。换 v5 只会更像小艺，不会更像人。
5. **8 GB 是硬天花板**：Gemma 常驻时实测 **5313 / 8188 MiB 已用，剩约 2.8 GB**[实测]。Qwen3 0.6B（约 2 GB）刚好塞得下，GPT-SoVITS（推算 3–4.5 GB）塞不下。**v5 在本机的定位应是「高质量旁路」，不是「替换 Qwen3 常驻」**。
6. **最划算的顺序不是「升 v5」**：先换参考音（P1）→ 再拿 v5 零样本 A/B（P2）→ 语料去 Edge 化后再微调（P3）。若坚持用现有 2 小时 Edge 语料微调，**v2ProPlus 可能比 v5 更稳**（官方明说 v1/v2/v2Pro 抗低质数据，v3/v4 不行）。

---

## 1. 原理

### 1.1 一句话

GPT-SoVITS＝**「GPT 负责怎么说」+「SoVITS 负责像谁说」+「vocoder 负责好不好听」** 的两段式少样本 TTS：先用 5 秒参考音做零样本，或 1 分钟数据做微调，再用参考音把音色「贴」到合成结果上。

### 1.2 结构

```text
文本
 ├─ 文本前端：zh_normalization（数字/单位/符号）→ LangSegmenter（中英日混排切分）
 │            → jieba 分词 + G2PW（多音字，ONNX/GPU）→ 音素序列
 ├─ BERT（chinese-roberta-wwm-ext-large）→ 文本语义特征 ─┐
 │                                                      ▼
 │                                            ┌──────────────────┐
 └───────────────────────────────────────────▶│ S1  GPT（AR）     │  自回归预测「语义 token」
                                              │ 逐 token 生成      │  25 Hz 帧率
                                              └────────┬─────────┘
                                                       │ semantic tokens
  参考音 ──CNHuBERT──▶ 语义特征 ───────────────────────┤
          └─ERES2NetV2─▶ 说话人向量(20480 维) ─────────┤
                                                       ▼
                                              ┌──────────────────┐
                                              │ S2  SoVITS        │  语义 token → mel
                                              │ v5: CFM + DiT     │  Euler 4/8/16/32 步
                                              └────────┬─────────┘
                                                       ▼
                                              ┌──────────────────┐
                                              │ vocoder（BigVGAN）│  mel → 波形
                                              └──────────────────┘
```

### 1.3 各模块职责

| 模块 | 干什么 | 关键事实 |
|---|---|---|
| 文本前端 | 把汉字变成「怎么读」 | G2PW 管多音字（`行/长/重`），`zh_normalization` 管数字单位，LangSegmenter 管中英日混排 [代码] |
| BERT | 给 GPT 提供上下文语义 | 中文用 `chinese-roberta-wwm-ext-large`；**推理时要加载，约占 0.6–1.3 GB 显存** [代码/推算] |
| S1 GPT | 决定停顿、语调、长短 | 自回归、25 Hz 语义 token；**v5 完全没动它** [代码] |
| CNHuBERT | 把参考音变成「内容特征」 | 25 Hz；与文本特征对齐，是 SoVITS 的输入之一 [代码] |
| SV（v2Pro 起） | 把参考音变成「音色向量」 | ERES2NetV2，baseWidth 24 / scale 4 / expansion 4，**20480 维**，16 kHz fbank 80 [代码] |
| S2 SoVITS | 语义 + 音色 → mel | v1/v2/v2Pro 是 VITS；v3/v4/v5 是 CFM（flow matching）+ DiT [代码] |
| vocoder | mel → 波形 | v5 换了新 vocoder，专治高频镜像/混叠 [官方] |

### 1.4 v5 到底改了什么（代码级）

| 改动 | 证据 | 对听感/速度的影响 |
|---|---|---|
| 新 S2：`CFMV5` | `GPT_SoVITS/module/models_v5.py`、`v5_inference.py` | 音色相似度、高频质感 |
| 两种采样档 | `v5dev`：32 步 + CFG 1.30；`v5turbo`：4 步 + CFG 0；步数 ∈ {4,8,16,32}，CFG ∈ [0,2] | turbo 约 1/16 的计算量（64→4 次网络前向）[推算] |
| 滚动窗口长句合成 | 参考 500 帧、单块目标 ≤640 帧、总块 1000 帧、回滚尾部 32 帧 | 长句不爆显存、语调连续；**天然适合流式** |
| 新 vocoder | `gsv-v5-pretrained/vocoder.pth`（独立权重） | 高频不「镜像」，听感不毛刺 |
| AR 加速 `Accel/` | `Accel/PyTorch/AR/backends/{flash_attn_varlen_cuda_graph, torch_static_cuda_graph, torch_varlen}.py`、`tools/acceleration.py` | CUDA Graph + FlashAttention 2.8.3；不支持时自动退回普通 AR |
| 量化/导出 | `Accel/PyTorch/AR/quantization.py`、`export.py` | 预留低比特与静态图路线 |

> 注意：`Accel` 加速的是 **AR（GPT）**，不是 CFM。CFM 的提速靠 `v5turbo` 的 4 步。

### 1.5 版本谱系

| 版本 | 发布 | S2 结构 | 输出 | 一句话定位 | 训练显存（官方） |
|---|---|---|---|---|---|
| v1 | 2024-01 | VITS（2k h） | 32k | 开山：5s 零样本 / 1min 微调 | — |
| v2 | 2024-08 | VITS（5k h） | 32k | 韩/粤；低质参考更稳 | — |
| v3 | 2025-02 | CFM + DiT | 24k | 相似度大涨、GPT 更稳；有金属音、发闷 | 14 G；梯度检查点 12 G；LoRA 8 G [官方] |
| v4 | 2025-04 | CFM + DiT | 48k | 修非整数倍上采样的金属音，原生 48k | 同上 |
| v2Pro | 2025-06 | VITS + SV | 32k | **超 v4，但保留 v2 的硬件成本与速度**；抗低质数据 | 略高于 v2 [官方] |
| v2ProPlus | 2025-06 | 同族增强 | 32k | 高配版；RTF 0.028（4060Ti）/ 0.526（M4 CPU）[官方] | 同 v2Pro |
| **v5** | **2026-10** | **CFM + SV + 新 vocoder** | 48k 档（以实测为准） | 零样本更像、高频更干净、可 Graph/FA；**分支开发** | 未公布 [官方] |

### 1.6 三条铁律（决定「像不像」）

1. **参考音是天花板**：v3/v4/v5 这条 CFM 线，合成音色**更贴参考音**；参考音糊、闷、带电，输出就带着走 [官方]。
2. **低质数据要用 v2Pro 线**：官方明说 v1/v2/v2Pro 对「平均质量较差」的训练集仍能出好结果，v3/v4 不能 [官方]。v5 属 CFM 线，**大概率继承这个脾气**。
3. **GPT 决定「顺不顺」，S2 决定「像不像」**：换 S2 不改 GPT，所以「重复、漏字、怪停顿」要另治（DPO、重训 S1、文本分句）。

---

## 2. 工作流

### 2.1 数据准备（官方 WebUI 五步）

```text
原始音频
 ① UVR5 分离人声/伴奏（bs_roformer / mel_band_roformer；FoxJoy 去混响）
 ② audio-slicer 切片（默认 3–10 s，静音阈值切）
 ③ 降噪（可选；会降到 16k，底噪不大就别开）
 ④ ASR 打标（Fun-ASR-Nano / SenseVoice / FunASR / faster-whisper）
 ⑤ SubFix 人工校对 → 生成 .list
```

`.list` 格式：

```text
vocal_path|speaker_name|language|text
D:\data\yh_0001.wav|yuanheng|zh|今天风挺大，你把外套穿上。
```

语言码：`zh / ja / en / ko / yue`。

### 2.2 训练

| 阶段 | 训什么 | 输入 | 备注 |
|---|---|---|---|
| S1 | GPT（AR） | 语义 token + 文本/BERT | 1 分钟起可微调；数据越多越稳 |
| S2 | SoVITS | 语义 + SV + mel | v5 是 CFM + DiT；LoRA/全参两条路 |

显存门槛（官方，v3 口径）：全参 14 G、开梯度检查点 12 G、**LoRA 8 G** [官方]。v5 未公布；同族 CFM 结构，**推算同档**，8 GB 只能走 LoRA 或云训。

### 2.3 推理

三种入口：

| 入口 | 用途 | 备注 |
|---|---|---|
| `webui.py` / `inference_webui.py` | 人耳试听、调参 | 有「启用并行推理」子界面；v5 另有 CUDA Graph / flash_attn 开关 |
| `GPT_SoVITS/inference_cli.py` | 脚本批处理 | 适合批量出样 |
| `api_v2.py`（默认 `:9880`） | **生产接入** | `/tts`、`/set_gpt_weights`、`/set_sovits_weights`、`/set_refer_audio`、`/control` |

`/tts` 关键参数（v5 分支已含 `use_cuda_graph`）[代码]：

| 参数 | 作用 | 建议 |
|---|---|---|
| `ref_audio_path` + `prompt_text` + `prompt_lang` | 参考音与其文本 | **必填**；参考文本错＝音色漂 |
| `text_split_method` | 切句方式（cut0/1/2/3/4/5） | 长文用 `cut5` |
| `streaming_mode` | 0 关 / 1 质量优先慢 / 2 中等 / 3 低质快 | 实时用 3，成品用 1 |
| `overlap_length` / `min_chunk_length` | 流式块重叠/最小块 | 默认 2 / 16 |
| `sample_steps` / `cfg_rate` | v5 采样步数与 CFG | dev: 32 / 1.3；turbo: 4 / 0 |
| `use_cuda_graph` | AR 静态图 | 40 系默认开 |
| `speed_factor` | 语速 | 0.9–1.1 |
| `parallel_infer` | 并行推理 | 批量才开 |

### 2.4 部署形态

| 形态 | 适合 | 代价 |
|---|---|---|
| Windows 整合包（`go-webui.bat`） | 最快上手 | 包旧（当前官方包还是 v3lora-20250228），**不含 v5** |
| conda + `install.ps1` | 可控 | 下载大（BERT/HuBERT/G2PW/UVR5/ASR） |
| Docker（`xxxxrt666/gpt-sovits`，含 Lite） | 隔离 | Windows 需调 `shm_size` |
| Colab / AutoDL 镜像 | 无卡训练 | 数据要上传 |
| **api_v2 常驻 + 热切权重** | **YHLZ 这种要接进主链** | 需自己做显存调度 |

### 2.5 给 YHLZ 的最小链路

```text
LLM 流式文本
  → 分句（≤60 字，按 。！？；… 切）
  → POST http://127.0.0.1:9880/tts
       {text, text_lang:"zh", ref_audio_path, prompt_text, prompt_lang:"zh",
        text_split_method:"cut5", streaming_mode:3, sample_steps:4, cfg_rate:0}
  → 24k/48k PCM 流
  → 现有 TTSProviderPort（backend/live 或 target_playback）
  → 播放 / OBS 浏览器源
```

---

## 3. 生态

### 3.1 上游（它站在谁肩上）

| 依赖 | 用途 | 许可/来源 |
|---|---|---|
| CNHuBERT（chinese-hubert-base） | 语义特征 | TencentGameMate |
| chinese-roberta-wwm-ext-large | 文本特征 | HFL |
| BigVGAN | 声码器 | NVIDIA |
| ERES2NetV2 | 说话人向量 | ModelScope（iic） |
| f5-tts / DiT | v3+ 的 CFM 主干灵感 | MIT |
| UVR5 / audio-slicer / SubFix | 数据三件套 | 各自开源 |
| FunASR / Fun-ASR-Nano / SenseVoice / faster-whisper | 打标 | 阿里 / Systran |
| G2PW | 多音字 | 社区 |

### 3.2 下游（谁在用它）

| 类型 | 代表 | 说明 |
|---|---|---|
| 官方 API | `api_v2.py` | HTTP/流式/热切权重，**生态的事实标准接口** |
| 推理优化 | [X-T-E-R/GPT-SoVITS-Inference](https://github.com/X-T-E-R/GPT-SoVITS-Inference) | 面向流式与并发的二次实现 |
| 可视化编排 | [AIFSH/ComfyUI-GPT_SoVITS](https://github.com/aifsh/comfyui-gpt_sovits) | ComfyUI 节点里做克隆/TTS |
| 角色前端 | [haide-D/SillyTavern-GPT-SoVITS](https://github.com/haide-D/SillyTavern-GPT-SoVITS) | SillyTavern TTS 扩展 |
| 云端体验 | [HF Space demo](https://lj1995-gpt-sovits-proplus.hf.space/) | 官方 half-H200 在线试 |
| 分发 | HF `lj1995/GPT-SoVITS`、ModelScope、Docker Hub、AutoDL、Colab | 权重与镜像 |
| 中文社区 | B 站教程、白菜工厂整合包/文档、QQ 群 | 踩坑资料密集 |

### 3.3 生态位

```text
        质量 / 相似度
             ▲
   IndexTTS │        GPT-SoVITS v5（少样本、可控、生态大）
   CosyVoice│   Fish Speech / F5-TTS（零样本、自然度强）
             │        Qwen3-TTS（小、快、中文稳，生态在长）
             └──────────────────────────▶ 速度 / 部署轻
```

- **GPT-SoVITS 的护城河**：中文文本前端最扎实（多音字/数字/混排）、5s–1min 数据门槛最低、API 与社区最成熟、MIT。
- **它的短板**：原生无情绪参数（官方 TODO 未做）、CFM 线吃参考音、分支迭代快。

### 3.4 生态风险

1. **v5 在分支上**：没有整合包、没有 Docker 正式 tag、API 可能再变；追 main 会踩空。
2. **权重许可要逐个看**：代码 MIT、`lj1995/GPT-SoVITS` 模型卡 MIT；但 ERES2NetV2、BigVGAN、G2PW 各有各的条款，商用要单独核。
3. **合成音来源合规**：用 Edge 音色训练/分发，属于「用他人合成音做声音资产」，商用与再分发风险高。
4. **伪造风险**：5 秒克隆的能力本身就是双刃剑，公开分发 voice pack 要带水印/声明。

---

## 4. 价值（对本项目）

### 4.1 技术价值

| 能力 | 数值 | 对元亨的意义 |
|---|---|---|
| 零样本 | 5 s 参考音 | 换嗓/试嗓成本极低，一天能 A/B 十几条 |
| 少样本 | 1 min 微调 | 已有 2 h 语料，**远超门槛** |
| 跨语种 | 中/英/日/韩/粤 | 元亨要唱歌、要念日文歌名 |
| 速度 | v2ProPlus RTF 0.028（4060Ti） | 20 字≈5 s 音频≈0.14 s 计算（不含前端/传输） |
| v5 turbo | 4 步 | 比 dev 少约 16 倍网络前向 [推算] |
| 流式 | `streaming_mode` 0–3 | 首包可压到亚秒级 [推算，待实测] |

### 4.2 工程价值

- **接口稳定**：`api_v2` 一个 POST 就能接，和现有 `TTSProviderPort` 的「文本进、PCM 出」契约同构。
- **可热切换**：`/set_sovits_weights` + `/set_refer_audio` 支持多嗓共存，正好对上白皮书里的 `voice_models` / `engine` 绑定。
- **可回滚**：权重是文件，A/B 就是换路径，比换模型安全。
- **可离线**：不依赖云端，符合「数字生命常驻本机」的定位。

### 4.3 资产价值（最重要）

现在元亨的声音是**模型的副产物**（`tts_model=clone` 一个开关）。引入 GPT-SoVITS 后，声音变成**可版本化的资产**：

```text
voice/
  yuanheng-v1/
    s1.ckpt            # GPT
    s2G.pth            # SoVITS
    ref/ref01.wav      # 参考音
    ref/ref01.txt
    meta.json          # 训练集哈希、步数、评测分、日期
```

这正好是 `docs/YHLZ2.0_VoiceIdentitySystem_架构设计白皮书.md` 里已经画过的 `voice_models` 表；v5 给了它一个可落地的引擎实现。

### 4.4 成本账

| 项 | 量级 | 说明 |
|---|---|---|
| 磁盘（v5 预训练） | **1.59 GB** | s2Gv5dev 766 MB + s2Gv5turbo 766 MB + vocoder [官方] |
| 磁盘（底模） | 3–4 GB | BERT-large + CNHuBERT + G2PW + SV |
| 磁盘（环境） | 8–12 GB | torch + cu118/cu128 + 依赖 |
| 显存（推理） | **3–4.5 GB** [推算] | fp16；BERT 占大头；v5dev 峰值更高 |
| 显存（训练） | 8 GB（LoRA）/ 12–14 GB（全参） | 官方 v3 口径 |
| 训练时间 | 未实测 | 2 h 语料、8 GB 卡，LoRA 预计数小时 [推算] |

---

## 5. 「元亨语音包」现状与诊断

### 5.1 口径与生产事实

> 本文把「元亨语音包」按**生产链路口径**理解：daemon `/tts` 默认 `tts_model=clone` 的路由。
> 若你指的是别的（例如 `下载物象/引进技术/cosyvoice-vllm-full.tar` 那个 CosyVoice3 低延迟包，或翻唱嗓），告诉我，我按同一套指标重测——**本文不含 CosyVoice 包的实测**（台账 0683 只做过静态复核）。

| 事实 | 值 | 来源 |
|---|---|---|
| 默认路由 | `clone` = Qwen3-TTS **0.6B-Base** 零样本克隆 | [代码] `console_server.py:43/51` |
| 参考音 | `models/tts/refs/xiaoyi/ref01.wav`，**7.20 s / 24 kHz / 单声道** | [实测] |
| 参考音来源 | Edge `zh-CN-XiaoyiNeural` 合成 | [台账 0454/6401] |
| 情绪切换 | happy/surprised/excited/angry → `design_bright/ref01.wav`（7.76 s / 24 kHz） | [代码] |
| 输出 | 24 kHz 单声道 16-bit WAV，整段 | [代码] `_wav_bytes` |
| 单次文本 | `_synth` 截 **120 字**；daemon 先截 200 字 | [代码] |
| 失败回退 | clone 异常 → **CustomVoice 0.6B（Vivian 预置音色）** | [代码] `_synth` |
| 1.7B | 已因 OOM 弃用 | [代码注释 0448] |
| 训练语料 | `models/tts/voice_train/yuanheng_2h`，**1312 段 / 120.1 分钟 / 44.1 kHz** | [实测] |
| 语料来源 | 同一 Edge Xiaoyi 音色合成 + loudnorm | [台账 6401] |
| GPU | 8188 MiB 总，**5313 MiB 已用，剩约 2875 MiB**（Gemma 常驻中） | [实测] |

### 5.2 五个根因（按影响排序）

**R1｜参考音是「克隆的克隆」，带宽只有 12 kHz（影响最大）**

Edge 合成 24 kHz → 参考音 24 kHz → 克隆输出 24 kHz。上采样到 44.1 kHz 的语料**不增加信息**。人耳对 12 kHz 以上的空气感、齿音、气息最敏感，这一层从源头就没了。所以无论换 Qwen3、v5 还是 CosyVoice，**只要还用这条参考音，就不可能「清晰」**。

**R2｜零样本 + 0.6B 容量，音色稳定性不足**

零样本靠一段参考音「即兴模仿」，不同句子之间音色会漂；0.6B 的容量也压不住细节。**手里有 2 小时语料却一直没微调**——这是当前最大的「闲置资产」。

**R3｜8 GB 抢卡，回退链会把声音换人**

Gemma 常驻占 5.3 GB，只剩 2.8 GB。Qwen3 0.6B 刚好；一旦 clone 失败，`_synth` 回退到 **CustomVoice 的 Vivian**——不是音质下降，是**突然换了一个人**。这比「不好听」更伤角色一致性。

**R4｜文本前端与截断**

单次 120 字硬截断（QQ 侧 200 字再截 120），长回复会被腰斩；多音字、数字、中英混排没有专门处理。

**R5｜无流式，首包＝整句合成时间**

`generate_voice_clone` 整段返回，长句要等全部合成完才出声。

### 5.3 v5 对每个根因有效吗

| 根因 | v5 能治吗 | 说明 |
|---|---|---|
| R1 参考音 12 kHz 天花板 | **不能** | 新 vocoder 只让 48k 输出「不毛刺」，不能凭空造出 12 kHz 以上的真实信息；甚至可能「脑补」出假高频 |
| R1' 音色不够像 | **能，且是 v5 主卖点** | 零样本相似度大幅提升（官方） |
| R2 零样本漂移 | **能缓解** | v5 相似度更高；但根治仍是微调 |
| R2' 2 h 语料闲置 | **能（但要先洗语料）** | 微调 v5 可行；**不过语料是 Edge 合成的，会把 Edge 的毛病焊死** |
| R3 8 GB 共存 | **不能，可能更糟** | v5 不比 v2Pro 省显存；dev 32 步 + CFG 更吃算力 |
| R4 截断/前端 | **部分能** | 前端更强（G2PW/多语种），但 120 字截断是 YHLZ 工程问题 |
| R5 无流式 | **能** | `streaming_mode` 1/2/3 + v5 滚动窗口 |
| GPT 侧（重复/漏字/语调） | **不能** | v5 没换 S1 |

### 5.4 结论

> **v5 是「上限工具」，不是「续命补丁」。**
> 它能把「像不像小艺」推到很高，也能让高频更干净；但它治不了「参考音本身是 24 kHz 合成音」和「8 GB 装不下两个模型」。
> 真正决定元亨声音上限的，是**换一条高质量参考音/语料**；v5 只是把这条好参考音发挥得更好的放大器。

---

## 6. 建议方案（按性价比排序）

### P0｜先量基线（半天，不改任何生产配置）

固定 20 句测试集（覆盖：陈述/疑问/感叹/多音字/中英混排/长句/情绪句），对现役 `clone` 测：

| 指标 | 工具 | 门槛 |
|---|---|---|
| 音色相似度 | ERES2NetV2 / CAM++ 对参考音算 cos | 记录基线，不设门槛 |
| 自然度/清晰度 | DNSMOS / NISQA 无参考打分 | 记录基线 |
| 可懂度 | SenseVoice/FunASR 回写 CER | ≤ 5% |
| 首包延迟 | 请求→首字节 | 记录 |
| 整句耗时 / RTF | 请求→WAV 完 | 记录 |
| 失败/回退率 | 日志里 `clone fail` 次数 | 0 |

### P1｜换参考音（1–2 天，性价比最高）

三条路，按「像人」排序：

1. **真人录音**（最优）：10–30 s 干净干声，44.1/48 kHz，无混响，签授权。
2. **高质量 TTS 设计嗓**：CosyVoice3 / Fish / IndexTTS2 / Qwen3 VoiceDesign 生成 20–30 s，44.1 kHz 起。**注意：这仍是合成音，只是带宽和自然度更高。**
3. **现有 `design_bright` 长参考**（7.76 s，24 kHz）——最省事，但天花板不变。

验收：同一批 20 句，相似度 cos 与 DNSMOS 双升，人耳盲测 3 选 1 胜出。

### P2｜v5 零样本 A/B（2–3 天）

- 装 v5 分支（**pin 到 commit，不追 main**），下 `gsv-v5-pretrained`（1.59 GB）。
- 两条参考音 × 两档采样：`v5turbo`(4 步/CFG 0) 与 `v5dev`(32 步/CFG 1.3)，共 4 组。
- 测：RTF、首包（`streaming_mode=3`）、峰值显存、20 句盲测。
- **重点看**：在 8 GB 上能不能与 Gemma 共存；不能，就记录「必须时间片」的代价。

### P3｜微调（语料先洗，1 周）

- **先决定语料来源**：
  - 用 Edge 语料 → 只能得到「更稳的小艺」，且商用风险高；
  - 用 P1 的新嗓重新生成 1–2 h → 才是「元亨自己的声音」。
- 8 GB 先走 **LoRA**；全参建议云训（12–14 GB）。
- **版本判断**：语料质量一般时优先 **v2ProPlus**（官方说它抗低质数据）；语料干净、追求相似度时再上 **v5**。

### P4｜集成与调度（3–5 天）

```text
方案 A（推荐）：双轨
  实时闲聊 → Qwen3 0.6B（2 GB，常驻，低延迟）
  高质量旁路 → GPT-SoVITS v5（按需加载：长回复、配音、唱歌、OBS 直播前预热）

方案 B：时间片
  gpu_lock 互锁：TTS 合成前让 Gemma 让出（重启 llama-server 代价高，不推荐高频用）

方案 C：CPU / 二机
  i7-13700H 跑 v5turbo（RTF 待测）；或第二台机器做 TTS 服务
```

接入点：`backend/console_server.py:_synth` 增加 `gptsovits` 分支；`voice_clone_config.json` 里已有 `gpt_sovits.gradio_url` 占位，可改为 `api_v2` 的 `:9880`。

### P5｜验收与回滚

- 保留 `clone` 路由不动，新增 `v5` 路由，用 `tts_model` 开关切换；
- 任何一项指标不达标 → 一键切回；
- 盲测由老爹拍板（听感是最终标准）。

### 6.6 不建议做的事

1. **不要把 v5 直接设成默认**：分支代码 + 无整合包 + 8 GB 未验证。
2. **不要用 Edge 语料训完就宣布「元亨本音」**：那是小艺的克隆，不是元亨。
3. **不要指望 v5 治 GPT 的重复/漏字**：S1 没换。
4. **不要同时开 Gemma + v5dev + 训练**：8 GB 必 OOM。

---

## 7. 风险与未知

| 风险 | 等级 | 应对 |
|---|---|---|
| v5 分支 API 变动/合并回 main | 高 | pin commit；锁定 `tts_infer.yaml` 与权重哈希 |
| 8 GB 共存未验证 | 高 | P2 先测峰值显存；不行就走双轨/CPU |
| v5 对低质语料的鲁棒性未知 | 中 | 先用 v2ProPlus 做对照 |
| 参考音版权/合成音合规 | 中 | 真人授权或自设计；对外分发加声明 |
| 训练时长/效果不确定 | 中 | 先 LoRA 小步试，2 h 语料分 10 min/1 h/2 h 三档 |
| 情绪控制缺失 | 低 | 用参考音切换 + 文本标点；等官方 TODO |

**待实测清单（按顺序）**：v5 在 4060 8G 的峰值显存 → turbo/dev 的 RTF 与首包 → 与 Gemma 共存/时间片代价 → 新参考音的相似度增益 → 微调增益。

---

## 附录 A｜关键证据

| 证据 | 位置 |
|---|---|
| 生产 TTS 路由与参考音 | `backend/console_server.py:43-67, 134-166` |
| 参考音实测 | `models/tts/refs/xiaoyi/ref01.wav` 7.20 s / 24 kHz |
| 语料实测 | `models/tts/voice_train/yuanheng_2h` 1312 段 / 120.1 min |
| GPU 现状 | `nvidia-smi`：5313 / 8188 MiB |
| v5 权重 | <https://huggingface.co/lj1995/GPT-SoVITS/tree/main/gsv-v5-pretrained>（1.59 GB） |
| v5 代码 | <https://github.com/RVC-Boss/GPT-SoVITS/tree/cuda_graph_accel_v5> |
| v5 变更日志 | `docs/cn/Changelog_CN.md`（2026-10-05「V5新版本」） |
| v5 采样实现 | `GPT_SoVITS/module/v5_inference.py` |
| AR 加速 | `GPT_SoVITS/Accel/README.md`、`tools/acceleration.py` |
| API 契约 | `api_v2.py`（`/tts`、`/set_sovits_weights`、`streaming_mode`、`use_cuda_graph`） |
| 训练显存 | Changelog：v3 14 G / ckpt 12 G / LoRA 8 G |

## 附录 B｜可直接用的命令（P2 阶段）

```powershell
# 1) 克隆 v5 分支并锁定
git clone -b cuda_graph_accel_v5 https://github.com/RVC-Boss/GPT-SoVITS.git gsv-v5
git -C gsv-v5 rev-parse HEAD   # 记下 commit，写进报告

# 2) 预训练权重放到 gsv-v5/GPT_SoVITS/pretrained_models/gsv-v5-pretrained/
#    s2Gv5dev.pth / s2Gv5turbo.pth / vocoder.pth

# 3) 起 API（注意别和 9872/8321 冲突）
python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml

# 4) 试音（turbo）
curl "http://127.0.0.1:9880/tts?text=元亨，能听到吗&text_lang=zh&ref_audio_path=ref01.wav&prompt_text=...&prompt_lang=zh&streaming_mode=3&sample_steps=4&cfg_rate=0&media_type=wav" -o out.wav

# 5) 试音（dev）
curl "http://127.0.0.1:9880/tts?text=元亨，能听到吗&text_lang=zh&ref_audio_path=ref01.wav&prompt_text=...&prompt_lang=zh&streaming_mode=1&sample_steps=32&cfg_rate=1.3&media_type=wav" -o out_dev.wav
```

> 真机试音前先问老爹（台账 0124）。

---

## 附录 C｜一句话回答「值不值得」

- **想要「更像人、更清晰」**：值得，但先换参考音（P1），v5 是放大器（P2）。
- **想要「低延迟常驻」**：v5 不是答案，Qwen3 0.6B 已经更合适；v5 做旁路。
- **想要「元亨独有的声音资产」**：值得，v5 + 新语料 + 版本化权重，正好接上 VoiceIdentitySystem 白皮书。
- **想要「这周就上线」**：不值得，v5 分支太新，整合包都没出。
