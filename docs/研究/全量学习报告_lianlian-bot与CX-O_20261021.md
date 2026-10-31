# 双项目全量学习报告：lianlian-bot × CX-O

> 日期：2026-10-21　｜　用途：技术学习与选型参照（配套《可借鉴技术报告》）
> 代码来源：本机 shallow clone 于 `research/lianlian-bot`、`research/CX-O`
> 引用记号：`路径:行号` 均指该 clone 内的真实文件；`docs/technical.md:N` 指 CX-O 自带技术文档
> 说明：两个仓库均**未附 LICENSE 文件**（默认保留所有权利），代码只能读、不能直接搬。

---

## 0. 一页纸结论

| 维度 | lianlian-bot | CX-O |
|---|---|---|
| 本质 | **一个人的单机语音陪伴体**：一套 3.2k 行的 asyncio 主循环 | **一整套 AI 角色操作系统**：5 个服务 + 20 余个子系统，23 万行 |
| 代码量 | 7.2k 行 Python（含工具/UI） | 约 **24 万行**（后端 8.1 万 + 测试 5.7 万 + 前端 5.8 万 + 其余 4.4 万），不含引擎/模型/二进制 |
| 依赖重量 | llama.cpp + SenseVoice + Kokoro，**全本地、零联网** | vLLM/TRT-LLM + SenseVoice + CosyVoice3/Qwen3-TTS + Weaviate + Electron |
| 部署 | 解压即跑（Windows），24~45 秒冷启动 | 需要 GPU 推理栈、docker、多端口编排，按天级部署 |
| 最大价值 | **每一处延迟与鲁棒性都写清了"为什么"**，可直接照抄的工程判断 | **机制密度极高**：投机预填充、双向打断三态、记忆衰减、梦境引擎、契约优先 |
| 最大问题 | 单人项目，无测试、平台耦合 Windows、硬编码 | 体量与复杂度失控风险；文档与实现之间存在漂移；同样无许可 |
| 与你（YHLZ）的关系 | 你的"语音陪伴"链路的**轻量参照实现** | 你的"数字生命"路线的**重型上限样本** |

**一句话**：lianlian 教你**怎么把一条语音链路做到 0.3 秒且不炸**；CX-O 教你**把一个角色做成平台时需要哪些子系统，以及用什么规约管住它**。

---

## 1. 仓库事实

### 1.1 元数据

| 项 | lianlian-bot | CX-O |
|---|---|---|
| 仓库 | `MingBeifen/lianlian-bot` | `nbllt666/CX-O` |
| 最新提交 | 2026-09-19 03:25（`Update 功能汇总.md`） | 2026-10-11 22:21（`fix: 修复训练进程停止、WebSocket 错误处理及文件上传等问题`） |
| 跟踪文件 | 73 | 1806（含 Git LFS 二进制，如 `CX-O-VoiceWorkStation/tools/ffmpeg/*.dll`） |
| 许可 | 无 LICENSE | 无 LICENSE（子模块 CosyVoice/SenseVoice/DiffSinger 各自有许可） |
| 文档 | `README.md` 881 行 + `功能汇总.md` 152 行 + `README-DEPLOY.md` | `AGENTS.md` 200 行 + `docs/` 6 篇（`technical.md` 1125 行最全）+ 各服务 DEPLOY 文档 |
| 测试 | 仅 `tools/selftest.py` 等手工自检脚本 | `CX-O-SERVER/tests` 246 文件 5.7 万行 + 根 `tests/` 9.2k 行 + 前端 vitest/E2E |
| AI 协作规约 | 无 | **AC 范式 v6**：`.trae/rules/rules-0~7`、变更文档闸门、`public/` 契约保护 |

> 注：clone 时 CX-O 因 Git LFS smudge 在受限环境下失败，需 `git config filter.lfs.smudge 'git-lfs smudge --skip -- %f'` 后重签出，否则只能拿到 1017/1806 个文件——**这也解释了为什么直接 `git clone` 后目录树看起来缺了一大半**。

### 1.2 代码分布（行数，仅统计源码/文档）

**lianlian-bot**

| 目录 | 行数 | 内容 |
|---|---|---|
| `core/` | 3193 | 主循环、音频、VAD、ASR、LLM、TTS、记忆、主动性 |
| `live2d/` | 1788 | VTS 协议驱动、Win32 桌宠窗口、自渲染渲染器、进程桥 |
| `webui/` | 1199 | aiohttp 服务 + 原生 JS 控制台 |
| `tools/` | 1008 | 体检、自检、模型配置生成、打包 |
| `_vendor/` | — | 自带 sounddevice + silero-vad（不改用户 venv） |

**CX-O**

| 目录 | 文件 | 行数 | 内容 |
|---|---|---|---|
| `CX-O-SERVER/server` | 317 | 80818 | FastAPI 主服务：api/core/handlers/services/protocol |
| `CX-O-SERVER/tests` | 246 | 56866 | 后端测试（含 E2E、延迟验证） |
| `APP-Frontend/src` | 265 | 51621 | React 18 + TS：pages 98 文件、hooks 26、avatar 35 |
| `APP-Frontend/electron` | — | ≈6500 | 主进程：三窗、托盘、IPC 白名单、BLE、电脑控制插件 |
| `CXO-ModelStation` | 59 | 12969 | 训练工作站（So-VITS-SVC / MeloTTS / 三引擎语料） |
| `CX-O-VoiceWorkStation/workstation` | 32 | 6900 | 作曲/翻唱/SVC 推理 |
| `public` | 73 | 6563 | 三层契约（schema 48 / interface_stub 24 / config_template 13） |
| `CXO-EvalKit` | 25 | 5449 | LLM 评测框架（memory/latency/quality 三维） |
| `CXO-NekoAdapter` | 21 | 3143 | 适配层（细节见 §3.11） |
| `CXO-Tuner` | 24 | 2501 | 自我进化（QLoRA + DPO） |
| `docker` | 14 | 2483 | ASR/LLM/TTS 推理容器与启动脚本 |
| 根 `tests` | 44 | 9253 | 跨服务集成测试 |

### 1.3 方法与本报告的边界

**怎么做的**
1. 浅克隆两个仓库到 `research/`（CX-O 需绕开 LFS，见上）。
2. 三路并行深读：lianlian 全部 26 个 `.py`（含 `app.js`/`run.bat`）；CX-O 后端 323 个 `.py`（8.2 万行）；CX-O 非后端部分（前端/工作站/模型站/适配器/评测/docker/CI）。
3. **交叉验证**：只信"文档 + 代码 + 注释"三者一致的部分；凡文档与代码冲突，一律以代码为准并在文中标出（见 §3.14、§2.11）。
4. 关键论断回到代码逐条点开确认（例如 `/api/models/apply` 是否真缺路由、`early_context` 是否真进 `system[0]`、代理是否真被设置）。

**边界（必须说明）**
- **没有运行任何一个项目**。所有性能数字都来自作者文档/注释里的实测，不是本机复测。
- CX-O 的引擎（`engines/`、`DiffSinger/`、`.trae/` 契约）不在仓库内，因此"能不能跑起来"只能从 import 路径推断，未做真实验证。
- 两个仓库都**没有 LICENSE**，本报告只提炼机制，不提供可直接粘贴的代码。
- 行号以本次 clone 的 HEAD 为准（CX-O `ca114c1`，2026-10-11），上游更新后会漂移。

---

## 2. lianlian-bot 全量拆解

### 2.1 定位与产品面

一只叫"恋恋"的桌面语音陪伴体，作者自述**完全由 DeepSeek 生成**。核心承诺是"全程本地、不联网、不花钱"，硬件基线 **RTX 5060 Laptop 8GB**（与你 4060 8GB 同档，因此它的实测数字对你**直接可参考**）。

功能面（`功能汇总.md`）：
- 语音 + 键盘双输入合流、插话打断、半双工兜底
- 流式应答（按标点分句 → 逐句合成 → 边播边生成）
- 长期记忆（三层 + 自动抽取 + 自动去重）
- 主动性（安静久了搭话、早上问候、饭点提醒、退避）
- Live2D 双方案：VTube Studio 驱动 / 自渲染透明桌宠
- Web 控制台（会话、记忆管理、形象切换）
- 统一 `models.json` 模型配置 + 可移植部署

### 2.2 结构

```
run.bat → core/voice_chat.py (VoiceChat)
            ├── core/audio_io.py   MicListener（采集线程）/ Player（播放）/ 设备诊断
            ├── core/vad.py        silero → webrtcvad → energy 三级
            ├── core/asr.py        SenseVoice（modelscope 本地缓存）
            ├── core/llm.py        OpenAI 兼容（llama.cpp / Ollama）+ 情绪/动作分类
            ├── core/tts.py        Kokoro v1.1-zh / Edge / GPT-SoVITS
            ├── core/memory.py     SQLite + bge + numpy 检索 + 自动抽取
            ├── core/proactive.py  四层闸门主动发起
            ├── live2d/*           VTS 驱动 / native_pet 渲染 / TCP 桥
            └── webui/server.py    aiohttp + 静态前端
```

### 2.3 并发模型与主链路

**两种输入，一个队列**（`README.md:824-835`，代码 `core/voice_chat.py:119-166`）：

1. `MicListener` 跑在独立线程（`core/audio_io.py:101-231`），用 VAD 切出一句 → `np.ndarray`
2. 键盘线程读到一行 → `str`
3. 两者都塞进同一个 `asyncio.Queue`（`_push`/`_deliver`，`core/voice_chat.py:147-165`），主循环 `await queue.get()` 谁先来算谁
4. 主循环按类型分派到 `handle_audio` / `handle_text`（`:498` / `:518`）

**打断**用 `asyncio.Event`（`:579` `_interrupt_watcher`）：麦克风在说满 160ms 时 `set()`；打字则**先判断她是否正在说话**再 `set()`——README 明确记了这个竞态：不判断的话"刚收到这句就把自己那一轮取消了"（`README.md:828-830`）。触发后 `player.stop()` 清空播放队列 + cancel 当前任务。

**回声治理**（`core/voice_chat.py:79-109`，`EchoGuard`）：
- `remember(text)` 记录她最近说过的 **8 句**
- `is_echo(text, playing_recently)` 三条判据：播放中且识别文本 **≤6 字**直接判回声 / 子串包含 / `difflib` 相似度 ≥0.7
- 默认 `BARGE_IN=0` 半双工：她说话期间自动闭麦，从根本上杜绝自问自答
- 保险：连续 3 次识别出自己的碎片 → **运行时把 `barge_in` 改成 False**（`:504-512`），此后走半双工

这是**用工程手段绕开 AEC** 的典型取舍：不做回声消除，改成"说话时别听"。代价是不能自然插话，且「播放中 + ≤6 字」会误杀用户真的回应一句"好的"（`:102-103`）。

### 2.4 延迟工程（最值得学的一节）

实测（作者 5060 Laptop，`功能汇总.md:37-45`）：

| 环节 | 实测 |
|---|---|
| VAD 断句 | 80% 命中 / 静音 0 误报 |
| ASR（2.5s 语音） | **0.16s** |
| LLM 首字（热态） | **0.08s**，显存 4.9GB |
| TTS 每句 | 0.29~0.65s |
| **首句出声** | **0.29~0.65s** |
| 冷启动 | 24~45s |
| 显存总占用 | **6.6 / 8 GB** |

三个关键手段：

1. **按标点攒句**（`core/voice_chat.py:44-76` `sentences()`）：不是等整段生成完，而是流式 token 攒够就切一句送合成（`:470`）。切分阈值是三级：
   - 硬标点 `。！？!?…；;\n` → **满 2 字**即切
   - 软标点 `，,、：:～~` → 满 **16 字**才切
   - 无论如何满 **40 字**（`MAX_CHUNK`）硬切

   这是"首句 0.3s"的直接来源；代价是 LLM token 流在 TTS 合成期间会被反压（一句一 `await`）。
2. **记忆块放在历史之后**（`core/llm.py:170-178`）：`messages = history + [system:hint] + [system:memory_block] + [user]`。前缀（人设+历史）保持不变 → **KV 缓存照命中**，只有记忆块与本句要重新 prefill（实测 0.26s）。若塞进开头 system，每轮都要重算整个上下文。
3. **辅助分类不阻塞主链**：情绪/动作分类各走一次 `temperature=0` + GBNF 约束 + `max_tokens=6` 的小调用，失败即 `neutral`/`none`（`core/llm.py:130-164`）。分类与主回复并行，不进关键路径。

### 2.5 语音前端（VAD 与麦克风鲁棒性）

`core/vad.py` 三级降级，优先级写在文件头注释（`:3`）：

| 级 | 类 | 适用 |
|---|---|---|
| 1 | `SileroVAD`（`:76`） | 神经网络，嘈杂环境最稳；有 torch 就能用 |
| 2 | `WebrtcVAD`（`:57`） | 20ms 分块投票，轻量 |
| 3 | `EnergyVAD`（`:22`） | 零依赖保底，带 150Hz 高通（`:34`）+ 噪声地板自适应（说话时 α=0.998 几乎不更新） |

降级只在**构造失败**时发生（`make_vad`，`core/vad.py:137-162`）：`import torch/silero_vad` 失败、`load_silero_vad()` 失败、采样率不是 16k、`import webrtcvad` 失败。显式指定 `VAD_BACKEND=silero` 时失败就抛错，不偷偷降级——**"自动"和"指定"两种语义分开**，这点值得学。

`MicListener._calibrate`（`core/audio_io.py:156-196`）在开机时**先安静听 1 秒**，按实测底噪自动定 VAD 门槛——作者这台机器环境噪声 -24dBFS，不校准必然误触发。另有全部"踩坑→自动化"的清单（`功能汇总.md:99-115`）：

- 麦克风打不开 → 给出权限路径 + 设备号，**自动降级成键盘模式**继续用
- 麦克风信号太轻 → `INPUT_GAIN` 数字放大
- 底噪 < -95dB → 直接警告"没送声音进来"
- SenseVoice 幻觉（"请不吝点赞"）→ `is_noise()` 过滤（`core/asr.py:35`）
- 咳嗽短音 → `MIN_SPEECH_MS` 丢弃
- `funasr` 每次启动联网校验 → 改成直读 modelscope 本地缓存（`core/asr.py:57-77`），离线秒起

### 2.6 记忆系统

**三层**（`README.md:168-175`）：

| 层 | kind | 用法 |
|---|---|---|
| 档案层 | `profile` | 每轮**全量注入**，不检索 |
| 事实层 | `fact`/`preference` | 向量检索 |
| 事件层 | `event` | 向量检索 + 时间衰减 |

**打分公式**（`core/memory.py:35`）：

```
score = 0.75 × 余弦相似度 + 0.15 × exp(-Δt/30天) + 0.10 × 重要度
```

取 Top-8，**不做相似度阈值过滤**——理由是中文嵌入相似度基线高（不相关句子也能到 0.59），卡阈值必然误杀，交给大模型自己判断相关性（`README.md:182-183`）。

**嵌入选型有实测对照**（`README.md:187-194`）：`nomic-embed-text` 中文 R@1 = 1/5（不可用）→ `bge-small-zh` 3/5 → **`bge-base-zh-v1.5` 6/7、R@3 7/7**。CPU 单查询 43ms，1 万条记忆暴力点积 1.65ms，**不需要向量数据库**。

**自动抽取的三道闸**（这是本文档里最值钱的工程细节，`README.md:242-293`）：
1. 严格提示词 + **温度 0**（"你是抽取程序不是角色"）
2. **GBNF 语法约束**：llama.cpp 在采样层强制格式，结构上不可能输出非法格式
3. **归一化重叠校验**（`core/memory.py:528-545`）：抽出的内容必须有足够比例的字来自原话（去掉"哥哥"与标点再比字符集），编造直接丢。阈值 `MEMORY_OVERLAP` **默认 0.45**（README 正文写 30%，以代码为准）；此外还有寒暄/长度/引号过滤（`:272-311`）

配套经验：
- **不用 JSON 用行格式**：`FACT|0.7|内容` 五行语法就够，解析是 `split("|", 2)`，token 更省、更快、不可能解析失败（`:263-272`）
- **问句闸门**：含"什么/吗/呢/谁/还记得"一律不抽取（问句里没有新事实，模型只能编）
- **去重保留信息更全的那条**：相似度 >0.90 时长者优先（曾把"橘猫"覆盖成"猫"）
- **时机**：自动写入放在"她正在播语音"的那几秒——那时 GPU 空闲，**零延迟成本**（`:240`）

### 2.7 主动性

核心设计一句话：**规则决定"说不说"，LLM 只管"说什么"**（`README.md:422-430`）。原因是让 LLM 自己决定要不要开口时，它永远选安全项（沉默），而且连 `<SILENT>` 都拼错。

四层闸门（`core/proactive.py:161-184`，便宜的先查）：

| 层 | 检查 |
|---|---|
| 硬规则 | 总开关、是否在对话中、安静够久（默认 600s）、静默时段（0-7 点） |
| 频率 | 每小时 ≤2、每天 ≤12、间隔 ≥8 分钟 |
| **退避** | 没被理一次，间隔 ×2（`gap = min_gap × backoff**unanswered`，`:172`）；连续 3 次没理当天闭嘴 |
| **环境** | 房间太安静（你可能不在）就不自言自语 |

内容侧还有三道代码校验（`:69`、`:278`、`:350`）：
- **静默变体**：任何 `<sil...>` 都当沉默
- **编造动作**：检测"我刚帮你泡好咖啡"这类她做不到的事 → 重试一次，再犯就不说
- **相似度去重**：与上次的话 Jaccard >0.55 就重试

素材来源明确：记忆库最近 12 条 + 最近 6 轮对话 + "上次你说的是…（别再说这个）" + 当前时间与角度清单（A 问他在干嘛 / B 提记得的事 / C 说想法 / D 顺着聊）。实测能说出"明天要考驾照啊～那你复习一下啦～"这种真用了记忆的话。

### 2.8 形象与桌宠

两条路径（`PET_BACKEND=vtube|native`）：

**A. VTube Studio 驱动**（`live2d/avatar.py`）：走 VTS 插件协议，播放电平 → `MouthOpen` 参数，情绪 → 表情文件或热键。渲染交给别人，项目只做"驱动"。

**B. 自渲染**（`live2d/native_pet.py` 736 行 + `native_pet_link.py` 200 行）：live2d-py（Cubism Native Core）+ GLFW，**逐像素透明**置顶窗口，不装 VTS、不用色键抠图。主程序与渲染器分进程，用 TCP 推 30fps 状态。

动作调度是**四层叠加**（`README.md:642-655`），对标 Neuro-sama：

| 层 | 内容 | 实现 |
|---|---|---|
| 1 绑定 | 拆分部件 + 物理 | 模型自带 `.moc3` / `physics3.json` |
| 2 动作库 | `motion3.json` | `animations/` 下 10 个动作 |
| 3 调度 | 状态机决定播哪个 | 说话→口型+身体摆动；情绪→反应动作；空闲→随机待机 |
| 4 语义 | LLM 动作标签 | 回复文本 → GBNF 分类（nod/wave/think/...）→ 触发 |

优先级：情绪反应/动作标签 > 待机动作；**说话时动作全部暂停**（动作带嘴部曲线会抢口型），没播的排队，说完立刻补上。

细节里的经验：
- 语音 RMS 只有 0.05~0.2，所以口型映射用 `(电平 × 增益) ** 0.7`（默认增益 6）
- 鼠标穿透用窗口过程子类化（`WM_NCHITTEST` 返回 `HTTRANSPARENT`），**不用** `WS_EX_TRANSPARENT`（会破坏透明边缘）
- 没有 `pose3.json` 的模型会"四只手"：检测不到 pose 文件就锁定 A 组手臂、隐藏 B 组

### 2.9 Web 控制台与配置系统

`webui/server.py`（aiohttp + WebSocket + 原生 JS，无 CDN、只监听 127.0.0.1），三页：对话（含浏览器实时语音输入 16k PCM 回流服务端）、记忆（改权重/删除/语义搜索/换嵌入模型后一键重算向量）、Live2D（扫描 model3.json 热切换）。

配置分两层：`.env`（50+ 项，`core/config.py` 360 行）+ `models.json`（**优先级更高**，统一管 LLM/TTS/嵌入/ASR/Live2D 路径，`tools/gen_models.py` 生成、`tools/sync_models.py` 同步进 bat）。

### 2.10 工程健壮性清单（可直接对照抄的）

| 场景 | 处理 | 位置 |
|---|---|---|
| 麦克风权限被拦/打不开 | 可操作提示 + 自动降级键盘模式 | `core/audio_io.py:143` |
| 电平差异极大 | 开机静听 1s 自动校准 | `core/audio_io.py:156` |
| 环境噪声大 | 优先 silero VAD | `core/vad.py:76` |
| ASR 幻觉 | `is_noise()` 过滤 | `core/asr.py:35` |
| `funasr` 联网校验 | 直读 modelscope 缓存 | `core/asr.py:57` |
| 旁白/`（动作）`被朗读 | TTS 层正则剥除 + 提示词双管 | `core/tts.py:13-38` |
| 长句标点爆炸 | 连续 3 个以上标点压成一个 | `core/tts.py`（clean 流程） |
| `keep_alive` 不支持 | 首次失败自动关掉该项重试 | `core/llm.py:75-103` |
| 记忆检索失败 | 本轮不带记忆，继续对话 | `core/llm.py:115-119` |
| 情绪/动作分类失败 | 返回 neutral/none，不影响主流程 | `core/llm.py:141-146` |
| 自问自答 | 默认半双工 + 回声自愈 | `core/voice_chat.py:86` |
| 模型换机器 | 路径相对化 + 打包/一键装/体检三工具 | `tools/*` |

### 2.11 缺陷与风险（逐条核对过代码）

**结构性**

- **无 LICENSE** → 法律上不可复用，只能作设计参考
- **无自动化测试**：只有 `tools/selftest.py`（合成→识别→大模型三段链路）与 `mic_test.py`（人工听）
- **Windows 深耦合**：设备诊断、`venv` 路径、Win32 窗口控制、`run.bat` 全写死（`webui/catalog.py:13-15` 里直接是 Steam 的 VTS 目录、`live2d/native_pet.py:742-743`、`tools/selftest.py:14`）
- **单进程单会话**：`VoiceChat` 全局单例，没有多用户/多角色概念

**功能性 bug（有代码证据）**

| # | 现象 | 证据 | 影响 |
|---|---|---|---|
| 1 | **Web 端换模型/改形象参数点了没反应** | `webui/static/app.js:433` POST `/api/models/apply`，而 `webui/server.py:370-389` 路由表里没有这条；`voice_chat.apply_llm/asr/tts/vad/memory/pet`（`:333-405`）因此全成死代码 | 中：控制台的"改配置"能力实际不可用 |
| 2 | **情绪感知链断裂** | `core/emotion.py:53,142` 的 `EmotionState`/`user_hint` 全项目无人 import；`asr.last_emotion` 只写不读；`voice_chat.py:470` 调 `stream_reply(user_text)` **从不传 hint** | 中：语音里听出来的情绪既不进 prompt 也不改语速 |
| 3 | **自渲染桌宠在正常对话轮次收不到表情** | `voice_chat.py:486` `if self.avatar is not None:` 把 `_avatar_emotion` 挡住了，而该函数本身是支持 `native_pet` 的（`:408-446`）；只有 `say()`（`:460`）会更新 | 中：native 模式表情只在主动说话时变 |
| 4 | **GSV 分情绪参考音频不可达** | `tts.synth` 支持 `emotion` 参数（`core/tts.py:335`），所有调用点都不传 | 低 |
| 5 | **去重合并写错 embedding** | `core/memory.py:292-299` 保留旧内容时仍写入新内容的向量 | 低-中：向量与文本错位，检索会漂 |
| 6 | **`self.turn` 三方共用竞态** | 主循环（`:648`）、主动循环（`:572`）、网页发送（`webui/server.py:314`）都写同一个字段；主动轮被打断后 `_barged` 无人消费（`:575-576` vs `:657-659`） | 中：偶发"轮次互相 cancel" |
| 7 | **没麦克风时主动性永不触发** | `proactive.py:181` 用 `ctx.noise_rms < 0.0015` 判定"房间没人"，纯键盘模式下 RMS 恒 0（`voice_chat.py:557`），`BotContext.busy` 也恒为 False | 低：键盘用户永远不会被主动搭话 |
| 8 | **SQLite 并发无锁** | 连接 `check_same_thread=False` 且被多个 `to_thread` 共用；`recall` 每次 `SELECT *` 全表再 numpy 打分 | 低（万级记忆以内够用） |
| 9 | **WebUI 无鉴权** | 仅监听 127.0.0.1；`server.py:205-216` 的预览接口路径校验弱（放行任何含 `Live2DModels` 子串的路径）；`WEBUI_HOST` 可配 0.0.0.0 | 低 |
| 10 | **被打断那一轮的内容永久丢失** | `turn.cancel()` 发生在 `_stream_out` 的 `async for` 中，而 history 只在流正常结束后追加（`core/llm.py:190-193`） | **中-高**：barge-in 越频繁，上下文断档越多 |
| 11 | **silero 的 RNN 状态从不复位** | `core/vad.py:102-105` 直接 `model(tensor, 16000)`，全文件无 `reset_states()` | 中：跨句/跨静音状态累积，长会话 VAD 会变钝 |
| 12 | **广播串行阻塞主链** | `emit` 串行 `await` 所有 sink（`voice_chat.py:307-312`），WebUI 对每个客户端 `await send_str`（`webui/server.py:89-100`） | 中：慢客户端会卡住 `_stream_out` |
| 13 | **native 推流无背压** | `writer.write(data)` 不 `await drain()`（`live2d/native_pet_link.py:128-133`） | 低 |
| 14 | **时机被提前消费** | `_seen[key]=today` 在生成之前写入（`core/proactive.py:231-242`），生成失败/判重后当天的"早上好/催睡/饭点"机会就没了 | 低 |
| 15 | **`apply_vad` 在事件循环里 join** | `mic.stop()` 内部 `join(timeout=3)`，被 async 方法直接调用（`voice_chat.py:370`） | 低（但会卡 3s） |

> 这九条的价值不在"这个项目菜"，而在于**它把"能跑"和"链路真的接通"之间的差距暴露得很清楚**：README 写得极其诚实（连 `<SILENT>` 拼错都记了），但仍有 3 处主链路上的断点在文档里没提。**结论：任何"文档齐全"的项目，落地前都要按主链路逐段打点验证。**

---
## 3. CX-O 全量拆解

### 3.1 定位

一句话：**把"一个 AI 角色"需要的所有子系统都做了一遍**——实时语音、记忆、知识图谱、多 Agent 协作、直播推流、声音克隆、AI 作曲、桌面宠物、自主生活、自我进化。

自述的九项核心能力（`docs/technical.md:40-52`）：实时语音对话（全双工、首包 <300ms）、Live2D/VRM 双引擎形象、三层记忆+图谱+蒸馏、ACP 多 Agent、OBS 四源直播、声音克隆与训练、AI 作曲、桌宠多开、自我进化。

这不是"项目"，是**平台**。它的学习价值在于**子系统清单与它们之间的边界**，而不在某一处实现。

### 3.2 服务拓扑

| 组件 | 技术 | 端口 | 职责 |
|---|---|---|---|
| CX-O-SERVER | FastAPI/uvicorn | 8000 | 统一后端：WS Gateway + REST + ASR + TTS 单体 |
| APP-Frontend | React 18 + TS + Vite + Electron | 3100 / Electron | 管理界面、聊天、直播、作曲、桌宠 |
| CX-O-VoiceWorkStation | FastAPI | 8200 | 作曲/歌声合成/SVC 翻唱/音域分析自动降 key |
| CXO-ModelStation | FastAPI（单 worker） | 8300 / 3300 | So-VITS-SVC + MeloTTS 训练、三引擎语料生成，另有 Electron 桌面版 |
| CXO-Tuner | FastAPI | 8310 | 自我进化（QLoRA + DPO） |
| CXO-EvalKit | FastAPI | 8320 | LLM 评测（memory / latency / quality） |
| asr-sensevoice | Docker/FunASR | 8005 | 流式识别 + FSMN-VAD + cam++ 声纹 |
| cosyvoice-tts | 独立 conda | 8094 | CosyVoice3 主引擎（克隆/情感），OpenAI 兼容 `/v1/audio/speech` |
| voicedesign-tts | vLLM-Omni | 8091 | 无参考音频的音色设计 |
| qwen3-tts-base | vLLM-Omni | 8093 | TTS 降级兜底 |
| llm | Docker/vLLM 或 TRT-LLM | 8080 | 对话推理 |
| Weaviate | 外部 | 8080 | 向量库（可选） |

> 值得注意：**TTS 有三条运行时（voicedesign / cosyvoice / qwen3_base）并按"有没有参考音频"自动路由，失败逐级降级**（`technical.md:243`）。这是把"引擎不可用"当成常态来设计，不是当成异常。

### 3.3 后端骨架

**启动顺序**（`server/main.py` 的 `lifespan`，`technical.md:124-140`）：配置 → 模型路由 → 记忆（同步/异步）→ 上下文 → ACP → LLM 客户端 → 蒸馏 → 副模型路由 → MCP/工具注册 → 向量库同步 → 提醒/离线 WS → 批量衰减/任务调度 → CXFC 插件 → ASR/TTS（embedded/remote 含降级）→ **预热**（共享 HTTP 客户端、CosyVoice3、LLM/Embedding）。

**双网关**：
- REST：`/api/v1/...`，**实测 36 个路由模块 / 37 次挂载**（agents/chat/memory/graph/tools/config/stats/backup/archive/anythingllm/distillation/multimodal/vector/service/acp/cxfc/admin/audio/avatars/live/face/voiceprint/meeting/cluster/vision/autonomy/dream/physio/tuner…）。注意：`AGENTS.md:92` 写的是"19 个 router"，**与实际不符**。
- WS：`/ws`（action 协议）与 `/ws/live`（二进制音频）两条端点，消息 `{action, request_id, data}` → `ACTION_HANDLERS` → `{action, request_id, ok, data}`。uvicorn workers 默认 1，后台副作用靠 `core/singleton.SingleLeaderGuard` 做单 leader 去重（`server/main.py:130-147`）。

**action 域划分**（`technical.md:151-165`）：chat / memory / tools / plugin / context / acp / mcp / config / metrics / system / **voice**（`voice.dual_stream`、`voice.partial`、`voice.tts_chunk`、`voice.prefill_started`、`voice.speaker`、`voice.voiceprint_result`）/ danmaku / events。

> 这套"action 即能力域"的命名法比"一个 `/chat` 加若干参数"更好扩展，也更适合前端做类型分发——**是本次学习里最可直接借用的接口设计习惯之一**。

**一个 Windows 上的真实血案（`server/main.py:13-50`）**：httpx 在 Windows 上会读系统代理，导致本地 127.0.0.1 请求被绕进代理。代码里做了 monkey-patch，`trust_env=False` 与 `proxy=None` **必须同时设**——只设一个仍会走代理。改之前该请求实测 **23553ms（502）**，改之后 **14ms**。注释里留着完整数据。

> 这条对 YHLZ 直接适用：本机若设过 `HTTP_PROXY`/`HTTPS_PROXY`（或装过代理软件），所有 `127.0.0.1:8081/8321` 的 httpx 调用都可能被拖慢到秒级甚至 502。**排查"偶尔特别慢"时，先查代理，再查模型。**

**启动装配的容错原则**：lifespan 里 20 多个组件逐个 `init_service`，**每个都 try-except 隔离**——记忆挂了不影响 ASR，图谱挂了不影响对话（`main.py:167-1060`）；关闭时按依赖逆序收（`main.py:1062-1183`）。

### 3.4 双流式语音（全项目技术含量最高的一段）

**设计思想**（`technical.md:177-181`）：单工=对讲机；双流式=ASR/LLM/TTS 三流并行、可互相打断。**关键点：链路事件由 ASR 的 Partial（中间结果）驱动，VAD 只做兜底**。

**边听边说**：ASR 边识别边推 Partial 当字幕（`voice.partial`）；LLM 在用户还没说完就开始推理；TTS 边收边合成边推送（`voice.tts_chunk`）。

**投机预填充（Speculative Prefill）**（`:189-193`）：
- 用户说出 **2 个字**（`_trigger_char_threshold=2`）即触发 LLM 推理
- 省掉等 VAD `on_end` 的**约 500ms 静默判定**
- 推送 `voice.prefill_started` 让前端知道"已经在想了"

**双向打断**（`:195-219`）：

*用户打断 AI*：VAD `speech_start` → 立即 `_interrupt_pipeline()` 取消 LLM+TTS、停播；`CancelledError` 时把用户已说的文本**累积到 pending**，下一轮合并，不丢内容。

*AI 打断用户*（`agent_interrupt_user.py`）：用户说话过程中判断是否插话，**三态**：

| 态 | 含义 |
|---|---|
| `INTERRUPT` | 可插话 |
| `CONTINUE` | 用户还在组织语言，等 |
| `IGNORE` | 自言自语，无需回应 |

两种模式：`main_llm`（用主模型直接生成插话内容）或 `independent_llm`（独立小模型只输出三态标记，不占主模型槽位）。

后续演进（这些补丁比原设计更有价值）：
- **提问意图硬闸门**：LLM 判 `INTERRUPT` 后，过一遍确定性检查 `_has_question_or_request`（提问词+祈使词），没有就降级 `IGNORE` → 消除"情绪独白被误当提问"
- **固定搭配剔除**：`_NON_QUESTION_PHRASES` 14 项先剔除（"是不是"类陈述/客套）再做子串匹配
- **最终完整请求触发（Feature B）**：ASR `is_final` 且过闸门 → 主动回一次，解决"短句问完没人理"
- **标签解耦**：`should_interrupt` / `should_reply` / `reply_content` 三分量，语义独立——**空打断不摧毁在途主管线**
- **停顿续接确认**：`REPLY_CONFIRM_S=0.5` 确认用户真说完再兜底，长句内停顿不被腰斩
- **忽略传导**：`REALTIME_VOICE_PROMPT_PADDING` 注入"回应边界"，让主模型对情绪/自言自语可以选择不回应

代码侧还有三处值得抄的工程细节：

- **"人打断 AI"在双流式路径上不做 LLM 判定**：VAD `speech_start` 直接 cancel 流水线（毫秒级），只在 `speech_end` 后留 **1000ms 保护窗**（`handlers/audio.py:315-347`）。**打断要快，不能等模型**；只有半双工/live 路径才走 `ASRInterruptModule` 的 LLM 判定。
- **"AI 打断人"带频控**：`min_speech=1000ms`、`cooldown=3000ms`，且 TTS 还没出声时不判定。
- **判定失败有降级矩阵**（`services/interrupt_llm.py:120-170`）：

| 情况 | 结果 |
|---|---|
| JSON 解析失败但文本含 `INTERRUPT` | `INTERRUPT` |
| 文本含 `IGNORE` | `IGNORE` |
| 其它解析失败 | `CONTINUE` |
| 超时 | `CONTINUE` |
| 其它异常 | `IGNORE` |

> "超时保守、异常沉默"——**失败语义表**比 try/except 更值得抄，因为它是可测试的。

**首包 <300ms 的五个手段**（`:221-230`）：

| 手段 | 量化 |
|---|---|
| 实时语音专用瘦身 prompt（跳过 MemoryRouter/HybridSearch/重型隐藏提示词，只留核心 system + 最近 2 轮） | 省 ~1500 token prefill（100-200ms） |
| 回复限长 `max_tokens=min(agent_max,150)` | 防 LLM 进入长文模式导致 TTS 排队 |
| **TextSmoother** 平滑缓冲（30ms 滑动窗口，把 1-2 字碎片聚成 3-5 字词组） | 用 ~40ms 换音质 |
| TTS **细粒度切片**流式合成（`synthesize_stream_fine`） | 不等整句。**注意口径不一致**：文档写"4 字即切"，代码默认 3 字（`tts_service.py:690`），语音管线实际传 **2**（`handlers/audio.py:735`），clamp 范围 2~5 |
| 首块即推 `voice.tts_chunk(is_final=False)` | 压缩数百 ms |

**一个更隐蔽的技巧：把 system 前缀填到缓存门槛以上**。`REALTIME_VOICE_PROMPT_PADDING` 不是废话填充——vLLM 的 prefix cache 需要前缀 **≥353 token** 才命中，他们把实时语音的 system 段补到 **≥360 token**，于是 TTFT 从 **240ms 降到 60ms**（同一段 padding 还顺带承载"回应边界/忽略规则"）。这是"把缓存机制当成物理常数来设计提示词"的典型案例。

**实测基线**（2026-08-18，`:273-285`）：

| 环节 | 实测 |
|---|---|
| ASR 触发（Partial 阈值 0.15s） | 280-330ms |
| LLM TTFT（预热后） | **50-92ms** |
| TTS 首块 | 245-270ms |
| hift decode（CUDA graph 后） | 67ms → **4ms** |
| **全链路 P50** | **449-610ms**（多数 <600） |
| **全链路 P95** | **637-762ms**（6 轮 ×10 次全部 <800ms） |
| RTF（CosyVoice3 克隆） | 0.13-0.15 |

> 改善幅度：从 P50~1300ms / P95~1785ms 降到上述水平，**46-64%**。硬验收条件是"P95<800ms 且连续 6 轮×10 次全部达标"——**这种把延迟变成可判定验收项的做法，比任何优化技巧都值得学**。

**VAD**（`:252-256`）：三模式 ENERGY / WEBRTC（默认）/ SILERO；双流式下只做兜底，不阻塞 ASR Partial 主流程；`min_silence_duration_ms=150`。注意这个数字：Silero 模式把句尾判定从 500ms 压到 **150ms**，等于白捡 **350ms**——这是"参数级"的延迟优化，不需要改架构。

**ASR 的部署反直觉**（`docker/asr/README.md` 注释）：容器侧 `ASR_DEVICE` **默认 CPU**，因为实测 10ms 音频走 GPU 仍需 116ms——那 116ms 是 funasr `AutoModel.generate` 的固定开销，与设备无关；曾经把 ASR 挤上 GPU0 导致显存爆掉、全链路 P50 恶化到 2.9s。**在 8GB 单卡上，"哪个模型该占 GPU"是一个必须实测的决策，不是直觉。**

**启动预热的三处实测**（`main.py:806-852`）：
- vLLM 冷 TTFT 7.6s、Embedding 冷 1.6s → 后台预热
- **语音 system 前缀 KV 预热：TTFT 444ms → ~30ms**（一次 warm 约 2747 tokens；不预热等于每轮多付 ~320ms）
- 共享 HTTP 客户端预热（连接池建连）

> "预热"不是可选优化：**不预热 = 每轮都付一次冷启动税**。而且预热要预"同一段前缀"，否则等于白 warm（见上一节 padding 那条）。

**TTS 细节**（`:240-250`）：`cross_fade_duration=0.15` 平滑拼接；情感指令由 LLM 生成自然语言 `tts_instruction`（与 `reply_text` 分离）再解析，`[emotion:*]` 标签只作迁移兼容；参考音频统一 `ref_audio_store.py`（`source=prompt` 生成 / `source=file` 外部）；音效标签与过渡词（`transition_text="嗯，"`）两个可开关。

### 3.5 声纹与人脸

**声纹**（`:287-305`）的设计目标很务实：① 实时认出谁在说（未注册标 `spk_N`）；② 说"记住我的声音"即可建档；③ **声纹慢于 ASR 时不让它卡住全双工**。

实现要点：
- `SpeakerClusterer` 维护"注册质心 + 临时簇"合并后的余弦相似度取最大者；临时簇跨 utterance 保留、会话间隔离
- 每句**并行**提交 ASR final 与声纹 embedding，但**只 await ASR**：声纹已就绪 → `speaker_status="ready"`；未就绪 → 先发 final + `pending`（前端显示"(识别中)"），后台补
- **in-flight 上限 `SPK_INFLIGHT_MAX=2`**，超限直接丢弃该句（保持"识别中"由后续更新），**绝不排队阻塞**
- 不"空则回退最近 speaker"跨句错标（避免张冠李戴）

**人脸**（`:316-326`）：注册/匹配/删除，"记住这个人"链路。

> 这一段的方法论是通用的：**给"慢的旁路能力"设计降级态（pending）而不是等它**。任何"锦上添花但会拖慢主链"的功能都该这么接。

### 3.6 记忆系统

**存储**：SQLite `data/memories.db`，单表 `memories`（`technical.md:352-373`）：

```
type(long_term/short_term/permanent/dream) content vector_id metadata
importance(1-5) importance_score(0-1) decay_type(exponential/ebbinghaus/zero/dream)
decay_params reactivation_count emotion_score permanent psychological_age
tags created_at updated_at archived_at is_deleted source workspace_id agent_id
```

**per-agent 三级隔离**（`core/memory/mixins/db_mixin.py:62-164`）：
1. **表级**：非 default Agent 用独立表 `memories_{safe_agent_id}`
2. **向量级**：Weaviate 独立 collection（default=`CXOMemory`，其余=`CXOMemory_{id}`）
3. **图级**：独立图库文件 `graph_{id}.db`（默认 `graph.db`，4 个图库 user/thing/concept/event）

另有 `audit_logs` 记录每次写/删/召回；注入条数默认 **top-5**（`inject_memories_count=5`）。

**代码结构**：`MemoryManager` 原 2998 行按功能域拆成 **9 个 mixin**（`:335-348`）：DB / 图集成 / 向量集成 / CRUD / 永久记忆 / 高级检索 / 批量 / 查询辅助 / 决策集成。梦境又加了第 10 个 `_DreamMixin`。

**写入**：INSERT（非永久 `importance_score=0.6`）→ 写 audit → 向量同步（失败仅告警）→ 图同步（失败仅告警）。**所有旁路同步都不阻塞主写入**，这个原则贯穿全系统。

**检索**（`:396-425`）：

```
最近交互记忆（session tag，最多 100）
  + 检索结果（hybrid：向量 0.6 + 关键词 0.4，min_score 0.2）
→ 按 id 去重（保留检索分数，缺字段用 recent 补）
→ 无分数的候选批量补算 (1+cos)/2
→ 三维打分 → 过滤（永久必留 / score≥0.8 / ≥min_score / 显式提及）
→ 场景调整 → 取 max_memories
```

**三维打分是"乘性门控"而不是加权和**（`:409`）：

```
final_score = relevance × (w_importance·importance + w_time·time) / (w_importance + w_time)
```

相关性为 0 则整条为 0，重要度和新鲜度**无法补偿**——这是个很强的设计判断：不相关的东西再重要也不该进上下文。

**场景感知权重表**（`:412-420`）：

| 场景 | importance | time | relevance |
|---|---|---|---|
| task | 0.30 | 0.20 | **0.50** |
| chat（闲聊/情感） | **0.45** | 0.20 | 0.35 |
| first_interaction | 0.30 | 0.30 | 0.40 |
| recall | 0.25 | 0.25 | 0.50 |
| learning | 0.35 | 0.20 | 0.45 |
| problem_solving | 0.25 | 0.20 | **0.55** |
| creative | 0.30 | **0.40** | 0.30 |

**衰减**（`:427-469`）——这是全文档最有"参数工程"味道的一节：

双阶段指数（默认）：`T(t) = α·e^(-λ₁Δt) + (1-α)·e^(-λ₂Δt)`；艾宾浩斯备选：`T = 1/(1+(Δt/T₅₀)^k)`，T₅₀=30、k=2。

按重要度分层给 (α, λ₁, λ₂)（`:448-455`）：

| 重要度 | 等级分 | α | λ₁ | λ₂ | 180 天保留率 |
|---|---|---|---|---|---|
| ≥0.95 | 1.00 | — | — | — | 1.00 永久 |
| 0.85-0.99 | 0.92 | 0.2 | 0.01 | 0.001 | 0.95 |
| 0.70-0.84 | 0.77 | 0.35 | 0.08 | 0.015 | 0.80 |
| 0.50-0.69 | 0.60 | 0.6 | 0.25 | 0.04 | 0.50 |
| 0.30-0.49 | 0.40 | 0.75 | 0.45 | 0.08 | 0.25 |
| <0.30 | 0.15 | 0.9 | 0.80 | 0.15 | 0.05 |

再激活加成：`新时间分 = min(旧 × (1+0.2×再激活次数) + 0.1 + 0.05×|情绪强度|, 1.0)`，召回时 `reactivation_count+1`、`emotion_score` 取均值、写 audit。

网络效应：`增强 = min(0.1×√关联活跃记忆数, 0.3)`；相关性 = 语义相似 60% + 上下文关联 30% + 关键词 10%。

> **要点：衰减不是"更久就更低"这一条直线，而是"重要度决定衰减速度"的分层曲线**，并且**检索一次就等于复习一次**（再激活加成）。这套东西与人类记忆研究（艾宾浩斯、间隔重复）是同构的。

**蒸馏**（`:478-481`）：超长上下文切分 + 多轮蒸馏对话 + 角色卡 Agent 自动创建，把海量内容变成可检索记忆。

### 3.7 图谱、上下文、ACP

- **知识图谱**（`:484-497`）：SQLite `data/graph.db` + 可选 Weaviate；节点/边建模；查询有 `semantic_query` / `hybrid_query`（关键词+向量+图遍历）/ `traversal`；lazy 初始化。
- **上下文**（`:501-508`）：`max_messages=500`、`window_size=50`、`summary_threshold=100`——超出就摘要。
- **ACP 多 Agent**（`:512-520`）：UDP 广播发现（端口 9998/9999）、分组（10001，最多 50 成员）、心跳 10s；前端有连接管理页。

### 3.8 工具与插件（CXFC）

工具注册中心 `server/core/tools/registry.py`，工具集分 6 类（builtin / master / summary / assistant / task / graph）+ MCP 外部接入；调用循环 = 推理→识别调用→执行→回填→继续，直到无调用或到上限（`technical.md:524-537`）。

**CXFC 插件协议**最值得注意的是**三种 transport**（`:541-553`）：

| transport | 形态 | 失败码 |
|---|---|---|
| `direct`（默认） | 插件自带 HTTP 服务，主服务直连 `/tools` `/skills` `/call` | — |
| `relay` | 后端不直连，投递给前端 WS 通道等回报 | `RELAY_UNREACHABLE` / `RELAY_TIMEOUT` |
| `embedded` | 工具以 Python Callable 直接进 `ToolRegistry`，进程内执行 | `EMBEDDED_HANDLER_MISSING` |

`embedded` 范式（`:555-567`）是 Autonomy/Dream 的装配方式：`register_embedded_plugin(plugin_id, name, tools, handlers, skills, capabilities)`，`plugin_id` 归一为 `embedded_{id}`，**进程内、无网络、无端口**。

> 这个"同一份插件契约，三种传输后端"的设计，本质是**把部署形态从代码里拆出去**——本地开发用 embedded，独立进程用 direct，浏览器侧能力用 relay。对 YHLZ 这种"能力要同时挂在 daemon / QQ / 桌宠"的结构很有参考价值。

### 3.9 自主系统（CX-O-Autonomy）

五层（`technical.md:875-887`）：

| 层 | 模块 | 职责 |
|---|---|---|
| 感知 | `perception/`（rss_fetcher / hotspot_monitor / context_sensor） | 新闻、热点、环境 |
| 动机 | `core/motivation/state.py`（`MotivationState`） | 四维：curiosity / social_need / creative_drive / **fatigue** |
| 规划 | `core/planner/action_planner.py` | 主模型按人设规划 + 记忆注入 + **动作白名单** |
| 行动 | `action/`（memory_actions / poster / streamer） | 写记忆、发帖、半自动直播 |
| 反思 | `reflection/`（diary / feedback / consolidator） | 每日日记、反馈评估、经历整合 |

调度：`CircadianScheduler`（wake/sleep/golden/diary/quiet_windows）→ 主循环 `AutonomyEngine` 按 `loop_interval_minutes` 跑"感知→动机→规划→行动→审计→反思"。

**九个动作枚举**（`:895-896`）：`sleep / wait / read_news / search / write_memory / write_post / start_live / stop_live / write_diary`——**动作空间是封闭白名单**，不是让 LLM 随便调工具。

**安全**：审计 `audit_logs.jsonl`（可回放）、内容闸门 `ContentGate`、发帖限速 `post_rate_per_hour`、"离开模式"授权。

**两个值得警惕的删减**（`:906-908`）：`safety/budget/`（TokenLedger 日 token 上限与成本告警）与 `safety/killswitch.py`（急停）**已被人工裁决删除**（2026-09-27），且主循环 `while True` **不存在终止路径**（`:936-938`，paused/sleeping 只是"轮级跳过"）。

> 这是本报告里最该划线的一处：**一个能自主上网、发帖、开直播的系统，把成本闸门和急停删掉了**。功能上"零侵入"，风险上"零兜底"。**可以学它的分层，不要学它的收口。**

### 3.10 梦境引擎（Dream）

管线（`technical.md:948-1000`）：采集日内经历 → LLM 生成梦境 → 过滤 → 缓冲 → 整合沉淀 → 过期清理（PurgeJob）。

记忆侧集成（`:972-979`）：`_DreamMixin` 是 `MemoryManager` 第 10 个 mixin；新增 `decay_type='dream'`（pending/surfaced λ=0.8、confirmed λ=0.25）与 `type='dream'`；`MemoryRouter` **默认排除梦境记忆**，只有 `dream_recall` 或触发词才放行 confirmed 梦境。

**五条安全红线**（`:993-999`）——这是全项目最漂亮的一组约束：

1. `is_ground_truth` 恒 `false`（梦境不是真实经历，不污染事实记忆）
2. `permanent=FALSE` 断言（梦境禁止永久化）
3. `dream_session_id` 强制唯一
4. `decay_type='dream'` + PurgeJob（按梦境策略清理）
5. `purge_dream_session` 支持会话回滚

> "生成出来的东西必须带一个'我不是真的'的位"，这个思路可以直接搬到任何**自产内容**（元亨的日记、反思、主动搭话）上。

### 3.11 自我进化（CXO-Tuner）

四层（`technical.md:837-844`）：采集（recall 对话→清洗→按角色卡锚点切分）→ 评判（judge 打分 + 构造 **DPO 偏好对**）→ 训练（QLoRA + `apply_resource_caps()` 控显存）→ Adapter 管理。

关键机制（`:846-853`）：
- **无人工标注**：对话自动回收成 DPO 偏好对，`anchor_ratio` 平衡锚点与真实交互
- **闲时调度**：`idle_start`/`idle_end` 窗口内才训，不抢对话主链
- **产物即热加载**：LoRA adapter 由 vLLM 动态加载，训完即时可用
- **资源兜底**：`CUDA_VISIBLE_DEVICES` 空值走 CPU，`max_memory_fraction` 防 OOM
- **默认可关**：`profiles: ["tuner"]`，不启用对主系统零影响

> 对 8GB 单卡机器，"闲时训练 + adapter 热加载 + 默认可关"是唯一可行的自我进化形态。**但它和主模型抢显存这件事没有真正解决**（QLoRA 仍要 6-8GB），实际只能在"人不在"时跑。

### 3.12 前端、音声工作站、模型站、评测

**前端技术栈**（`APP-Frontend/package.json`）：Electron 42 + React 18 + Vite 6 + TS 5.7 + Zustand 5 + TanStack Query 5 + Tailwind 3；渲染层 **pixi.js 8 + pixi-live2d-display 0.4**（Live2D）与 **three 0.184 + @pixiv/three-vrm 3.5**（VRM）双引擎；动效 gsap / framer-motion；图表 recharts；**五线谱 vexflow**（作曲页）；图谱 d3-zoom/d3-selection；`@abandonware/noble`（**蓝牙**——这正是 §3.9 之外"生理信号接入"的采集通道）；i18next 多语言；测试 vitest + Playwright + Testing Library。

**页面组织**（`src/pages/`）：98 个文件 = **44 个页面 + 36 个测试 + 18 个纯逻辑/子组件**，集中在 `management/`：

| 域 | 页面 |
|---|---|
| 对话与记忆 | `ChatPage`（含 lifecycle 测试）、`MemoriesPage`、`MemoryAgentPage`、`VectorDataPage`、`ArchivePage`、`DistillationPage` |
| 语音与直播 | `AudioPanelPage`、`AudioSourcePage`、`AudioTestPage`、`AudioWorkstationPage`（含 `CoverPanel/CompositionPanel/DuetPanel/MusicPanel` + vexflow 五线谱）、`LiveConsolePage`、`LiveOverlayPage`、`DanmakuSourcePage`、`SubtitleSourcePage` |
| 形象与形象源 | `AvatarSourcePage`、`NekoPluginsPage` |
| 自主与进化 | `AutonomyPage`、`DreamPage`、`TunerPage` |
| 协作与运维 | `AgentsPage`、`AcpPage`（含圆桌会议视图）、`ClusterPage`、`CxfcPage`、`PluginsPage`、`ToolsPage`、`SettingsPage`（**13 个区块**：形象/直播/后端/管理密钥/音频/采集/LLM/进化/向量/图谱/服务/插件/启动）、`DashboardPage`（含 perf 测试） |

**窗口形态**：桌宠窗 `/pet?agentId=…`（**每个 Agent 一窗，可多开**）、管理窗、弹幕窗，另有 **5 个 OBS 浏览器源** `/source/*`（形象/弹幕/字幕/音频）；Electron 主进程拦截 `page-title-updated` 保证 OBS 按窗名采集，关掉最后一个桌宠窗才退出应用。

**请求层**：`src/api/clients/` 实际 **26 个域客户端**（admin/agents/audio/autonomy/avatarManifest/avatars/chat/cluster/config/cxfc/discovery/distillation/dream/graph/health/meeting/memories/metrics/neko/physio/service/tools/tuner/vector/vision/voiceworkstation）——`AGENTS.md` 写的"12 个"已过时。地址解析四级：Electron IPC > localStorage > `VITE_API_URL` > `127.0.0.1:8000`；两个 axios 实例（主 30s / VWS 60s）；只对 GET/HEAD 重试 3 次；GET 有 100 条/60s 的 LRU 缓存；错误消息五级回退。
> 有意思的是 `@tanstack/react-query` 在依赖里但**全项目没用**——请求层是手写 axios + 局部缓存。

**桌宠侧**（`src/pages/pet/`）做得比一般项目细：
- `lipMixer.ts` / `useLipSyncMixer.ts` / `useTtsLipSync.ts`：**口型混合器**，三路优先级 `TTS > 弹幕 > 麦克风`，逐帧拷贝到输出 ref，无源时归零并自停 RAF
- `useMicAsrUplink.ts`：`getUserMedia(16k)` → `ScriptProcessor(4096)`（≈256ms/帧）→ PCM16 → Live WS 二进制；**用的是已废弃的 ScriptProcessor，不是 AudioWorklet**
- `vad.ts`（前端也跑 VAD）、`danmakuSpeechQueue.ts`、`dragGesture.ts`、`hitGeometry.ts`、`useMousePassthrough.ts`（**鼠标穿透**：头像椭圆 + 聊天条矩形命中，其余 `setIgnoreMouseEvents`）
- `MeetingRoomView.tsx`：多 Agent 圆桌会议

**形象抽象**（`src/avatar/`）：`createDriver` 工厂 + `live2dDriver` / `vrmDriver` 双实现，上层只认 `types.ts`；`tagParser` / `applyTags` / `labelTimeline` 把文本里的 8 类标签（`[emotion:] [blend:] [bone:] [pose] [release] [wind:] [sleep:] [action:]`）解析成**参数时间线**，用 TTS 的 `text_segment` 进度推进触发点；`stripTtsInstruction` 渲染前剥掉给 TTS 的指令标签。**"模型无关驱动接口 + 标签到参数的时间线 + 音画同步"是这套前端最值得抄的结构。**

**hooks**（`src/hooks/` 26 文件 5k 行）：`ws/transport.ts` 统一 WS 工厂（重连 none/fixed/exponential、防重入）；`useWebSocket` 内含 `TTSStreamPlayer`（首包立即调度、`nextStartTime` 背靠背、`generation` 代际号防打断后旧解码结果复播）；`useLiveWebSocket`（指数退避 100→2000ms）；`useMicAsrUplink`；`useVisionPipeline`；`useBackendFailover`（连续探测失败切集群对等节点）；`useConfigReload`（WS 驱动配置热更新）。

**Electron 安全基线**：`contextIsolation:true`、`nodeIntegration:false`、preload 仅经 `contextBridge`；IPC 来源白名单（`file://` 或本机 http）；电脑控制插件跑在本机 **8443（自签 TLS + 256-bit 令牌）**；BLE 心率经主进程 ≤1Hz 上送 `/api/physio/hr`。

**CX-O-VoiceWorkStation**（`workstation/` 32 文件 6900 行；整目录 309 文件/31.6MB，其中 `tools/ffmpeg` 约 28MB）：`api/`（7 router）、`music/`（score/arranger/accompaniment/mixer/draft_registry/musicxml）、`services/`（singing_engine/song_pipeline/sovits_svc_infer/vocal_separator/duet_pipeline/vocal_analysis）。引擎全部是**子进程 wrapper**：

| 引擎 | 调用形态 | 关键约束 |
|---|---|---|
| DiffSinger | `subprocess.run([python, voicews_inference.py, --score, --voice_bank, --output], cwd=DiffSinger)` | 300s 超时；缺目录/声库抛 `SingingEngineError` 并列出全部缺失项 |
| so-vits-svc | `create_subprocess_exec(inference_main.py, -m model, -c config, -n raw, -s spk, -t transpose)` | 输入先复制进 `raw/`；按上游命名取回结果再改名；超时 terminate→kill |
| demucs | `python -m demucs --two-stems=vocals -n htdemucs` | 产物 `vocals.wav` / `accompaniment.wav`；**PATH 前置自带 ffmpeg 供 torchcodec 解码** |
| AudioSep | `python tools/audiosep_runner.py --query-a/--query-b` | 文本查询拆两路；两引擎依赖不共存，各自独立 python |

能力：5 阶段歌曲流水线（validate→accompaniment→vocal→svc→mix，可重启恢复）、20 条草稿命令总线（撤销栈 100、TTL 7 天、版本号防并发）、librosa pyin 音域分析 + 自动升降 key（clamp ±12）、六阶段双人合唱（separate→split→analyze→svc_a→svc_b→mix）。

> **从 clone 直接起不来**：`workstation/music/inventory.py:280-310` 在 **import 期**自检 `.trae/specs/.../music-inventory.schema.json`，`api/cxfc_plugin.py:57-86` 在模块级加载 `command-protocol.schema.json`——而 `.trae/` 被 `.gitignore` 忽略、不在仓库里。**这是"规则资产不入库"的直接后果：模块连 import 都过不去。**

**CXO-ModelStation**（59 文件 12.9k 行）：训练域——So-VITS-SVC / MeloTTS 训练（子进程 + 自适应 batch + OOM 识别 + 长超时）、三引擎批量语料生成（manifest v2 + MD5 去重）、训练互斥（跨引擎 409 冲突）；单 worker；另有 Electron 桌面版（自带便携 Python，安装包实测 **2293MB**）。

**CXO-NekoAdapter**（2 千行 TS）：把 N.E.K.O 的插件服务器拉在本机（控制面 48920 / 插件 48916 / 工具桥 28443），模拟主服务器 `/api/tools/*` 捕获工具定义 → 转成 CXFC schema → `/call` 转发。**这是"外部插件生态接入"的第三种姿势：不改对方，做一层协议伪装。**

**CXO-EvalKit**（105 文件 3.5k 行）：三维阈值可直接当"验收尺"借：

| 维度 | 指标 | 阈值 |
|---|---|---|
| memory | 1 年保持率 | ≥0.6 |
| memory | 永久记忆保持 | =1.0 |
| memory | 再激活组须优于对照组 | bool |
| latency | REST P95 | ≤2000ms |
| latency | 全双工 WS 首包 P95 | ≤800ms |
| latency | 相对基线回归 | ≤+20% |
| quality | judge 均分 | ≥3.5 |

> 注意 latency 的主指标锚点是 `asr_first_partial → tts_first_audio`，**不是** `asr_final → 首包`（因为投机模式下后者恒为 0/负）——**指标定义本身要跟架构匹配**，这是评测设计里最容易错的一步。

### 3.13 工程规约（AC 范式）——最不像代码但最该学的一层

`AGENTS.md` 200 行 + `.trae/rules/rules-0~7` 定义了一套"AI 协同开发规约"：

| 机制 | 内容 |
|---|---|
| **规则优先级** | 本文件高于单次提示词与上下文；上下文压缩时必须完整保留 |
| **契约优先** | `public/` 是契约物理载体（schema 48 + interface_stub 24 + config_template 13）；**禁止"零引用即删除"**，修改必须走 `s0601` 流程 |
| **模块边界** | 模块间只允许依赖 `public/` 契约，禁止直接 import 别的模块内部实现 |
| **变更闸门** | 每次变更必须在 `.trae/documents/` 留 `YYYYMMDD_模块N_变更简述.md`（frontmatter + 问题分析/修复方案/实现步骤/预期效果四章） |
| **单入口收敛** | `prompt_builder.build_messages`、`chat_helpers.*`、`core/chat/stream.py` 是唯一真相源，禁止复制实现 |
| **测试闸门** | 后端 pytest、前端 lint+test+E2E+Mock 回归；契约测试由 LLM 按 rules-3 §五执行 |

**但要看清它的真实状态**（`AGENTS.md:91-93`）：三层契约自己标着"🟡 种子阶段，待 s0201"——**契约体系是目标，不是既成事实**。`.trae/` 整个目录被 `.gitignore` 忽略（`AGENTS.md:85`），意味着**规则资产不在仓库里**，别人 clone 下来看不到 rules/specs/documents。

更能说明问题的是"幽灵契约"：`public/interface_stub/speech_orchestrator.pyi` 声明了一个全库**没有实现**的 `SpeechOrchestrator`，文件头自己写着"幽灵契约，真实面由 `TTSService` 承担"；而 `error_codes.schema.json` 里 `properties: {}`（空种子）、`router 19 个` 的描述对应现实是 36 个——**契约文件本身没有 CI 校验，所以它漂移得比代码还快**。

> 学到的是**形式**（单入口、变更文档、契约保护、上下文保留），不是**它的执行度**。若 YHLZ 要上契约，第一件事是让契约**可执行**（schema 校验 + stub 与实现的一致性测试），否则会长出同样的幽灵。

### 3.14 缺陷与风险

| # | 风险 | 证据 | 说明 |
|---|---|---|---|
| 1 | **体量与复杂度** | 23.8 万行，5 个服务 + 12 个外部引擎 | 单人要跑起来需要一整套 GPU 服务；故障面呈组合爆炸 |
| 2 | **无 LICENSE** | 根目录无 LICENSE | 与 lianlian 同样：只能读不能搬 |
| 3 | **规则资产不入库** | `.gitignore` 忽略 `.trae/`（`AGENTS.md:85`） | 契约/规则/变更文档只存在于作者本地，clone 者拿不到 |
| 4 | **自主系统无急停、无成本闸门** | `technical.md:906-908, 936-938` | 能发帖/直播/上网，却没有 TokenLedger 与 killswitch |
| 5 | **文档与实现可能漂移** | `technical.md` 里多处"已删除/已迁移/待 s0201"；两条引擎线并存（CosyVoice3 主、Qwen3 备） | 读文档必须回代码验证 |
| 6 | **GPU 门槛真实** | vLLM + CosyVoice3 + SenseVoice + LLM 同驻 | 8GB 单卡跑不全，需要按需启停或多机 |
| 7 | **权限面巨大** | 电脑控制、生理信号接入、浏览器自动化发帖 | 攻击面与误操作面都大 |
| 8 | **评测框架自证风险** | EvalKit 由同一作者设计阈值 | 阈值是否代表真实体验，需要外部基线 |
| 9 | **测试多但耦合深** | 5.7 万行测试，E2E 依赖真实服务 | 离线可跑的比例未知，CI 价值打折 |
| 10 | **工具调用面没有 per-agent 授权** | `WS tools.call` 可执行任意已注册工具，只有 enabled/category 过滤与 15 个主模型工具白名单（`chat_helpers.py:187-227`）；管理面才校验 x-api-key | **高**：任何能连上 WS 的客户端都能调全部工具 |
| 11 | **全局错误码契约是空种子** | `public/schema/error_codes.schema.json` 只有 `properties:{}`；实测 WS 错误码 31 个散在各 router | 中：调用方无法统一处理 |
| 12 | **日志格式与规则不符** | `AGENTS.md:105` 要求 `[timestamp] [INFO/ERROR] [elapsed]`，实现是标准 `%(asctime)s - %(name)s - %(levelname)s - %(message)s` | 低（但说明"规则即文档"并不能约束实现） |
| 13 | **同一参数三处不同值** | 向量维度：config 默认 1024 / `weaviate_store` 768 / 文档 768；TTS 切片：文档 4 字 / 代码默认 3 / 语音管线传 2 | 中：调参时极易踩空 |
| 14 | **运行配置不在仓库** | clone 内无 `CX-O-SERVER/config.json`（gitignored），实际运行 = 默认值 + 环境变量 | 低（但复现他人效果需要自建） |
| 15 | **两个子系统从 clone 起不来** | VWS 在 import 期读 `.trae/specs/...schema.json`（`workstation/music/inventory.py:280-310`、`api/cxfc_plugin.py:57-86`），而 `.trae/` 不入库；`DiffSinger/`、`engines/` 为空 | **高**：契约优先的代价是"契约不在，代码也不在" |
| 16 | **CI 覆盖不对称** | 后端/Tuner/前端有 job；VWS/ModelStation/EvalKit/NekoAdapter 无 job，Playwright E2E 不在 CI | 中：越大的模块越没人守 |
| 17 | **文档漂移可量化** | `AGENTS.md` 称"12 域客户端"实际 26；`technical.md:664` 提到的 `useAudioStream`/`useMicrophone` 不存在；"19 router"实际 36 | 中：接手成本被文档放大而非降低 |

---

## 4. 横向对比

| 维度 | lianlian-bot | CX-O | 启示 |
|---|---|---|---|
| **目标** | 一个人的陪伴体 | 角色平台 | 目标决定复杂度，不是能力决定 |
| **语音链路** | 半双工 + 分句流式，0.3-0.65s 首句 | 全双工 + 投机预填充 + 4 字切片，P95 637-762ms | 代差在"**是否由 Partial 驱动**"，不在模型 |
| **打断** | `asyncio.Event` + 播放队列清空 | 双向三态判定 + 意图硬闸门 + 标签解耦 | 打断要做对，必须有"该不该打断"的判据层 |
| **记忆** | 三层 + 0.75/0.15/0.10 加权 | 三维乘性门控 + 场景权重 + 分层衰减 + 再激活 | 加权的下一步是**门控**；衰减的下一步是**分层** |
| **主动性** | 四层闸门 + 指数退避 + 三道内容校验 | 五层架构 + 四维动机 + 九动作白名单 + 昼夜调度 | lianlian 的"规则说不说/LLM 说什么"应作为地基 |
| **形象** | VTS 驱动 或 自渲染 + Neuro 式四层 | Live2D/VRM 双引擎 + 多开桌宠 | 动作调度是状态机问题，不是渲染问题 |
| **工程** | 单人、无测试、文档极诚实 | 契约优先、单入口、变更文档、5.7 万行测试 | 规约的价值在**改了之后还认得回来** |
| **可复现** | 解压即跑（Windows） | 天级部署（GPU + docker） | 学习成本差两个数量级 |
| **许可** | 无 | 无 | 都不能直接搬代码 |

**一个反直觉的观察**：CX-O 的功能是 lianlian 的 30 倍，但**语音体验的关键差距只有一个**——CX-O 用 ASR Partial 驱动整条链路，lianlian 等 VAD 断句。其余 30 倍的工程量，大部分花在"周边能力"上而不是"对话质量"上。

---

## 5. 结论：各自最值得学的一件事

**从 lianlian 学"克制"**：
> 它用 3.2k 行做到了"你说一句、她 0.3 秒出声、记得住、会主动找你"，并且**每一个反直觉的取舍都写了原因**（为什么不用阈值、为什么不用 JSON、为什么默认半双工、为什么记忆块放历史后面）。**能解释自己的每个决定，比功能多寡更重要。**

**从 CX-O 学"边界"**：
> 它的价值不是"功能多"，而是**每个子系统都有一条明确的进出边界**：插件三种 transport、工具注册中心、per-agent 记忆表、`voice.*` action 域、`public/` 契约、`build_messages` 单入口、梦境五条红线。**系统变大以后，唯一能防止腐化的东西是边界，不是纪律。**

**对你（YHLZ）的直接含义**：你的语音链路已经有 `barge_in.py` / `target_vad.py` / `target_chain.py` / `streaming_asr_bridge.py`，架构上比 lianlian 完整；你的记忆有 L1/L2/L3 + PPR + 衰减，比 lianlian 深。**真正缺的是三样**：Partial 驱动的投机预填充、文本平滑切句（TextSmoother）、以及"延迟变成验收项"的度量纪律。具体落地见配套《可借鉴技术报告》。

---

## 附录 A：文件地图（速查）

**lianlian 必读文件**

| 文件 | 为什么读 |
|---|---|
| `core/voice_chat.py:44-76` | 分句算法（三级阈值） |
| `core/llm.py:167-193` | 记忆块注入位置（保 KV 前缀） |
| `core/memory.py:35,232-260,500-545` | 打分公式、问句闸门、重叠校验 |
| `core/proactive.py:161-184` | 四层闸门 + 指数退避 |
| `core/audio_io.py:156-196` | 开机自动校准 VAD |
| `core/vad.py:3-90` | 三级降级 |
| `live2d/native_pet.py` | 自渲染透明窗 + 动作调度 |
| `README.md:164-293` | 记忆系统的完整踩坑史（最值钱） |
| `README.md:418-483` | 主动性设计取舍 |

**CX-O 必读文件**

| 文件 | 为什么读 |
|---|---|
| `docs/technical.md:173-305` | 双流式语音全解（含实测） |
| `docs/technical.md:327-481` | 记忆系统（表结构/打分/衰减表） |
| `docs/technical.md:868-1000` | Autonomy + Dream |
| `AGENTS.md` | AC 范式与契约优先 |
| `CX-O-SERVER/server/protocol/actions.py` | action 域划分 |
| `CX-O-SERVER/server/prompt_builder.py` | 提示词单入口 |
| `CX-O-SERVER/server/core/chat/stream.py` | 工具循环状态机 |
| `CX-O-SERVER/server/services/interrupt_llm.py` | 打断判定的收敛基类 |
| `public/schema/`（48 个） | 契约长什么样 |

## 附录 B：术语

| 词 | 含义 |
|---|---|
| 双流式 | ASR 进、TTS 出两条流同时跑，不等整轮结束 |
| 投机预填充 | 用户还没说完就先开始 LLM 推理 |
| 乘性门控 | 相关性作为乘数，为 0 则整条得 0，其他维度无法补偿 |
| 再激活 | 记忆被召回一次，衰减计时/分数回涨 |
| Partial | ASR 的中间结果（非最终句） |
| GBNF | llama.cpp 的文法约束采样 |
| transport | 插件与主服务的通信形态（direct/relay/embedded） |
| AC 范式 | CX-O 自定的 AI 协同开发规约体系（rules-0~7） |
