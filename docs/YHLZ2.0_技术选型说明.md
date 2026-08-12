# YHLZ 2.0 技术选型说明

> 版本: v1.0
> 生成日期: 2026-08-04
> 依据: YHLZ2.0_架构与技术白皮书 v1.0 + 仓库实际依赖与代码
> 范围: 按原白皮书章节顺序,逐章说明"为什么这么选",不重复"怎么实现"。实现细节见白皮书。

---

## 目录

1. [项目概述](#一项目概述)
2. [总体架构](#二总体架构)
3. [目录结构总览](#三目录结构总览)
4. [后端核心引擎详解](#四后端核心引擎详解)
5. [语音对话链路与数据流](#五语音对话链路与数据流)
6. [延迟优化与并发设计](#六延迟优化与并发设计)
7. [前端与桌面端](#七前端与桌面端)
8. [直播子模块 live_stream](#八直播子模块-live_stream)
9. [插件与工具系统](#九插件与工具系统)
10. [数据存储与记忆体系](#十数据存储与记忆体系)
11. [配置体系](#十一配置体系)
12. [已知问题与待完善项](#十二已知问题与待完善项)
13. [技术白皮书:设计原则与关键技术](#十三技术白皮书设计原则与关键技术)
14. [运行手册与端口速查](#十四运行手册与端口速查)
15. [演进路线](#十五演进路线)

---

## 一、项目概述

### 1.1 选型总原则

YHLZ 2.0 的所有技术决策围绕以下五条优先级递减的原则展开:

| 优先级 | 原则 | 含义 |
|---|---|---|
| P0 | **本地优先 + 显存可控** | 8GB 笔记本 GPU 必须能跑;引擎模块可独立加载/释放,显存花在哪层完全可控 |
| P0 | **低延迟流水线** | "边说边听、边想边播"——任何环节不允许"全部完成再开始下一环节" |
| P1 | **多级 fallback 永不静默失败** | ASR/TTS/LLM 任一环故障,系统仍给出可用输出(而非报错中断) |
| P1 | **引擎可插拔,配置驱动** | 换引擎从"改代码"降为"改配置";抽象基类 + 注册表是标配 |
| P2 | **依赖最小化** | 能用一个库解决的不引两个;能移除的依赖坚决移除(如 Silero VAD) |

> 反例(明确放弃的选项):任何"必须全程联网才能用"的方案、任何"加载后无法释放显存"的方案、任何"主进程阻塞"的同步调用。

### 1.2 三种交互形态的形态选型理由

| 形态 | 入口 | 选型理由 |
|---|---|---|
| WebUI 控制台 | `start.bat` → `webui_server.py`(:5000) | 全功能管理面板,统一管控所有服务;Flask + 纯原生 JS,无构建链,契合"单 bat 启动" |
| 桌面挂件(桌宠) | `live2d_qt_avatar.py` 等 | 透明置顶 Live2D 形象;纯 PyQt5 + QOpenGLWidget 主方案,放弃 QWebEngineView/GLFW/pygame |
| 语音连续对话 Demo | `对话DEMO\voice_chat_demo.py` | 纯本地完整语音闭环,进程内直连引擎,延迟可观测,不经过任何 HTTP |

### 1.3 硬件基线与硬约束派生选型

| 项目 | 规格 | 选型影响 |
|---|---|---|
| GPU | RTX 4060 Laptop **8GB** | ASR + TTS 不能同时常驻;按需加载是硬要求 |
| ASR 设备 | CUDA / FP16 | 必须支持半精度推理 |
| TTS 设备 | CUDA / bf16 + CUDA graph 预热 | 首块延迟优化的关键手段 |
| 统一采样率 | 16kHz(对话链路) | 全链路重采样到 16k,避免混用 |

派生结论:
- **8GB 显存** → 排除端到端大模型(如 Qwen2-Audio 全量本地);选择"小而专"的分离管线(ASR/TTS/LLM 各自独立模型)
- **笔记本移动场景** → 默认在线 LLM(避免本地 7B 模型吃满显存影响 ASR/TTS),保留本地 LLM 接入位
- **Windows + 中文用户** → 优先选有中文优化、Windows 兼容性好的库(如 funasr 优先于原版 Whisper 服务)

---

## 二、总体架构

### 2.1 系统拓扑的架构选型

```
                        ┌─────────────────────────────┐
                        │    webui_server.py (Flask)   │  :5000  WebUI 总控制台
                        │  服务管理/记忆/工具/API代理    │
                        └──────────────┬──────────────┘
                                       │ HTTP /api/* 代理(SSE 转发)
                        ┌──────────────▼──────────────┐
                        │   backend/main.py (FastAPI) │  :8000  后端核心
                        │  SSE /chat · WS /ws/avatar  │
                        │  WS /ws/stream · REST 全套  │
                        └──┬─────┬──────┬──────┬─────┘
```

| 候选 | 结论 | 理由 |
|---|---|---|
| **FastAPI** | ✅ 选用(:8000 主对话链路) | 原生 async、SSE/WebSocket 一等公民、Pydantic 配置校验、与 ASR/TTS/LLM 异步管线天然契合 |
| Flask | ⚠️ 仅用于控制台(:5000/:5050) | WebUI 是 IO 密集代理层,SSE 转发用 Flask 足矣;不引入主对话链路 |
| Starlette 裸用 | ❌ 放弃 | FastAPI 已封装,无需重复造轮子 |
| Django | ❌ 放弃 | 同步 ORM 与流式 SSE 不匹配,过重 |

**关键权衡**:
- **单进程异步** vs 多 worker:选单进程。原因:全局单例引擎(asr/tts/llm)加载昂贵,多 worker 会复制显存占用;并发用 `run_in_executor` 把 ASR 增量推到线程池即可。
- **uvicorn 单实例**:8GB 机器不开多 worker,通过协程 + 线程池混用承载并发。

### 2.2 三种交互形态数据路径的选型

| 形态 | 路径 | 选型理由 |
|---|---|---|
| 语音 Demo | 麦克风 → 进程内引擎单例 → 音箱 | 不经过任何 HTTP 服务,进程内直连 `backend.*`;追求最低延迟,无 HTTP 开销 |
| WebUI 控制台 | 浏览器 → webui_server(:5000) → backend(:8000) | 三层代理,SSE 流式渲染;控制台与对话链路分层,各自独立演进 |
| 桌面桌宠 | 桌宠 WS `:8000/ws/avatar` 收同步事件 + HTTP 控制 | 实时口型/表情/说话事件广播;WS 适合 10ms 级高频事件 |

### 2.3 技术栈选型一览

| 层 | 技术 | 选型理由 |
|---|---|---|
| 后端框架 | FastAPI + uvicorn(单进程,异步) | 见 2.1 |
| 控制台 | Flask(:5000 / :5050) | IO 代理层,无构建链 |
| ASR | FunASR(SenseVoiceSmall)、openai-whisper 兜底 | 中文 SOTA + 显存友好,详见四章 |
| TTS | faster-qwen3-tts(主)、edge-tts、Qwen3-TTS-0.6B-Base(克隆) | 真流式 + CUDA graph 预热,首块 0.4s,详见四章 |
| LLM | openai SDK(AsyncOpenAI)对接 dashscope qwen-turbo / DeepSeek | 统一接口,provider 切换零代码,详见四章 |
| VAD | 纯能量检测状态机 | 已移除 Silero,详见四章 |
| 音频处理 | librosa、scipy、rnnoise、noisereduce、webrtcvad(可选) | 三层降噪互补,详见四章 |
| 桌面渲染 | live2d-py(v3,OpenGL)、PyQt5、Electron 28 + Pixi.js 6 | 纯 PyQt5 主方案,详见七章 |
| 直播 | pyvts、B站 WS 手写协议、GPT-SoVITS(Gradio :9872) | 详见八章 |

---

## 三、目录结构总览

```
YHLZ2.0/
├── backend/                    # 后端核心(FastAPI :8000)
│   ├── tts/                    # TTS 多引擎包(抽象基类 + 注册表范式)
│   ├── voice_identity/         # 声纹身份管理(独立模块化)
│   └── data/                   # 记忆数据库/人格 JSON
├── 对话DEMO/                   # 语音对话 Demo(进程内直连,无 HTTP)
├── webui_server.py             # Flask 总控制台(:5000)
├── desktop_avatar/             # Electron 桌宠(辅助方案)
├── updates/live_stream/        # 直播子模块(独立认知型方案)
├── plugins/                    # 工具插件 x4
├── assets/live2d/              # 5 个 Cubism4 模型
├── GPT-SoVITS/                 # 直播 TTS(.gitignore,本地部署)
├── start.bat                   # 主入口(单 bat 启动原则)
└── 下载物象/乱七八糟/            # 规划与调研文档
```

**目录划分的选型理由**:

| 划分决策 | 选型理由 |
|---|---|
| `backend/tts/` 独立成包 | TTS 多引擎需要抽象基类 + 注册表范式,独立包便于扩展新引擎 |
| `backend/voice_identity/` 独立模块 | 声纹身份管理与 TTS 合成解耦,有独立审计报告(V1.1~V1.6) |
| `对话DEMO/` 与 `backend/` 同级 | Demo 进程内直连引擎,不走 HTTP;独立目录便于单独运行调试 |
| `updates/live_stream/` 独立子模块 | 直播是认知型虚拟主播方案,与主对话解耦;独立插件化架构 |
| `GPT-SoVITS/` 加入 .gitignore | 本地部署、体积大;只在直播场景用,不进入主对话链路 |
| `start.bat` 唯一主入口 | 用户偏好(P0):单 bat 启动,自检依赖 → 启动 WebUI |

---

## 四、后端核心引擎详解

### 4.1 main.py — FastAPI 装配根的选型

**全局单例** vs 依赖注入:选**全局单例**(asr_engine、tts_engine、llm_engine 等)。
- 理由:引擎加载昂贵(显存占用),全局单例避免重复加载;FastAPI 依赖注入对显存类资源不友好(每次请求注入可能触发重载)。
- 代价:测试隔离性弱,通过 `/modules/start|stop` 按需加载/释放显存弥补。

**生命周期(lifespan)**:启动时注入引擎 → 启动播放线程 → sync_manager.start() → 注册热键;关闭时反向释放。这是显存可控(P0)的核心实现。

### 4.2 config.py — 配置中心的选型

**Pydantic Config 单例** vs 多文件配置:选**单例 + .env**。
- 理由:Pydantic 提供类型校验与默认值;.env 单一权威,避免配置散落。
- `load_dotenv(override=True)`:强制以项目根 `.env` 为准,避免环境变量污染。

### 4.3 ASR 引擎选型

| 候选 | 结论 | 理由 |
|---|---|---|
| **FunASR SenseVoiceSmall** | ✅ 主引擎 | 中文识别 SOTA、~500M 参数 8GB 显存友好、FP16 推理快、支持多语言与情感 |
| openai-whisper | ⚠️ Fallback(medium→small→base→tiny) | 英文/小语种兜底;中文不如 SenseVoice 但生态成熟 |
| FunASR fsmn-vad | ❌ 不用 | 已用纯能量 VAD,fsmn-vad 显存占用额外 |
| 阿里云 ASR API | ❌ 不用 | 违反"本地优先"原则,联网延迟不可控 |

**关键权衡**:
- **流式增量** vs 整段识别:选**重叠滑窗流式**(3200 样本触发 + 2/3 重叠 + 前缀 diff)。整段识别延迟过高,违反 P0 低延迟原则。
- **多 pass 重识别**:首次 `avg_log_prob < -0.3` 时用 beam≥15 重新识别。代价:偶发延迟增加;收益:低置信度场景准确率显著提升。
- **三档模式**(speed/balanced/accuracy):允许用户在延迟与准确率间动态切换,而非固化一个参数。
- **HF 端点智能选路**:hf-mirror / modelscope / huggingface / fastgit 实测可达性 + 下载速度排序,解决国内网络问题。
- **模型加载双策略**:`cpu_then_gpu` / `direct_gpu` + 每轮清显存重试(3 次);8GB 显存下首次加载易 OOM,重试机制是必要的。

**已放弃的方案**:
- **Whisper 大模型本地常驻**:medium 模型 FP16 已 ~3GB 显存,与 TTS 同驻会爆显存。

### 4.4 TTS 多引擎选型

| 候选 | 状态 | 选用理由 |
|---|---|---|
| **Qwen3-TTS-12Hz-0.6B-CustomVoice** | ✅ 默认引擎 | 真流式(每 8 token 产一块)、CUDA graph 预热后首块 ~0.4s、音色 Vivian(24kHz)、本地可控 |
| Qwen3-TTS-0.6B-Base | ⚠️ 注册(克隆) | x-vector 说话人向量提取,支持声音克隆;非流式,作特殊场景备选 |
| Edge-TTS | ⚠️ 已实现未注册 | 在线免费、首包延迟低;违反"本地优先",仅作离线兜底备选 |

**关键权衡:faster-qwen3-tts vs 官方 transformers**:
- **faster-qwen3-tts** 胜出原因:CUDA graph 预热把首块延迟从 4-6s 压到 ~0.4s,这是 P0 低延迟原则的硬指标。
- 官方 transformers 实现首块延迟过高,无法满足"首段 300ms 即开口"的播放层门槛。

**引擎管理器设计**:
`BaseTTSEngine` 抽象基类 + `TTSManager` 注册表,实现"换引擎从改代码降为改配置":
- `activate(name)` 成功即激活
- `auto` 逐个尝试可用引擎
- 执行期异常自动回退到可用引擎

**这是 P1"引擎可插拔"原则的标准范式**,后续 ASR/LLM 也沿用此模式。

**已放弃的方案**:
- **Edge-TTS 作为默认**:违反"本地优先"原则,且无法保证网络稳定性。
- **VITS 系本地大模型**:推理速度慢,8GB 显存下首块延迟无法达标。

### 4.5 LLM 引擎选型

| 候选 | 状态 | 选用理由 |
|---|---|---|
| **dashscope qwen-turbo** | ✅ 默认 | 中文对话质量好、流式延迟低、兼容 OpenAI 协议(`compatible-mode/v1`) |
| DeepSeek | ⚠️ 可切换 | 推理能力强,作备选 provider |
| qwen-vl-plus | ⚠️ 多模态 | `generate_with_image` 用于视觉输入(屏幕分析等) |
| 本地 vLLM / Ollama | ❌ 不作默认 | 7B 模型吃显存,与 ASR/TTS 抢占 8GB 预算;保留接入位 |

**关键权衡**:
- **AsyncOpenAI SDK** 而非各厂商原生 SDK:统一接口、provider 切换零代码改动,符合 P1 引擎可插拔原则。
- **逐字符 flush**(flush_threshold=1):极致压缩首 token 延迟,代价是 SSE 包数多(用 zlib 压缩缓解)。
- **LRU 缓存**(1000 条 / TTL 300s / MD5 键):重复问题零延迟返回,适合高频问候场景。
- **`_warmup()` 预连接**("Hi", max_tokens=1):首次真实请求不再承担建连延迟。
- **离线 fallback**:LLM 未连接时按关键词模板回复("哥们儿,有啥事儿?"),保证永不静默失败。

### 4.6 VAD 引擎选型

| 候选 | 结论 | 理由 |
|---|---|---|
| **纯能量检测 + 三态状态机** | ✅ 选用 | CPU 即可跑、零显存占用、状态机简单可调、与 8GB 显存预算不冲突 |
| Silero VAD | ❌ 已移除 | 依赖 ML 模型加载、占用显存/GPU、与 ASR/TTS 抢资源;`requirements.txt` 中残留声明但代码已不引用 |
| FunASR fsmn-vad | ❌ 不用 | 同样占用模型资源,收益有限 |
| webrtcvad | ⚠️ 可选 | 备用能力,默认不启用 |

**关键权衡**:
- **动态 hangover**:整段语音 <15 帧(短促语音)时 `dynamic_hangover = max(hangover_frames, 3)`,防短句切尾。这是纯能量 VAD 的核心增强,弥补了无 ML 模型的劣势。
- **噪声自适应**:静音态 RMS 入 30 帧滑动窗取中位数做 noise_floor(学习率 0.02),有效阈值 = `max(energy_threshold, noise_floor × 3.0)`。解决环境噪声漂移问题。
- **3 帧 VAD 抗误触**(barge-in):连续 3 帧有声才判定插话,防单帧噪声触发打断。

**演进教训**:
> 从 Silero VAD 迁移到纯能量 VAD 是典型"依赖最小化"决策。Silero 的精度优势在能量 VAD + 动态 hangover + 噪声自适应后已足够,而它占用的显存对 8GB 机器是显著负担。**这条迁移路径体现了 P2 依赖最小化原则。**

### 4.7 会话与上下文的选型

**conversation_manager.py — 连续对话状态机**:
- **状态机** `IDLE → LISTENING → THINKING → SPEAKING → INTERRUPTED` vs 自由状态:选状态机。原因:barge-in/回声/超时等边界条件多,状态机显式枚举更可控。
- **回声过滤(自播窗口)** vs AEC:选**自播窗口为主**(播放前 2.5s + 播放后 6s),AEC 备用。原因:自播窗口逻辑简单、零延迟、95% 场景够用;AEC 引入自适应滤波复杂度,后续作双保险接入。
- **离线 fallback**:LLM 未连接时按关键词模板句回复,保证永不静默失败。

**context_manager.py — 上下文窗口**:
- **Token 计数**:tiktoken `cl100k_base`,缺失时字符 ×0.5 估算。tiktoken 是 OpenAI 官方计数器,与 LLM 计费一致。
- **异步摘要**:累计 ≥7000 token 时调 LLM(temperature=0.3,≤100 字)生成摘要,清空历史仅留摘要,防溢出。异步而非同步,避免阻塞对话。
- **性格读写** `backend\data\personality.json`:JSON 而非 DB,原因:性格是低频读写的单对象,JSON 足够,无需引入 DB 复杂度。

### 4.8 情绪分类选型

| 候选 | 结论 | 理由 |
|---|---|---|
| **中文关键词规则表** | ✅ 当前选用 | 零延迟、零显存、可解释;五分类(happy/calm/sad/angry/neutral)足够 |
| mDeBERTa 零样本 | ⚠️ 预留 | 准确率更高但需加载模型,占用显存;准确率不达标时切换 |

**关键权衡**:
- 置信度 = 最高分 / 总分归一化;`resolve_voice_for_emotion` 低于阈值(0.5)回退默认音色,避免低置信度误切音色。

### 4.9 多模态同步选型

- **`SyncEvent` + `deque(maxlen=1000)`** vs 消息队列:选 deque。原因:单进程内同步,无需跨进程队列;maxlen 防内存泄漏。
- **后台 `_process_loop` 10ms 轮询**:10ms 是人耳对口型同步的感知阈值上限,低于此无收益。
- **事件类型**:mouth_sync / emotion_change / speech_start / speech_end / tts_chunk,覆盖桌宠同步全部需求。

### 4.10 音频链路四大模块选型

| 模块 | 选型 | 理由 |
|---|---|---|
| `audio_enhancer.py` | 噪声门 → 预加重(α=0.97) → RNNoise → 自适应谱减 → VAD 剪切 → 双频段 AGC → DRC → RMS 归一化 → EQ | 多级链路覆盖稳态/非平稳/突发三类噪声 |
| `noise_suppression.py` | AGC → noisereduce(非平稳,prop_decrease=0.6)或谱减法(alpha=2.0) → STFT 频段 EQ | 模式可选:none/noisereduce/spectral/deepfilter/hybrid |
| `echo_cancellation.py` | NLMS 自适应滤波(4096 阶,逐样本)+ 频域分块(512)+ 谱减抑制 + 双讲检测 | **当前未被主链路调用**,备用能力 |
| `audio_buffer.py` | deque 队列 + interrupt 清缓冲 + done 哨兵 + 自播窗口 + 口型计算 | 轻量高效,deque 适合首尾频繁操作 |

**关键权衡**:
- **三层降噪** vs 单库方案:选三层(RNNoise + noisereduce + 谱减)。单一方案覆盖不了稳态/非平稳/突发三类噪声,组合代价是延迟略增,但 ASR 准确率显著提升。
- **AEC 未接入主链路**:当前自播窗口过滤已能解决 95% 回声场景,AEC 作为后续接入的"双保险",避免过早引入复杂度。
- **RNNoise** vs 其他:实时性强、CPU 推理、对稳态噪声效果好,符合 P0 本地优先。

### 4.11 文本后处理选型

- **OpenCC** vs 内置对照表:优先 OpenCC,缺失时 fallback 到 1000+ 条内置对照表。保证繁简转换在无 OpenCC 环境仍可用(P1 fallback 原则)。
- **常见错字纠正(~200 条)+ 拼音纠错(~200 条)**:规则表自实现,零延迟、可维护。
- **置信度能力**:`filter_by_confidence`(avg_logprob<-0.8 不可靠),与 ASR 多 pass 联动。

---

## 五、语音对话链路与数据流

### 5.1 主链路(Web 服务形态)的选型

```
麦克风 → vad_engine → asr_engine → context_manager → llm_engine
       → 切句器 → tts_manager → audio_buffer → 播放线程 → sync_manager → WS /ws/avatar → 桌宠
```

**链路各环节的选型理由**:
- **VAD 前置**:能量 VAD 先判定打断,避免无效音频送 ASR 浪费 GPU。
- **ASR 多 pass + 后处理**:准确率与延迟动态平衡。
- **LLM 逐字符流式**:首 token 延迟最小化。
- **切句器双档**:`/chat` 50字上限、`/ws/stream` 12字触发/30字上限。Web 服务 vs WS 流式对延迟敏感度不同,分别调参。
- **TTS 流式 + 首段 300ms 即开口**:心理感知首响最快。
- **口型计算每 0.1s**:与 sync_manager 10ms 轮询配合,平衡精度与开销。

### 5.2 语音 Demo 形态选型

**四类线程 + 四套队列的并发设计** vs 单线程异步:选**线程 + 队列 + asyncio 混合**。
- 理由:sounddevice 回调是 C 层线程,不能直接用 asyncio;线程 + 队列是 audio 回调与异步 LLM/TTS 的标准桥接模式。

| 线程 | 选型理由 |
|---|---|
| 录音线程 | sd.InputStream 回调,只做 VAD 与帧缓冲,**从不阻塞**;ASR 由 `_flush_speech` 另起 daemon 线程 |
| 播放线程 | OutputStream 回调连续无间隙播放;缓冲不足补静音 |
| 处理线程 | `_on_speech_end` 拿锁后 `_handle_turn`,同步 ASR + `asyncio.run` 跑 LLM/TTS |
| 排队段消费者 | 消化插话/超时语音段,绝不丢弃 |

| 队列 | 选型理由 |
|---|---|
| `Player._queue` | threading.Queue,播放音频序列 |
| `Recorder._pending_segments` | deque(maxlen=8),插话/超时段;带 `_queue_lock` |
| `play_queue` | asyncio.Queue,TTS 合成任务 ↔ dispatcher;`asyncio.Queue` 适配异步管线 |
| `Recorder._preroll` | 1s 环形缓冲,防丢首字;环形缓冲是预滚动的标准数据结构 |

**三大对话体验机制的选型**:

1. **插话不打断 / 排队追加(方案A)** vs 立即打断:
   - 选排队追加。理由:"宁可排队听完,不可丢用户的话"(P1 对话体验 > 严格时序)。
   - 音量遮蔽 `frame_rms > AI音量 × 1.6`:防把 AI 回声当插话。

2. **语音段超时入队不丢弃(方案C)** vs 丢弃:
   - 选入队。理由:同上,绝不丢弃用户语音段。
   - `_on_speech_end` 拿 `_processing` 锁超时 2s → `push_pending` 入队。

3. **相邻短段合并** vs 各自独立处理:
   - 选合并。理由:处理"对/然后/那个"碎片,合并后 ≤50 字的段拼成一句。
   - 相邻 <1.5s 且合并后 ≤50 字才合并,避免过度合并。

**并行 TTS 与顺序保证**:
- **LLM 每出一句 `create_task(_synth_one)`**:并行合成,各句独立。
- **`_play_dispatcher` 用 `next_seq` + pending 字典做 seq 排序**:并行合成结果按序输出,句子间零卡顿。
- **barge-in 令牌 `_gen_token`**:使旧 LLM/TTS 立即退出,防止上下文污染。

**回声判定**:`_is_echo()` 检查插话与刚播 assistant 文本字符重叠 >60% 判回声。字符重叠率比音频 AEC 轻量,适合 Demo 场景。

### 5.3 回声防自嗨双保险选型

1. **运行时窗口过滤**(主):audio_buffer 自播窗口(播放前 2.5s 余量 + 播放后 6s 余波)。选主方案的原因:逻辑简单、零延迟、95% 场景够用。
2. **AEC 备用能力**:NLMS 自适应滤波器 + 双讲检测模块已实现,未被主链路引用。选备用的原因:避免过早引入复杂度,后续自播窗口不足时接入。

---

## 六、延迟优化与并发设计

### 6.1 三层延迟优化选型

| 层 | 技术 | 选型理由 |
|---|---|---|
| LLM 层 | 逐字符 flush(flush_threshold=1)+ 预热 | 首 token 延迟最小化;代价是 SSE 包数多,用 zlib 压缩缓解 |
| TTS 层 | 真流式(每 8 token 一块)+ CUDA graph 预热 + 端到端预热 | 首块延迟 4-6s → ~0.4s;CUDA graph 是 faster-qwen3-tts 的核心优势 |
| 播放层 | 首段满 `tts_first_chunk_min_ms`(300ms)即开口渐进播放 | 心理感知首响最快;300ms 是人耳感知"即时"的阈值 |

**三层流水线**是 P0 低延迟原则的核心实现,任何一层不流式都会破坏整体延迟。

### 6.2 并发模型选型

| 模块 | 并发模型 | 选型理由 |
|---|---|---|
| **backend** | FastAPI 异步 + `run_in_executor` 跑 ASR 增量 + 独立 sounddevice 播放线程 + sync_manager 10ms 事件循环 + LLM/TTS 协程流水线 | 异步主线程承载 HTTP/WS,ASR 增量推线程池避免阻塞事件循环,播放线程独立避免音频卡顿 |
| **语音 Demo** | 线程 + 队列 + asyncio 混合 + 互斥锁 `_processing`(同刻只处理一句)+ `_pending_lock`(消费者互斥) | sounddevice 回调是 C 层线程,不能直接用 asyncio;锁保证同刻只处理一句,避免上下文错乱 |
| **显存管理** | `/modules/start|stop` 按需加载/释放 ASR/TTS/VAD/LLM | 8GB 笔记本显存预算下,引擎独立加载/释放是硬要求(P0) |

**关键权衡**:
- **协程流水线**(生产者切句 → 消费者合成 → 缓冲):比"全部生成完再播"延迟低数倍,符合 P0。
- **所有场景不丢弃语音段**:Demo 的锁超时转排队机制,保证用户语音绝不丢失(P1 对话体验)。

---

## 七、前端与桌面端

### 7.1 WebUI 总控制台选型

| 模块 | 选型 | 理由 |
|---|---|---|
| **Flask** | ✅ 选用 | 控制台是 IO 代理层,Flask 足够;无框架学习成本 |
| **纯原生 HTML/JS(2443 行)** | ✅ 选用 | 无构建步骤、无 node_modules、可直接编辑;与项目"单 bat 启动"理念契合 |
| Vue/React | ❌ 放弃 | 引入构建链增加复杂度,与 P2 依赖最小化冲突 |
| FastAPI 前端 | ❌ 放弃 | 主对话链路已用 FastAPI,控制台分离避免耦合 |

**关键权衡**(用户偏好 P0):
- **侧边栏 + 全容器内容区**:Web-like 布局
- **菜单切换页面而非追加**:带 active 高亮
- **窗口 90% 屏幕 + 居中**
- **侧边栏 250px 固定宽 + 4px 左高亮**
- **所有界面文本白色**
- **亮色主题**

### 7.2 桌面挂件四种实现的选型

| 实现 | 状态 | 选型理由 |
|---|---|---|
| `live2d_qt_avatar.py` | ✅ 主方案 | PyQt5 + QOpenGLWidget(live2d-py v3),LWA_COLORKEY 透传;独立聊天窗、快捷键、12Hz 按键轮询 |
| `live2d_desktop_avatar.py` | ⚠️ 一体化方案 | QWebEngineView 加载 `:8081` 网页 + QWebChannel 桥;FaceTracker 摄像头面部捕捉,系统托盘 |
| `live2d_pygame_avatar.py` | ❌ 已弃用 | pygame + OPENGL;**必须先建窗口再 import live2d.v3**(DLL 冲突防护),手绘气泡菜单 |
| `live2d_renderer.py` | ✅ 参考实现 | 纯渲染模块,抽出口型/补间/表情差分淡出/视线管理器 |

**关键权衡**:
- **QOpenGLWidget** vs GLFW:QOpenGLWidget 与 PyQt5 事件循环原生集成,无 DLL 冲突;GLFW 需要混用事件循环,不稳定。
- **LWA_COLORKEY** vs WA_TranslucentBackground:组合使用实现黑色背景透传,这是 Windows 透明窗口的可靠方案。
- **live2d-py v3** vs Pixi.js:live2d-py 是 Python 原生绑定,与后端同进程通信零成本;Pixi.js 需要走 WS,延迟略高。

**教训沉淀(已落地)**:
> 1. **live2d-py C 扩展 DLL 与 pygame OpenGL DLL 加载顺序冲突** → 必须先建窗口再 import live2d.v3
> 2. **QWebEngineView 无法实现真正透明窗口** → 改用原生 PyQt5 方案
> 3. **GLFW 与 PyQt5 事件循环混合不稳定** → 全部改用 QOpenGLWidget
> 4. **进程残留导致新旧桌宠实例并存** → 单实例锁 + 窗口标题验证

这些教训已写入项目 memory,后续不再走这些弯路。

**共有的口型与表情机制选型**(源于 live2d_renderer.py):
- **口型:三正弦叠加** `0.4sin(2.5φ)+0.3sin(1.8φ)+0.3sin(3.3φ)` 归一化 + RMS ×8 放大 + `LIPSYNC_OVERRIDE_THRESHOLD=0.001` 参数保护。三正弦叠加比单正弦更接近自然开合。
- **表情:基线三快照 + 差分淡出**(应用表情后计算参数基线差,~800ms 淡出回原态;口型参数不参与表情淡出)。差分淡出比硬切自然,口型豁免避免淡出期间口型失真。
- **视线:GazeManager(Drag 冷却)+ ease-out 补间**;状态机 idle/viewing/thinking/replying。

### 7.3 Electron 桌宠选型

| 候选 | 状态 | 理由 |
|---|---|---|
| **Electron 28 + Pixi.js 6 + pixi-live2d-display** | ⚠️ 辅助方案 | 借鉴"桌面灵"架构、跨平台、Cubism 2/4/5 全支持;但内存占用高,非首选 |
| PyQt5 + QOpenGLWidget | ✅ 主方案 | 见 7.2 |

**Electron 主进程关键选型**:
- **无边框透明置顶**(380×480, screen-saver 级置顶):桌宠标准形态
- **位置持久化**(`%APPDATA%/yuanheng-avatar/avatar-config.json`):用户体验
- **点击穿透 + 三阶段拖拽 + 工作区 clamp + 330ms 淡出关闭**:交互细节
- **单实例锁**:防多实例(教训沉淀)
- **安全模型**:`contextIsolation:true` + `nodeIntegration:false` + contextBridge 暴露白名单 IPC:Electron 安全最佳实践

### 7.4 浏览器 Live2D 查看器选型

- **8 种情感光效系统**:happy/sad/angry/surprised/anxious/tired/excited/neutral,主色 + 辉光 + 呼吸强度,easeInOutQuad 过渡。光效系统比单一颜色切换更具表现力。
- **外部控制双通道**:`window.postMessage` + `window.*` 函数。双通道兼容不同集成方式。
- **5 个 Cubism4 模型**:hiyori / akari / wanko / tororo / hijiki(均含 vtube.json 可导入 VTube Studio)。多模型可选,vtube.json 支持 VTS 导入。

---

## 八、直播子模块 live_stream

### 8.1 架构选型

**LiveStreamManager 中央调度 + 插件化** vs 单体脚本:选**插件化**。
- 理由:直播涉及 B站/VTS/TTS/认知多模块,插件化便于独立开发与替换;与主项目解耦,可独立运行。

```
LiveStreamManager(中央调度:状态机/能量/冷场/话题/记忆)
   ├── set_plugins() ──▶ BilibiliLivePlugin / VTubeStudioPlugin
   ├── set_engines() ──▶ MouthSyncEngine / ExpressionController / TopicGenerator / CognitiveAvatarController
   ▼
events.py 事件工厂: is_allowed(权限+价格门槛) → normalize → format → to_payload
   ▼
tts_service.enqueue_text() ── TTS 双队列(HIGH/NORMAL)──▶ GPT-SoVITS Gradio(:9872)
```

### 8.2 直播工作流选型

| 模块 | 选型 | 理由 |
|---|---|---|
| **状态机** `IDLE → PREPARING → LIVE ⇄ BREAK → ENDING → ENDED` | ✅ 选用 | 直播生命周期明确,状态机可控 |
| **B站 WS 手写二进制协议** | ✅ 选用 | 官方无成熟 Python SDK,手写可控;16B 头 + body + zlib 解压 + 30s 心跳 |
| **B站第三方库** | ❌ 放弃 | 无成熟方案,手写可控性更强 |
| **SC/礼物/舰长 = HIGH 优先级 TTS** | ✅ 选用 | 付费用户优先播报,商业逻辑 |
| **弹幕回复 LLM ≤30 字 + 2s 延迟** | ✅ 选用 | 防刷屏;30 字适合语音播报时长 |

**长直播自律管理选型**:
- **能量系统**:LIVE 每 60s 衰减 0.005,休息恢复 0.02/分钟,<20% 自动休息。模拟人类疲劳,避免"无限直播"的机械感。
- **自动休息**:每 30 分钟强制休息。
- **冷场检测**:30s 无弹幕自动生成话题。
- **自动话题**:每 300s 主动(topic_generator 6 大类 60+ 话题)。
- **直播记忆回写**:结束后保存时长/弹幕数/礼物数/热门话题到主项目记忆库(category="live")。

这些是"认知型虚拟主播"的核心差异化,而非简单弹幕回复机器人。

### 8.3 认知控制器选型

**自实现规则引擎** vs ML 模型:选**规则引擎**。
- 理由:8 种认知状态(NEUTRAL/ALERT/FOCUSED/SURPRISED/CALM/EXCITED/THREATENED/BEAUTY_AWE)+ 三层判定 + 注意力头部动作,规则可解释、零显存、可调。

**关键设计**:
- **三层判定**:系统状态映射 → 张力类型(危机→THREATENED 优先于美学→BEAUTY_AWE)→ 认知带宽。优先级保证危机场景不被美学覆盖。
- **表现映射**:THREATENED→angry 表情、BEAUTY_AWE→surprised、EXCITED→excited+wave_hand、ALERT→surprised+blink。
- **注意力头部动作**:视觉/音频注意力权重(5 帧滑动平均)→ HeadX/HeadY + easeBoth 缓动。5 帧滑动平均抗抖动。
- **跨模态涌现**:多模态共鸣→BodyAngle 摇摆;空间感知激活→HeadX 扫视。
- **规则引擎**:6 条按优先级(10~1)排序,支持动态增删。

### 8.4 TTS 服务选型

| 候选 | 结论 | 理由 |
|---|---|---|
| **GPT-SoVITS(Gradio :9872)** | ✅ 选用 | 直播场景需要强声音克隆,GPT-SoVITS 克隆质量高于 Qwen3-TTS-Base |
| Qwen3-TTS-Base | ❌ 直播不用 | 克隆质量不足;用于主对话链路的轻量克隆 |
| **双线程双队列(HIGH/NORMAL)** | ✅ 选用 | HIGH 满时挤掉 NORMAL(evict 回调);`threading.Condition` 同步 |
| **GradioClient 直连** | ✅ 选用 | `/config` 发现 API id,`/change_sovits_weights` 热切换权重,`/inference` 合成(20+ 参数) |
| **播放 winsound → 回退 ffplay** | ✅ 选用 | winsound 零依赖,ffplay 兜底 |
| **dB 增益限幅 -60~+24** | ✅ 选用 | 防 clipping |

### 8.5 插件选型

| 插件 | 选型 | 理由 |
|---|---|---|
| `bilibili_live` | 手写 B站 WS 协议 + `api.live.bilibili.com/msg/send` | 官方无 SDK,手写可控 |
| `vtube_studio` | pyvts 认证 + 表情热键 + `set_parameter_with_easing` 6 种缓动 100Hz 插值 + 自动眨眼(3s 间隔) | 官方 Python 库,参数缓动是 VTS 的优势 |
| `live_control` | 统一入口:start/end/break/resume/send/get_status/get_stats/set_expression/config | 统一接口便于外部调用 |

---

## 九、插件与工具系统

### 9.1 架构选型

**`NekoPluginBase` 抽象基类 + `@plugin_entry` 装饰器 + `plugin.toml` 声明** vs 其他方案:
- 选此方案的理由:与 TTS 的 `BaseTTSEngine` + `TTSManager` 范式一致(P1 引擎可插拔原则)。
- `plugin.toml` 声明(entry 指向 `plugins.xxx:Class`,SDK 版本 `>=0.1.0,<0.2.0`,enabled/auto_start):声明式配置,符合"配置驱动"原则。
- `Ok(value)/Err(error)` 结果对象:Rust 风格错误处理,比异常更显式。

> ⚠️ 注意:`plugin_sdk.py` / `plugin_manager.py` / `tools.py` / `smart_tool_manager.py` 当前为**反编译还原的 stub 空壳**(见 12 章),插件实现本身完整,但调度层待重建。

### 9.2 工具插件清单选型

| 插件 | 工具 | 选型理由 |
|---|---|---|
| `api_tools` | `get_weather`(wttr.in)、`web_search`(DuckDuckGo) | wttr.in 免费无 Key;DuckDuckGo 无需 API Key,requests 超时 10s |
| `file_tools` | `read_file`(超 1000 字截断)、`write_file`(append)、`list_files`(带图标) | 截断防 LLM 上下文溢出;append 模式避免覆盖 |
| `utility_tools` | `calculator`(正则白名单 `^[\d\s+\-*/().%^]+$` 后 eval)、`get_time/get_date`、`set_reminder`(守护线程) | 正则白名单防 eval 注入;守护线程防提醒丢失 |
| `screen_monitor` | `start/stop_monitor`、`capture_now`、`analyze_now`、`get_status`、`get_analysis_history`、`set_config` | 30s 截屏 + 120s 分析;识别"视频/游戏/文档/网页"时按 300s 冷却**主动搭话** |

**关键权衡**:
- **wttr.in** vs 心知天气/和风天气 API:选 wttr.in。原因:免费无 Key,符合 P2 依赖最小化;商业 API 需 Key,引入配置复杂度。
- **DuckDuckGo** vs Google/Bing:选 DuckDuckGo。原因:无需 API Key,无配额限制。
- **正则白名单 + eval** vs `ast.literal_eval`:选正则白名单 + eval。原因:计算器需要四则运算与百分号,`literal_eval` 不支持运算符;正则白名单保证安全。
- **screen_monitor 主动搭话**:300s 冷却防刷屏,依赖 vision_engine(stub)与 `llm_engine.generate_with_image`。

---

## 十、数据存储与记忆体系

### 10.1 人格数据选型

**JSON 文件**(`backend/data/personality.json`) vs DB:
- 选 JSON。理由:性格是低频读写的单对象,JSON 足够,无需引入 DB 复杂度。
- 角色:元亨,用户的"铁哥们";性格词:义气/随和/爽快
- 说话风格 casual、兄弟腔、口头禅(收到哥们/哟/中/没毛病/妥了)
- 由 context_manager 读入生成 system prompt

### 10.2 记忆数据库选型

> ⚠️ 当前为 stub,真实实现待重建。本节描述的是**已确定的选型方向**。

| 候选 | 结论 | 理由 |
|---|---|---|
| **SQLite** | ✅ 选用 | 单文件、零运维、与 Python stdlib 集成、适合个人桌面应用 |
| Postgres | ❌ 放弃 | 需独立服务,违反"单 bat 启动"原则 |
| Redis | ❌ 放弃 | 内存型不适合持久化记忆 |
| ChromaDB / FAISS | ⚠️ 备选 | 向量检索;当前用 SQLite + embedding 列(100+ 维)存,后续可迁移 |

**v1 schema**(已存在,81KB,13 条记忆):
- `memories`:id/content/category/importance/created_at/last_accessed/**embedding**(100+ 维向量,曾有向量检索)/**decay_factor**(遗忘衰减)/source_conversation/is_pledge/pledge_deadline/pledge_status/context_tags/related_memory_ids/iteration_count
- `memory_relations`:记忆关系图谱(source/target/relation_type)
- `context_scenarios`:场景化记忆过滤(trigger_keywords/memory_filter/priority)

**v2 schema**(已设计未实现,5 表):
- `long_term_memories`:v1 基础上新增 emotion_tag、consolidated_into(记忆整合)
- `memory_relations`:多 weight 列
- `contacts`:姓名/关系/关系分/时间线/记忆关联(15 列)
- `personality_profiles`、`emotion_records`:人格画像与情绪记录

**关键权衡**:
- **SQLite + 自实现向量检索** vs ChromaDB:选 SQLite。原因:依赖最小化、个人桌面场景数据量小(千条级)、SQLite 足够;ChromaDB 引入额外服务进程。
- **多实体图谱**(contacts/personality):复杂度高,但为长期"记忆→人格动态演化"铺路,符合 P2 长期智能化目标。
- **遗忘衰减**:decay_factor 字段已设计,后续按时间/访问频率衰减。
- **场景化过滤**:`context_scenarios` 表,trigger_keywords → memory_filter → priority。

**结论**:记忆管线(v1 向量检索 + v2 多实体)曾真实存在,现已被 stub 占位,真实实现需按上述 schema 重建。

### 10.3 其他运行产物选型

| 目录 | 选型理由 |
|---|---|
| `outputs/` | TTS 音频产物,便于回放调试 |
| `recordings/` | 录音,便于回放调试 |
| `logs/` | webui/backend 日志,分级滚动 |
| `cache/` | 运行缓存,LLM LRU 缓存等 |
| `data/test_sandbox.txt` | 沙盒写入测试文件,file_tools 验证用 |

---

## 十一、配置体系

### 11.1 .env 选型

**单一 .env 权威** vs 多配置文件:选**单一 .env**。
- 理由:避免配置散落;.env 是后端引擎配置的唯一权威。
- `load_dotenv(override=True)`:强制以项目根 `.env` 为准,避免环境变量污染。

```
API_PROVIDER               # dashscope / deepseek
DEEPSEEK_API_KEY / BASE_URL / MODEL
DASHSCOPE_MODEL            # qwen-turbo(Key 从系统环境变量读)
ASR_MODEL / ASR_DEVICE / USE_FP16 / USE_KV_CACHE / ASR_FAST_MODE
TTS_ENGINE / TTS_MAX_CHUNK_LENGTH / TTS_FIRST_CHUNK_MIN_MS / TTS_FALLBACK_BUFFER_ENABLED
MAX_CONTEXT_TOKENS / SUMMARY_THRESHOLD / TTS_BUFFER_MS / SAMPLE_RATE
```

### 11.2 配置文件清单选型

| 文件 | 用途 | 选型理由 |
|---|---|---|
| `.env` | 后端引擎配置(唯一权威) | 单一权威,避免散落 |
| `gui_config.json` / `assets/live2d/gui_config.json` | 桌宠配置 | GUI 配置独立,便于不同桌宠实现各自配置 |
| `webui_config.json`(运行时生成) | WebUI 配置 | 运行时生成,避免首次启动报错 |
| `launcher_config.json`(运行时) | live2d_desktop_avatar 启动器 | 运行时生成 |
| `updates/live_stream/config/*.json` | 直播模块配置(开关/房间/Cookie/VTS) | 直播模块独立配置,与主项目解耦 |
| `plugins/*/plugin.toml` | 插件声明(默认 enabled 视插件而定) | TOML 比 JSON 多注释,适合插件元数据 |

**关键权衡**:
- **TOML** vs JSON(plugin.toml):选 TOML。原因:支持注释、类型更丰富、Python 3.11+ stdlib 内置。
- **JSON** vs YAML(其他配置):选 JSON。原因:Python stdlib 原生支持,无 PyYAML 依赖;配置简单无需 YAML 的高级特性。

---

## 十二、已知问题与待完善项

### 12.1 选型相关的待决策点

| # | 问题 | 位置 | 选型决策方向 |
|---|---|---|---|
| 1 | `conversation_manager.handle_ws` 不存在 | main.py:1499 → `/ws` 路由 | 修复或移除 `/ws` 端点 |
| 2 | 记忆系统为 stub | context_manager 内联接口 | 按 `memories_v2.db` 的 5 表 schema 实现 v2 记忆管线(向量检索 + 遗忘衰减 + 联系人图谱) |
| 3 | 插件调度层为 stub | plugin_sdk/plugin_manager/tools/smart_tool_manager | 重建 SDK,恢复 main.py `/tools` 端点,接通 webui 工具代理 |
| 4 | webui 工具代理断链 | webui_server.py `/api/tools/*` → `:8000/tools` | 目标端点不存在,随 #3 一起修复 |
| 5 | screen_monitor 依赖 vision_engine stub | 插件 | 实现 vision_engine,screen_monitor 主动搭话能力生效 |
| 6 | Edge-TTS 引擎未注册 | tts/edge.py | 实现完整,`_build_default_manager` 注册即可 |
| 7 | echo_cancellation 未接入主链路 | 模块 | AEC 是备用能力,当前靠自播窗口过滤;后续接入作双保险 |
| 8 | 顶层多个启动脚本为 stub | avatar_main/gui_main 等 12 个 4 行占位 | 真实入口:start.bat / voice_chat_demo / desktop_avatar,清理占位 |
| 9 | `webui_static/`、`prompts/`、`memory/`、`gui/` 为空 | 目录 | 运行时生成或历史遗留,清理 |
| 10 | `/memory/{id}` DELETE/PUT 为占位 | main.py | 不落库,随 #2 一起修复 |

### 12.2 待决策点(未关闭)

| 决策点 | 现状 | 待选项 | 决策时机 |
|---|---|---|---|
| 向量检索库 | SQLite + embedding 列 | ChromaDB / FAISS | 记忆系统重建时 |
| 本地 LLM | 未接入 | vLLM / Ollama / Llama.cpp | 显存预算足够时 |
| AEC 接入 | 备用 | 接入主链路 | 自播窗口过滤不足时 |
| 情绪分类 | 关键词规则 | mDeBERTa 零样本 | 准确率不达标时 |

---

## 十三、技术白皮书:设计原则与关键技术

### 13.1 设计原则(选型层面)

1. **低延迟优先,渐进式开口**(P0):对话延迟优化的核心思想不是"全部生成完再播",而是"边说边听、边想边播"——LLM 逐字符、TTS 逐块、播放首段 300ms 即开口,三层流水线把用户感知延迟压到最小。
2. **多级 fallback 永不静默失败**(P1):ASR(FunASR→whisper→mock)、TTS(引擎级自动回退)、LLM(离线模板回复),任何一环故障都给出可用输出。
3. **对话体验 > 严格时序**(P1):插话不打断、语音段超时入队不丢弃、短段合并——"宁可排队听完,不可丢用户的话"。
4. **回声自防**:自播窗口过滤 + NLMS AEC 双保险,AI 不回应自己的声音。
5. **显存按需**(P0):8GB 笔记本上引擎模块可独立加载/释放,GPU 资源用在哪层完全可控。
6. **引擎可插拔**(P1):TTS 抽象基类 + 注册表、LLM provider 切换、VAD 从 Silero 迁移纯能量的演进路径,均体现"配置驱动,代码不动"。
7. **依赖最小化**(P2):移除 Silero/QWebEngineView/GLFW/pygame/pyautogui,能不引的依赖坚决不引。
8. **表现层认知化**:直播子模块将"认知状态"逐层映射为表情/动作/头部运动,数字人从"会说话"走向"有状态"。

### 13.2 关键技术选型点

| 技术 | 选型 | 选型理由 |
|---|---|---|
| 流式增量 ASR | 3200 样本触发 + 2/3 重叠滑窗 + 前缀 diff | 整段识别延迟过高,违反 P0 |
| 动态 VAD 尾音保护 | 短句自动加 hangover,防切尾;噪声地板自适应 | 纯能量 VAD 的核心增强,弥补无 ML 模型的劣势 |
| 三正弦口型模型 | 不同频率正弦叠加模拟自然开合,平滑系数 0.3 | 比单正弦更接近自然开合 |
| 表情差分淡出 | 表情只改变"与基线的差",800ms 淡出恢复,口型参数豁免 | 比硬切自然,口型豁免避免淡出期间口型失真 |
| 认知→表现映射 | 系统状态/张力/带宽/注意力 → 表情/动画/HeadX/Y 缓动 | 规则引擎可解释、零显存、可调 |
| NLMS 回声消除 | 4096 阶逐样本自适应 + 双讲检测,ERL 估计 | 备用能力,自播窗口不足时接入 |
| 双频段 AGC | 1k 以下目标 0.6、高频 0.4,限增益 10dB,适配语音频谱 | 单频段 AGC 不适配语音频谱 |
| CUDA graph 预热 | TTS 流式首块延迟 4-6s → 0.4s | faster-qwen3-tts 的核心优势 |
| zlib 压缩 WS | >512B 消息自动压缩,降低桌宠同步带宽 | 适合长直播场景 |
| seq 排序 dispatcher | 并行 TTS 结果按序输出,句子间零卡顿 | 并行合成 + 顺序输出,延迟与一致性兼得 |

### 13.3 性能基线(实测/设计目标)

| 指标 | 目标 | 选型依据 |
|---|---|---|
| TTS 流式首块延迟 | ~0.4s(CUDA graph 预热后) | P0 低延迟硬指标 |
| 播放首响门槛 | `tts_first_chunk_min_ms` = 300ms | 人耳感知"即时"的阈值 |
| 插话响应 | 播放期音量遮蔽 >1.6× 判定,锁超时 2s 转排队 | 防把 AI 回声当插话 + 不丢弃用户语音 |
| 长直播 | 3-4 小时(能量/休息/冷场/话题自律) | 模拟人类疲劳,避免机械感 |
| 弹幕回复延迟 | 2s 防刷屏节流 | 防刷屏 |

---

## 十四、运行手册与端口速查

### 14.1 启动方式选型

**单 bat 启动原则**(P0 用户偏好):主入口 `start.bat` 自检依赖 → 启动 WebUI,WebUI 以子进程管理 backend/live2d。

```bat
:: 主入口(WebUI 总控制台 :5000,自动装依赖/建目录/开浏览器)
start.bat

:: 语音 Demo(必须 -X utf8 防 Windows 编码崩溃)
python -X utf8 对话DEMO\voice_chat_demo.py
python -X utf8 对话DEMO\demo_webui.py          (:5050 控制台)

:: 后端直启
python -X utf8 backend\main.py                 (:8000)

:: 桌宠
python live2d_qt_avatar.py
python live2d_desktop_avatar.py
cd desktop_avatar && npm start                 (Electron)

:: 直播模块(配置 + 插件启用后)
python updates\live_stream\install_deps.py
```

**关键权衡**:
- **`-X utf8`** vs 默认编码:必须 `-X utf8`。原因:Windows 默认 GBK 编码会导致中文路径/输出崩溃。
- **WebUI 子进程管理 backend**:60s 就绪等待 + 最多 3 次自动重启。原因:backend 启动慢(模型加载),WebUI 需耐心等待 + 容错。

### 14.2 端口速查

| 端口 | 服务 | 协议 | 选型理由 |
|---|---|---|---|
| 5000 | webui_server.py Flask 主控制台 | HTTP /api/* + SSE | 控制台主入口 |
| 5050 | demo_webui.py Demo 控制台 | HTTP + SSE 日志 | Demo 独立控制台 |
| 8000 | backend/main.py FastAPI | HTTP + WS /ws/avatar /ws/stream | 主对话链路 |
| 8081 | live2d_desktop_avatar 内嵌静态服务器 | HTTP(live2d_viewer.html) | 桌宠内嵌查看器 |
| 9872 | GPT-SoVITS WebUI(live_stream TTS) | Gradio | 直播 TTS |
| 18765 | avatar 备用 Live2D 查看器 | HTTP | 备用 |

### 14.3 进程关系选型

- **WebUI(5000)以子进程管理 backend(8000)/live2d**:带 60s 就绪等待 + 最多 3 次自动重启。选型理由:统一管控,容错。
- **live2d_desktop_avatar 会自拉 backend**(uvicorn 启动 `backend.main:app`):选型理由:一体化启动器,用户单点击即可全启动。
- **voice_chat_demo 与 backend 引擎进程内直连**:不经过任何服务端口。选型理由:追求最低延迟,无 HTTP 开销。
- **demo_webui(5050)以子进程管理 voice_chat_demo**:SSE 转发日志。选型理由:Demo 控制台独立于 Demo 本身,便于观察。

---

## 十五、演进路线

### 15.1 短期(恢复完整功能)

| 演进项 | 当前 | 目标 | 选型路径 |
|---|---|---|---|
| 重建记忆系统 | stub | v2 多实体 | 按 `memories_v2.db` 的 5 表 schema 实现 v2 记忆管线(向量检索 + 遗忘衰减 + 联系人图谱) |
| 重建插件调度层 | stub | 完整 SDK | 实现 plugin_sdk/plugin_manager/tools,恢复 main.py `/tools` 端点,接通 webui 工具代理 |
| 修复 `/ws` 路由 | AttributeError | 修复或移除 | 修复 `handle_ws` 或移除 `/ws` 端点 |
| 注册 Edge-TTS 引擎 | 未注册 | 注册可选 | `_build_default_manager` 注册,完善 TTS 引擎切换面 |

### 15.2 中期(体验深化)

| 演进项 | 当前 | 目标 | 选型路径 |
|---|---|---|---|
| 接入 echo_cancellation | 备用 | 主链路双保险 | 接入 echo_cancellation 到主链路(自播窗口 + AEC 双保险落地) |
| vision_engine 实现 | stub | 完整 | screen_monitor 主动搭话能力生效 |
| 情绪分类升级 | 关键词规则 | 零样本模型 | 预留 mDeBERTa,准确率不达标时切换 |
| 记忆→人格动态演化 | 无 | 联动 | 记忆影响性格与话题 |

### 15.3 长期(智能化)

| 演进项 | 当前 | 目标 | 选型路径 |
|---|---|---|---|
| PROACTIVE/ACTIVITY 开关 | 无 | 数字人主动发起话题 | 蓝图 4.1 落地 |
| 直播子模块与主项目融合 | 独立 | 认知控制器接入桌宠 | 认知控制器的张力/注意力输入接入桌宠 |
| 多模态融合 | generate_with_image 已具备 | 视觉感知进入对话上下文 | 系统已具备 `generate_with_image`,扩展到对话 |
| 端到端人格一致性 | 部分 | 统一调度 | 声音克隆(语音克隆引擎已具备)+ 情绪音色 + 表情差分统一调度 |

### 15.4 选型原则落实检查

| 原则 | 落实点 | 验证 |
|---|---|---|
| 本地优先 + 显存可控 | ASR/TTS/LLM/VAD 独立模块,/modules/start\|stop 按需加载 | ✅ |
| 低延迟流水线 | LLM 逐字符 + TTS 逐块 + 播放首段 300ms | ✅ |
| 多级 fallback | ASR 3 档 + TTS 引擎级回退 + LLM 离线模板 | ✅ |
| 引擎可插拔 | TTSManager 注册表 + LLM provider 切换 + VAD 演进 | ✅ |
| 依赖最小化 | 移除 Silero/QWebEngineView/GLFW/pyautogui | ✅ |

---

*本文档基于 YHLZ2.0_架构与技术白皮书 v1.0 与仓库实际依赖生成,按原白皮书 15 章结构组织,后续重大选型变更需同步更新。*
