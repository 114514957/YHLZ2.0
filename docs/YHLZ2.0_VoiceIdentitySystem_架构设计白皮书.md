# YHLZ Voice Identity System v1.0 架构设计白皮书

> 版本: v1.0
> 生成日期: 2026-08-03
> 依据:《YHLZ 2.0 架构与技术白皮书》 + 当前仓库实际代码(backend/tts/、backend/tts_engine.py、backend/emotion_classifier.py、updates/live_stream/backend/tts_service.py、GPT-SoVITS/)
> 定位: 本白皮书是后续 Agent 开发 Voice Identity System 的**唯一设计依据**。任何实现偏差均以本文档为准。

---

## 目录

1. [系统定位](#一系统定位)
2. [整体架构](#二整体架构)
3. [核心模块设计](#三核心模块设计)
4. [Voice Profile 数据模型](#四voice-profile-数据模型)
5. [数据库设计](#五数据库设计)
6. [声音创建流程](#六声音创建流程)
7. [缓存系统设计](#七缓存系统设计)
8. [TTS 集成设计](#八tts-集成设计)
9. [接口与 API 设计](#九接口与-api-设计)
10. [角色绑定与场景融合](#十角色绑定与场景融合)
11. [错误处理与降级策略](#十一错误处理与降级策略)
12. [配置体系](#十二配置体系)
13. [演进路线](#十三演进路线)
14. [附录: 与现有代码的映射关系](#十四附录与现有代码的映射关系)

---

## 一、系统定位

### 1.1 为什么需要 Voice Identity System

当前 YHLZ 2.0 的 TTS 架构本质是**"选引擎 → 选音色 → 说话"**:

```
调用方 → TTSManager.synthesize(text, voice="Vivian")
             │
             ├── Qwen3-TTS CustomVoice   (预置说话人, SPEAKERS 常量表)
             ├── Qwen3-TTS Clone         (单个 ref_audio 的全局 prompt cache)
             ├── Edge-TTS                (在线音色 ID)
             └── GPT-SoVITS (直播子模块)  (单一 ref_audio + 单一权重对)
```

这个模型有三个根本问题:

1. **音色是"全局常量",不是"角色资产"**: 换声音要改代码/改配置,声音与角色(元亨)没有数据级绑定,与 Live2D 外观、人格、记忆是四张皮。
2. **克隆资产无法沉淀**: Qwen3-TTS Clone 每次启动重新提取 prompt cache;GPT-SoVITS 的参考音频与权重散落在配置里,没有统一生命周期、没有版本、没有试听、没有权限。
3. **引擎切换与声音绑死**: 直播模块直接绑定 GPT-SoVITS Gradio 接口,与主链路 TTSManager 完全脱节,无法按场景(桌宠/直播/配音/批量)自动选引擎。

### 1.2 它解决什么问题

Voice Identity System (VIS) 将"音色"升级为**一等公民资产 —— 声音身份 (Voice Identity)**:

| 维度 | 传统 TTS | Voice Identity System |
|---|---|---|
| 抽象单元 | 引擎 + 音色名 | `voice_id` 标识的声音身份资产 |
| 生命周期 | 每次启动重建 | 创建 → 缓存 → 激活 → 复用,永久沉淀 |
| 数据归属 | 全局配置 | 绑定 owner(角色/用户),独立数据库 |
| 克隆样本 | 单一固定 ref_audio | 可管理的声音样本集(10~30s) |
| 引擎关系 | 音色属于某个引擎 | 一个 voice_id 可被多引擎复用(高保真/低延迟/兜底) |
| 场景适配 | 无 | quality_mode: 桌面/直播/配音/批量自动选引擎 |
| 权限 | 无 | 使用/修改/删除/场景授权,为多用户与交易铺路 |
| 与角色关系 | 无 | Personality + Memory + Appearance + **Voice Identity** |

### 1.3 最终形态

```
Character = Personality(人格) + Memory(记忆) + Appearance(外观/Live2D) + Voice Identity(声音身份)
```

**Voice Identity 是角色的发声器官**,它只回答一个问题:**"这个角色,用什么声音、以什么风格说话"** —— 引擎选择是它的内部实现细节。

### 1.4 设计原则(硬约束)

1. **不破坏现有架构**: 必须遵守 TTSManager 抽象层;禁止在 conversation_manager / main.py 直接调用具体模型;禁止业务代码绑定 GPT-SoVITS。
2. **Voice Identity 是独立领域模块**: 位于 `backend/voice_identity/`,是"声音资产管理层",不是 `tts/plugins`。
3. **支持长期演进**: 声音市场、多用户、云端同步、声音权限、声音交易、声音安全检测,数据模型与模块边界须预留。
4. **硬件基线**: RTX 4060 Laptop 8GB,显存按需加载/释放,与现有 `/modules/start|stop` 生命周期管理对齐。
5. **零样本/少量样本优先**: 默认 10~30s 高质量样本零样本克隆;长数据微调(Fine-tune)作为未来扩展,接口预留。

---

## 二、整体架构

### 2.1 架构分层图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Character Layer  (角色层)                            │
│   Personality(personality.json) + Memory(memories_v2.db 待重建)           │
│   + Appearance(Live2D model) + Voice Identity(voice_id 引用)              │
│   载体: conversation_manager / live_stream_manager / WebUI / 桌宠         │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │  voice_id (角色身份唯一引用)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  Voice Identity Layer  (backend/voice_identity/)          │
│  【声音资产管理层 — 本白皮书核心】                                          │
│                                                                           │
│  VoiceIdentityManager (facade, 对上层唯一入口)                             │
│   ├── registry        声音身份注册表 (profile 生命周期/激活态)               │
│   ├── profile         VoiceProfile 模型 + JSON 读写校验                     │
│   ├── extractor       样本检测/预处理/说话人 Embedding 提取                 │
│   ├── cache_manager   三级永久缓存 (Profile/Embedding/Model) + 8GB 预算     │
│   ├── permission      声音权限控制 (owner/scope/action)                    │
│   ├── style_controller 风格/情绪/quality_mode → 引擎参数解析                │
│   └── engines/        引擎适配器 (GPT-SoVITS / Qwen3-Clone / CustomVoice   │
│                       / Edge / IndexTTS-未来)                             │
│   └── voice_identity.db (sqlite: profiles/models/permissions/usage)       │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │  voice_spec (已解析的引擎参数)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    TTS Engine Layer (现有 TTSManager, 不动核心)            │
│   TTSManager (注册表/激活/自动回退)                                         │
│    ├── qwen3-tts-customvoice   (预置说话人, 真流式)                        │
│    ├── qwen3-tts               (克隆, prompt cache)                       │
│    ├── edge                    (在线兜底, 待注册)                          │
│    └── gpt-sovits (经 adapter 接入, Gradio :9872 或进程内 API)             │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │  (audio, sr) 流
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      Audio Pipeline (现有, 不改)                           │
│   audio_buffer(打断/缓冲/口型) → 播放线程 → sounddevice                     │
│        └── 每 0.1s 口型开合度 → sync_manager → WS /ws/avatar → 桌宠        │
│        └── 自播窗口 → conversation_manager 回声过滤                        │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 各层职责

| 层 | 职责 | 与现状的关系 |
|---|---|---|
| **Character Layer** | 角色综合状态;只持有 `voice_id`,不关心引擎 | 现有 conversation_manager / live_stream_manager 只改一行:`tts.generate(voice_id=char.voice_id)` |
| **Voice Identity Layer** | 声音资产的创建、持久化、缓存、权限、风格解析、引擎适配;把 `voice_id` 翻译成"某引擎可执行的参数集 voice_spec" | **新增** `backend/voice_identity/` |
| **TTS Engine Layer** | 引擎注册、激活、合成、故障回退;接受 voice_spec 并产出音频流 | 现有 `backend/tts/`,**结构零改动**,仅扩展现有引擎对 voice_spec 的接受能力 |
| **Audio Pipeline** | 缓冲/打断/口型/播放/同步/回声 | 完全不动 |

### 2.3 依赖方向(单向,禁止反向)

```
Character Layer ──▶ Voice Identity Layer ──▶ TTS Engine Layer ──▶ Audio Pipeline
```

- 上层只能通过 `VoiceIdentityManager` 公共接口交互。
- `voice_identity/` 允许 import `backend.tts.*`(引擎层),**禁止**被 `backend.tts/*` 反向 import。
- 任何模块禁止直接访问 `voice_identity.db` 以外的状态;业务代码禁止触碰引擎私有参数(如 sovits_weights、gpt_weights)。

---

## 三、核心模块设计

```
backend/voice_identity/
├── __init__.py          # 导出 VoiceIdentityManager 单例 voice_identity_manager
├── manager.py           # 门面: 编排所有子模块, 上层唯一入口
├── registry.py          # 声音身份注册表 (内存激活态 + DB CRUD)
├── profile.py           # VoiceProfile 数据模型 + JSON 读写/校验/迁移
├── extractor.py         # 声音样本处理: 检测/预处理/Embedding 提取
├── cache_manager.py     # 三级永久缓存 + 8GB 显存/内存预算
├── permission.py        # 声音权限策略引擎
├── style_controller.py  # 风格/情绪/quality_mode → 引擎参数
├── db.py                # voice_identity.db SQLite 访问层 (schema 见第五章)
├── constants.py         # 枚举: VoiceType / QualityMode / Scenario / 状态
├── errors.py            # VIS 异常体系 (VoiceNotFound / PermissionDenied 等)
└── engines/             # 引擎适配器 (对现有 TTSManager 引擎的语音身份封装)
    ├── __init__.py      # adapter 工厂: 按 engine_name 实例化
    ├── base.py          # VoiceEngineAdapter 抽象基类
    ├── gpt_sovits.py    # GPT-SoVITS 适配器 (Gradio :9872)
    ├── qwen3_clone.py   # Qwen3-TTS Clone 适配器 (按 voice 切换 prompt cache)
    ├── qwen3_customvoice.py # CustomVoice 预置说话人适配器 (SPEAKERS 扩展)
    ├── edge.py          # Edge-TTS 适配器 (在线兜底)
    └── index_tts.py     # IndexTTS 预留适配器 (骨架, 未来实现)
```

### 3.1 manager.py — VoiceIdentityManager(门面)

**职责**: 对上层暴露唯一 API,编排注册表/缓存/权限/风格/引擎适配。

```python
class VoiceIdentityManager:
    # —— 资产管理 ——
    async def create_profile(self, source: str, meta: ProfileMeta) -> VoiceProfile
        # 编排 extractor → embedding → model 准备 → 试听 → registry.save
    async def get_profile(self, voice_id: str) -> VoiceProfile
    async def list_profiles(self, owner: str | None = None, type: VoiceType | None = None) -> list[VoiceProfile]
    async def delete_profile(self, voice_id: str, actor: str) -> None        # 权限检查后级联清理缓存/DB
    async def activate(self, voice_id: str) -> None                          # 设为角色可用状态
    async def deactivate(self, voice_id: str) -> None
    # —— 合成入口 (被 Character Layer 调用) ——
    async def generate(
        self,
        text: str,
        voice_id: str,
        emotion: str = "neutral",
        quality_mode: QualityMode = "high",
        style: str | None = None,
        scenario: Scenario = "desktop",
        **kwargs,
    ) -> AsyncGenerator[tuple[np.ndarray, int], None]
    # —— 内部编排 ——
    def _resolve(self, voice_id: str) -> VoiceSpec      # 权限+激活校验 → 引擎参数
    def _select_engine(self, spec, quality_mode) -> adapter  # 引擎选择策略
```

**关键行为**:
- `generate` 是门面方法,内部走 `permission.check → style_controller.resolve → engine_adapter.synthesize/stream → 失败降级`。
- 全流程埋点 `voice_usage` 统计(场景/耗时/成功)。
- 启动时从 DB 恢复"上次激活"的 profile 到 registry。

### 3.2 registry.py — 声音身份注册表

**职责**: profile 的内存激活态管理 + DB 持久化桥。

- `_active: dict[voice_id, VoiceProfile]`:当前激活(可被角色使用)的声音身份,容量上限由缓存预算控制。
- `_index: dict[str, list[voice_id]]`:owner → voice_id 索引;`character → voice_id` 绑定索引(一张表,见第五章 voice_profiles.owner)。
- 方法: `register / unregister / get / query / touch(voice_id)`(更新 last_used_at,供缓存淘汰)。
- 与 cache_manager 联动: 激活 = 拉取 embedding/模型缓存到热区;闲置超时 = 释放热区资源。

### 3.3 profile.py — VoiceProfile 数据模型

**职责**: 声音身份的纯数据定义与持久化。Schema 完整定义见第四章。

- `VoiceProfile` dataclass,字段与第四章一致;`to_dict() / from_dict()`。
- `validate()`: 必填字段、枚举合法性、引用路径存在性、embedding 维度一致性。
- 版本迁移: `SCHEMA_VERSION = 1`,`upgrade(old: dict) -> dict` 预留字段演进(声音市场/安全检测等新字段以版本号平滑升级)。

### 3.4 extractor.py — 声音样本处理

**职责**: 把"一段用户上传的声音"变成"可供引擎使用的标准样本 + 说话人 Embedding"。

| 步骤 | 说明 | 复用现有代码 |
|---|---|---|
| 格式检测 | 采样率/声道/时长/编码;不合格直接报错 | `librosa` / soundfile  |
| 有效性检测 | 静音占比、SNR、是否有音乐/双人对话;给出 PASS/WARN/FAIL | 现有 `audio_enhancer` 的能量/VAD 逻辑 |
| 预处理 | 重采样 16k/24k、降噪、AGC、VAD 自动剪切出 10~30s 最干净片段 | `backend.audio_enhancer` / `backend.noise_suppression` |
| 说话人 Embedding | 提取说话人向量(x-vector / 声纹特征) | 按引擎: Qwen3 `create_voice_clone_prompt(x_vector_only_mode=True)`;GPT-SoVITS 零样本时可不显式 embedding(仅需 ref_audio+ref_text),由引擎侧完成 |

**输出产物**(全部落盘,不驻内存):
- `clean_ref_audio.wav`(24kHz 或引擎原生采样率)
- `ref_text.txt`(可选: 若有参考文本,提升 Qwen3 克隆质量)
- `embedding.npy`(向量,带 dim/算法元数据)
- 诊断报告(duration/snr/failed_segments)

**接口**:

```python
async def process_sample(src_path: str, engine_prefs: dict) -> SampleArtifacts
async def extract_embedding(audio_path: str, algo: str = "qwen3-xvector") -> EmbeddingArtifact
```

### 3.5 cache_manager.py — 三级永久缓存

**职责**: 声音资产的持久化存储与热区加载,管理 8GB 硬件预算。详见第七章。

```python
class CacheManager:
    # 目录: voice_identity/cache/{profiles,embeddings,models,previews}
    def save_artifact(self, kind: CacheKind, voice_id: str, payload) -> ArtifactRef
    def load_artifact(self, ref: ArtifactRef) -> Any
    def pin(self, voice_id: str) -> None        # 进入常驻热区 (激活)
    def unpin(self, voice_id: str) -> None      # 退出热区
    def evict_lru(self, keep: int) -> list[str] # 预算不足时按 LRU 淘汰
    def total_size(self) -> CacheStats           # 供 /api/voice/cache 观测
```

### 3.6 permission.py — 声音权限引擎

**职责**: 回答"谁可以用这个声音做什么"。

- 主体(principal): `user` / `character` / `room`(直播房间)/ `feature`(desktop/live/dubbing/batch)。
- 动作(action): `use` / `create` / `modify` / `delete` / `transfer`(未来交易)。
- 检查函数: `check(voice_id, principal, action, scenario) -> bool`,失败抛 `PermissionDenied`。
- v1.0 策略: 默认 `owner=该角色` 全权限,其余主体需显式授权;提供 `authorize()/revoke()`。
- 为多用户/声音交易预留: 约束表达式 `constraints_json`(如 `{"usage_limit": 1000, "expires_at": ...}`)。

### 3.7 style_controller.py — 风格控制器

**职责**: 把"高层的风格/情绪/质量要求"翻译成"每个引擎的具体参数"。

- 输入: `emotion`(来自 emotion_classifier,现有五分类)、`style`(profile 内预设)、`quality_mode`(high/realtime/fallback)、`scenario`。
- 输出: `VoiceStyleSpec` → `{"engine": ..., "rate": ..., "pitch": ..., "emotion_voice": ..., "ref_audio": ..., "engine_kwargs": {...}}`。
- 每个 profile 自带 `style.emotions` 映射(替换全局 `EMOTION_VOICE_MAP`),例如:
  `happy → {"rate": "+10%", "pitch": "+5%", "gpt_sovits_emotion": "happy"}`。
- **兼容策略**: 未定义映射时回退现有 `emotion_classifier.EMOTION_VOICE_MAP` 的 Edge-TTS 音色映射,保证零侵入。

### 3.8 engines/ — 引擎适配器

**职责**: 让 TTSManager 里的每个引擎都能"按 voice_id 工作",把 profile 资产翻译成引擎原生参数。**适配器不是新引擎,不注册进 TTSManager,而是 TTSManager 引擎的"语音身份外壳"**。

`base.py`:

```python
class VoiceEngineAdapter(ABC):
    engine_name: str            # 对应 TTSManager 注册名, 如 "qwen3-tts" / "gpt-sovits"
    supports_quality: set[QualityMode]  # {"high"} / {"realtime"} / {"realtime","high"}
    @abstractmethod
    def prepare(self, profile: VoiceProfile) -> EngineBinding
        # 将 profile 资产(embedding/ref_audio/权重路径)加载为引擎可执行绑定
    @abstractmethod
    async def stream(self, binding, text: str, style: VoiceStyleSpec)
        -> AsyncGenerator[tuple[np.ndarray, int], None]
    @abstractmethod
    def release(self, binding) -> None     # 释放该声音绑定的显存/内存
```

| 适配器 | 实现要点(基于现有代码) |
|---|---|
| `gpt_sovits.py` | 基于 `updates/live_stream/backend/tts_service.py` 的 GradioClient 模式(api_name 发现/change_sovits_weights/change_gpt_weights/inference 20+ 参数);prepare = 按 profile 载入 ref_audio + 权重对(零样本: 默认权重 + 参考音频;未来: 微调权重路径);高保真定位 |
| `qwen3_clone.py` | 基于 `backend/tts/qwen3_tts.py`;prepare = `create_voice_clone_prompt(profile.reference_audio, x_vector_only_mode=True)` 生成该 voice 的 prompt cache;按 voice_id 切换 `_prompt_cache`(引擎本身改造点,见第八章) |
| `qwen3_customvoice.py` | 基于 `backend/tts/qwen3_customvoice.py`;prepare = 把 profile.type=preset 映射到 `SPEAKERS`(Vivian 等),或为"虚拟角色声音创建"新增预置说话人;实时定位 |
| `edge.py` | 基于 `backend/tts/edge.py`;prepare = profile 的 `engine_mapping.edge.voice_id`;兜底定位,永不成为首选 |
| `index_tts.py` | 骨架: 继承 base,`supports_quality={"high"}`;prepare/stream 抛 `NotImplemented` 并在 manager 中标记为 "future" |

---

## 四、Voice Profile 数据模型

### 4.1 字段定义

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema_version` | int | ✔ | 当前 = 1,迁移钩子 |
| `voice_id` | str(UUID) | ✔ | 全局唯一标识,所有场景引用(`tts.generate` / Live2D 绑定 / 直播房间) |
| `owner` | str | ✔ | 属主: `user:xxx` 或 `character:xxx`(角色绑定即 `owner=character:yuanheng`) |
| `name` | str | ✔ | 显示名(如"元亨-主声") |
| `type` | enum | ✔ | `clone`(真人克隆) / `virtual`(虚拟角色声音) / `preset`(预置音色) |
| `language` | str | ✔ | `zh-CN` / `en-US` 等,ISO 639 兼容 |
| `reference_audio` | object | clone 必填 | 见 4.2 |
| `embedding` | object | clone 必填 | 见 4.2 |
| `engine` | object | ✔ | 引擎偏好与按引擎映射,见 4.2 |
| `cache` | object | ✔ | 缓存产物引用与哈希,见 4.2 |
| `permission` | object | ✔ | 权限策略(默认 + 显式授权),见 4.2 |
| `style` | object | ✔ | 默认风格 + 情绪映射,见 4.2 |
| `metadata` | object | ✔ | 创建信息/来源/标签/质量分,见 4.2 |
| `status` | enum | ✔ | `draft`(创建中) / `ready`(可试听) / `active`(已激活) / `disabled` / `error` |
| `created_at` / `updated_at` / `last_used_at` | str(ISO) | ✔ | 生命周期时间戳 |

### 4.2 嵌套对象

- **reference_audio**: `{path, duration_sec, sample_rate, channels, source_hash, ref_text}` —— ref_text 为可选参考转录(提升克隆保真度)。
- **embedding**: `{path, dim, algo, version}` —— algo 如 `qwen3-xvector` / `sovits-speaker` / `index-tts-spk`。
- **engine**: `{preferred: "gpt-sovits", fallbacks: ["qwen3-tts","edge"], per_engine: {"edge": {"voice_id": "zh-CN-XiaoxiaoNeural"}, "gpt_sovits": {"sovits_model": "...", "gpt_model": "..."}}}`。
- **cache**: `{profile_json: {path, hash, size}, embedding_npy: {...}, prompt_cache: {...}, sovits_weights: {...}, preview_wav: {...}}`。
- **permission**: `{default: {"use": true, "modify": false}, grants: [{"principal": "room:10001", "actions": ["use"], "constraints": {"scenario": ["live"]}}]}`。
- **style**: `{default: {"rate": "+0%", "pitch": "+0%"}, emotions: {"happy": {...}, "calm": {...}, ...}, quality: {"high": {...engine 参数...}, "realtime": {...}}}`。
- **metadata**: `{created_by, source_note, tags: [...], preview_score, origin: "upload" | "generated" | "preset"}`。

### 4.3 JSON 示例(完整)

```json
{
  "schema_version": 1,
  "voice_id": "8f2c1a9e-3b7d-4f5a-9c1e-2d0a6b8c4f21",
  "owner": "character:yuanheng",
  "name": "元亨-主声",
  "type": "clone",
  "language": "zh-CN",
  "status": "active",
  "reference_audio": {
    "path": "voice_identity/cache/profiles/8f2c1a9e/ref_clean_24k.wav",
    "duration_sec": 18.6,
    "sample_rate": 24000,
    "channels": 1,
    "source_hash": "sha256:4a2f...",
    "ref_text": "兄弟们好啊，我是元亨，今儿个天气不错，咱们出去溜达溜达。"
  },
  "embedding": {
    "path": "voice_identity/cache/embeddings/8f2c1a9e/xvector.npy",
    "dim": 128,
    "algo": "qwen3-xvector",
    "version": "1.0"
  },
  "engine": {
    "preferred": "gpt-sovits",
    "fallbacks": ["qwen3-tts", "edge"],
    "per_engine": {
      "gpt_sovits": {
        "sovits_model": "yuanheng_v2",
        "gpt_model": "yuanheng_gpt_v2",
        "text_lang": "zh",
        "speed_factor": 1.0
      },
      "edge": {"voice_id": "zh-CN-XiaoxiaoNeural"},
      "qwen3_tts": {"prompt_cache_id": "pc-8f2c1a9e"}
    }
  },
  "cache": {
    "profile_json": {"path": "voice_identity/cache/profiles/8f2c1a9e/profile.json", "hash": "sha256:...", "size": 2048},
    "embedding_npy": {"path": "voice_identity/cache/embeddings/8f2c1a9e/xvector.npy", "hash": "sha256:...", "size": 512},
    "prompt_cache": {"path": "voice_identity/cache/models/8f2c1a9e/prompt_cache.pt", "hash": "sha256:...", "size": 1048576},
    "sovits_weights": {"path": "voice_identity/cache/models/8f2c1a9e/sovits.pth", "hash": "sha256:...", "size": 134217728},
    "preview_wav": {"path": "voice_identity/cache/previews/8f2c1a9e/preview.wav", "hash": "sha256:...", "size": 65536}
  },
  "permission": {
    "default": {"use": true, "modify": false},
    "grants": [
      {"principal": "room:10001", "actions": ["use"], "constraints": {"scenario": ["live"]}},
      {"principal": "feature:batch", "actions": ["use"], "constraints": {"usage_limit": 5000}}
    ]
  },
  "style": {
    "default": {"rate": "+0%", "pitch": "+0%"},
    "emotions": {
      "happy": {"rate": "+8%", "pitch": "+3%", "gpt_sovits_emotion": "happy"},
      "calm":  {"rate": "+0%", "pitch": "-2%"},
      "sad":   {"rate": "-10%", "pitch": "-5%"},
      "angry": {"rate": "+5%", "pitch": "+8%"},
      "neutral": {}
    },
    "quality": {
      "high":     {"engine": "gpt-sovits", "speed_factor": 1.0, "super_sampling": true},
      "realtime": {"engine": "qwen3-tts", "x_vector_only_mode": true},
      "fallback": {"engine": "edge"}
    }
  },
  "metadata": {
    "created_by": "user:local",
    "created_at": "2026-08-03T10:30:00+08:00",
    "updated_at": "2026-08-03T11:00:00+08:00",
    "last_used_at": "2026-08-03T12:00:00+08:00",
    "source_note": "用户上传 3 条共 62s, 自动剪切 18.6s 最干净片段",
    "tags": ["主声", "男声", "兄弟腔"],
    "preview_score": 0.92,
    "origin": "upload"
  }
}
```

### 4.4 两种声音来源的差异

| 项 | clone(真人克隆) | virtual(虚拟角色声音创建) |
|---|---|---|
| reference_audio | 必填(10~30s) | 可选(可用预设音色作为基底) |
| embedding | 必填,自动提取 | 可选;支持"预设音色 + 风格调制" |
| 典型引擎 | GPT-SoVITS / Qwen3-Clone | CustomVoice 预置说话人 / Edge 映射 |
| 未来扩展 | 长数据微调 | 声音混合 / 参数化声线设计 |

---

## 五、数据库设计

**库文件**: `backend/voice_identity/voice_identity.db`(SQLite,UTF-8,WAL 模式)。

**建库工具**: `backend/voice_identity/db.py` 内置 `init_db()` 与 `SCHEMA` 常量,幂等执行 `CREATE TABLE IF NOT EXISTS`。

### 5.1 voice_profiles —— 声音主体信息

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| voice_id | TEXT | PK | 声音身份唯一 ID(UUID) |
| owner | TEXT | NOT NULL | 属主 `user:xxx` / `character:xxx`,索引 |
| name | TEXT | NOT NULL | 显示名 |
| type | TEXT | NOT NULL | clone / virtual / preset |
| language | TEXT | NOT NULL DEFAULT 'zh-CN' | 主语言 |
| status | TEXT | NOT NULL DEFAULT 'draft' | draft/ready/active/disabled/error |
| ref_audio_path | TEXT | NULL | 清洗后参考音频路径 |
| ref_audio_duration | REAL | NULL | 参考音频时长(秒) |
| ref_audio_sr | INTEGER | NULL | 参考音频采样率 |
| ref_text | TEXT | NULL | 参考转录文本(可空) |
| embedding_path | TEXT | NULL | 说话人向量文件路径 |
| embedding_dim | INTEGER | NULL | 向量维度 |
| embedding_algo | TEXT | NULL | 提取算法 |
| preferred_engine | TEXT | NOT NULL DEFAULT 'gpt-sovits' | 首选引擎 |
| fallback_engines | TEXT | NOT NULL DEFAULT '["qwen3-tts","edge"]' | 降级引擎 JSON 数组 |
| engine_mapping | TEXT | NULL | per_engine 参数 JSON |
| style_json | TEXT | NULL | 风格/情绪映射 JSON |
| permission_json | TEXT | NULL | 权限策略 JSON |
| metadata_json | TEXT | NULL | 元数据 JSON |
| created_at | TEXT | NOT NULL | ISO 时间 |
| updated_at | TEXT | NOT NULL | ISO 时间 |
| last_used_at | TEXT | NULL | 最近使用,缓存淘汰依据,索引 |

### 5.2 voice_models —— 模型缓存

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| model_id | INTEGER | PK AUTOINCREMENT | 缓存条目 ID |
| voice_id | TEXT | NOT NULL, FK→voice_profiles | 归属声音身份,索引 |
| engine | TEXT | NOT NULL | gpt-sovits / qwen3-tts / index-tts |
| model_type | TEXT | NOT NULL | embedding / prompt_cache / sovits_weights / gpt_weights / preview |
| file_path | TEXT | NOT NULL | 磁盘路径 |
| file_size | INTEGER | NOT NULL | 字节数 |
| file_hash | TEXT | NOT NULL | sha256,用于内容寻址去重 |
| format | TEXT | NULL | npy / pt / pth / wav |
| status | TEXT | NOT NULL DEFAULT 'ready' | ready/generating/error/evicted |
| created_at | TEXT | NOT NULL | ISO 时间 |
| last_used_at | TEXT | NULL | 最近使用,LRU 依据,索引 |

### 5.3 voice_permissions —— 权限

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| perm_id | INTEGER | PK AUTOINCREMENT | 权限条目 ID |
| voice_id | TEXT | NOT NULL, FK→voice_profiles | 目标声音身份,索引 |
| principal_type | TEXT | NOT NULL | user / character / room / feature |
| principal_id | TEXT | NOT NULL | 主体标识,联合索引(voice_id, principal_type, principal_id, action) |
| action | TEXT | NOT NULL | use / create / modify / delete / transfer |
| allowed | INTEGER | NOT NULL DEFAULT 1 | 1 允许 / 0 拒绝 |
| constraints_json | TEXT | NULL | 约束表达式 JSON(次数/有效期/场景白名单) |
| created_at | TEXT | NOT NULL | ISO 时间 |

### 5.4 voice_usage —— 使用统计

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | PK AUTOINCREMENT | 流水 ID |
| voice_id | TEXT | NOT NULL, FK→voice_profiles | 声音身份,索引 |
| engine | TEXT | NOT NULL | 实际引擎 |
| scenario | TEXT | NOT NULL | desktop / live / dubbing / batch / preview |
| quality_mode | TEXT | NULL | high / realtime / fallback |
| text_len | INTEGER | NULL | 合成文本长度(字符) |
| audio_duration_sec | REAL | NULL | 产出音频时长 |
| latency_ms | REAL | NULL | 合成耗时 |
| success | INTEGER | NOT NULL DEFAULT 1 | 1 成功 / 0 失败 |
| created_at | TEXT | NOT NULL | ISO 时间,索引 |

### 5.5 建表要点

- `voice_profiles.owner`、`voice_models.voice_id`、`voice_permissions.voice_id`、`voice_usage.voice_id` 全部建索引,支撑"按角色列出所有声音"与"使用排行"。
- SQLite 外键 `PRAGMA foreign_keys=ON`;删除 profile 走 `delete_profile()` 事务: 先删 usage/permissions/models 再删 profile。
- 预留演进: 声音安全检测结果存 `voice_models(model_type='safety_report')`;声音交易记录存 `voice_permissions(action='transfer')` + `voice_usage` 统计,无需改表。

---

## 六、声音创建流程

### 6.1 总流程

```
 ① 上传声音 ──▶ ② 音频检测 ──▶ ③ 预处理 ──▶ ④ Speaker Embedding
                                                      │
                                                      ▼
 ⑧ 激活 ──▶ ⑦ 试听 ──▶ ⑥ 缓存生成 ──▶ ⑤ 模型准备
```

profile.status 随流程推进: `draft → ready(试听后) → active`;任一步骤失败 → `error` 并返回可读错误。

### 6.2 分步输入/输出

| # | 步骤 | 输入 | 处理 | 输出 |
|---|---|---|---|---|
| ① | **上传声音** | 音频文件(建议 ≥30s 素材,mp3/wav/flac/m4a)+ 元数据(name/type/language/owner/来源) | 落盘到临时区,计算源哈希 | `staged_file` + 上传票据 |
| ② | **音频检测** | staged_file | 解码;检查采样率/声道/时长/静音占比/SNR/是否双人对话;时长不足 10s 或信噪比过低 → FAIL | 诊断报告 `AudioDiagnosis{pass, duration, snr, issues[]}` |
| ③ | **预处理** | 检测通过的音频 | 复用 `audio_enhancer` + `noise_suppression` 清洗;VAD 自动切割出 10~30s 最干净连续片段;重采样到引擎原生采样率(24kHz);生成参考转录(可选) | `clean_ref_audio.wav` + `ref_text.txt` + 片段统计 |
| ④ | **Speaker Embedding** | clean_ref_audio | 按首选引擎提取说话人向量(Qwen3 x-vector / GPT-SoVITS speaker);保存元数据 | `embedding.npy` + EmbeddingArtifact(dim/algo/version) |
| ⑤ | **模型准备** | embedding + ref_audio + 引擎偏好 | 零样本: 校验默认权重可用(或热加载);未来: 长数据微调入口在此挂接;生成引擎绑定参数 | `EngineBinding`(ref_audio 路径 / 权重对 / prompt 参数) |
| ⑥ | **缓存生成** | EngineBinding | 生成各引擎缓存产物: Qwen3 `prompt_cache.pt`(若选克隆引擎)、GPT-SoVITS 权重映射(零样本默认权重则记引用)、预览音频占位;全部写入 `voice_identity/cache/` 并登记 `voice_models` 表 | cache 条目 + 哈希登记 |
| ⑦ | **试听** | 缓存产物 + style.default | 用固定试听句(如"你好,我是{name},很高兴见到你。")按 style 合成 1 段;产出试听音频并统计耗时 | `preview.wav` + preview_score(合成成功率/耗时);status → `ready` |
| ⑧ | **激活** | ready 的 profile | 权限默认写入(owner 全权);`registry.activate`;`cache_manager.pin`;status → `active`;绑定 owner 角色(character 映射) | 可用的 `voice_id` |

### 6.3 关键规则

- 步骤 ②③④ 全部异步化(线程池,避免阻塞 FastAPI 事件循环),失败可重试。
- 试听通过才允许激活;用户可跳过试听(标记 `ready` 直接激活,但 UI 上强制提示)。
- 创建中途失败: 自动清理临时产物,profile 置 `error` 保留诊断信息,不产生孤儿缓存。
- 全程记录 `voice_usage(scenario='preview')`,供质量复盘。

---

## 七、缓存系统设计

### 7.1 缓存分层与常驻策略(RTX 4060 Laptop 8GB)

```
Profile Cache (元数据, 常驻内存, 总量 < 1MB)
   └── 所有 profile 的 JSON 元数据 + registry 索引
        · 常驻: ✔ 全部(体积可忽略)

Embedding Cache (磁盘常驻, 内存按需, 单条 < 1MB)
   └── embedding.npy 全部落盘 voice_identity/cache/embeddings/
        · 常驻内存: 仅激活的 profile(≤ N 条, 预算上限 32MB)
        · 按需加载: 非激活 profile 使用时从磁盘秒级加载

Model Cache (磁盘常驻, 显存按需, 大头)
   ├── Qwen3 prompt_cache.pt (单条 ~1-10MB, CPU 内存即可推理)
   │     · 常驻: 仅当前激活声音(切换即换绑)
   ├── GPT-SoVITS 权重 (单角色 100-500MB, GPU 推理)
   │     · 常驻: 无 — 零样本模式复用公共权重, 微调权重经 API 热切换
   ├── IndexTTS 权重 (未来, 同 GPT-SoVITS 策略)
   └── 基底大模型 (Qwen3-0.6B / GPT-SoVITS 全量, ~2-4GB 显存)
         · 常驻: 仅当该引擎被激活时(与现有模块生命周期对齐, 不常驻)
```

### 7.2 显存预算表(8GB 基线)

| 占用项 | 估算 | 说明 |
|---|---|---|
| ASR(SenseVoiceSmall) | ~1.5GB | 已有, 按模块管理 |
| Qwen3-TTS 基底(0.6B bf16) | ~2.5GB | 与 ASR 可共存 |
| GPT-SoVITS 推理态(零样本) | ~3.5GB | 单角色权重对 |
| LLM / Live2D / 系统 | 其余 | 显存不足时经 `release_gpu()` 释放 |

**冲突策略**: `cache_manager` 提供 `gpu_budget` 估算与 `can_coexist(engine_a, engine_b) -> bool`;当 GPT-SoVITS 与 Qwen3 需要同时服务(如直播高保真 + 桌宠实时)时,按场景优先级热切换,绝不双模型常驻。

### 7.3 常驻 vs 按需加载总结

| 缓存 | 常驻 | 按需 |
|---|---|---|
| Profile 元数据 | ✔ 全部 | — |
| 激活声音的 embedding / prompt_cache | ✔ 单个 | — |
| GPT-SoVITS 权重 | ✘ | 激活时经 Gradio 热切换,完成后仅留磁盘缓存 |
| 基底模型 | ✘ | 引擎激活时加载,`unload()`/`release_gpu()` 释放 |
| 预览音频/历史产物 | ✘ | 试听时读取,磁盘直出 |
| 全部缓存哈希索引(voice_models 表) | ✔ 常驻 DB | — |

### 7.4 永久缓存语义

- **永久 = 磁盘持久化 + 内容寻址**: 同一 ref_audio(源哈希相同)二次创建直接复用 embedding/prompt_cache,不重复计算。
- 缓存文件随 `voice_identity/cache/` 目录持久保存;DB 中 `voice_models.status='evicted'` 表示磁盘文件被清理(可重建),哈希未变则允许惰性重建。
- 淘汰策略: LRU + 预算水位;`last_used_at` 超过阈值且非激活 → 释放内存热区,磁盘文件保留。
- 删除 profile 时级联清理磁盘缓存与 DB 记录。

---

## 八、TTS 集成设计

### 8.1 集成原则

1. **TTSManager 结构零改动**: 不修改 `manager.py` 的注册/激活/回退机制;适配器位于 voice_identity 侧。
2. **引擎改造是"增强"不是"重写"**: 现有引擎(如 `qwen3_tts.py`)只加"按 voice_id 切换 prompt cache/ref_audio"的能力,默认行为不变。
3. **业务代码单一入口**: Character Layer 只调用 `voice_identity_manager.generate(text, voice_id, ...)`,禁止直接触碰 TTSManager 或引擎。

### 8.2 调用链

```python
# Character Layer (conversation_manager / live_stream / WebUI / 桌宠)
async for audio, sr in voice_identity_manager.generate(
    text="兄弟们,走着!",
    voice_id="8f2c1a9e-...",       # 角色绑定, 或默认角色的 voice_id
    emotion="happy",                # 来自 emotion_classifier 或 LLM
    quality_mode="high",            # high / realtime / fallback
    scenario="desktop",             # desktop / live / dubbing / batch
):
    audio_buffer.enqueue(audio, sr)  # 现有 Audio Pipeline 不动

# 内部编排 (manager.generate)
# 1. registry.get(voice_id)          → profile (校验 active + 权限)
# 2. style_controller.resolve(...)   → VoiceStyleSpec (引擎 + 参数 + 情绪映射)
# 3. _select_engine(spec, quality)   → gpt-sovits | qwen3-tts | edge (按 quality_mode 与引擎可用性)
# 4. adapter.prepare(profile)        → EngineBinding (prompt cache / 权重热切换)
# 5. adapter.stream(binding, text, style) → 流式音频, 失败按 fallbacks 降级
# 6. cache_manager.touch(voice_id) + voice_usage 埋点
```

### 8.3 统一合成接口(目标形态)

```python
# backend/voice_identity/manager.py 顶层入口 —— 与需求示例对齐
tts.generate(text, voice_id, emotion, quality_mode)
```

| 参数 | 类型 | 说明 |
|---|---|---|
| `text` | str | 待合成文本(已过 text_postprocessor 清洗) |
| `voice_id` | str | 声音身份;缺省 → 当前角色绑定的 voice_id |
| `emotion` | str | 五分类(happy/calm/sad/angry/neutral);None → 自动分类 |
| `quality_mode` | str | `high`(GPT-SoVITS 最高拟真) / `realtime`(Qwen3 低延迟) / `fallback`(Edge 兜底) |
| `scenario` | str | desktop / live / dubbing / batch,影响权限校验与统计 |
| `style` | str \| None | 覆盖 profile 风格预设 |
| 返回 | AsyncGenerator[(np.ndarray, int)] | 兼容现有 stream_synthesize_text 消费方 |

### 8.4 引擎选择策略(quality_mode → 引擎)

| quality_mode | 首选 | 次选 | 兜底 | 依据 |
|---|---|---|---|---|
| `high`(默认) | gpt-sovits | qwen3-tts(克隆) | edge | 允许牺牲实时性换拟真度, 定位"视频/动画配音、批量生产" |
| `realtime` | qwen3-tts(克隆) | qwen3-tts-customvoice | edge | 桌宠聊天/直播弹幕低延迟 |
| `fallback` | edge | qwen3-tts-customvoice | — | 本地模型不可用时的网络兜底 |

- 引擎可用性(已加载/权重存在/Gradio 可达)由适配器 `can_serve()` 上报,选择器据此跳过不可用项。
- 若 profile 的 `preferred_engine` 与 quality_mode 冲突,以 quality_mode 为主,但保留 profile 的 per_engine 参数。

### 8.5 对现有引擎的最小改造点

| 文件 | 改造 | 兼容性 |
|---|---|---|
| `backend/tts/qwen3_tts.py` | 新增 `set_prompt_cache(prompt)` / 构造时接受 `ref_audio` 参数;`_prompt_cache` 由单一全局改为可切换 | 默认值不变, 单例行为不变 |
| `backend/tts/qwen3_customvoice.py` | 无(SPEAKERS 常量经 adapter 映射即可);如需虚拟角色可运行时注册说话人 | 零改动 |
| `backend/tts/edge.py` | 无(adapter 直接传 voice_id) | 零改动 |
| `updates/live_stream/backend/tts_service.py` | 作为 gpt_sovits 适配器的参考实现模板, 适配器复制其 GradioClient/权重热切换逻辑;live_stream 侧改调 manager | live_stream 自身保留原接口作为兼容 |

### 8.6 情绪与风格的融合

- 不再使用全局 `EMOTION_VOICE_MAP` 直接覆盖音色(它把"情绪"错误地映射成"换一个人");改为 **profile.style.emotions** 内映射(语速/音高/引擎情绪参数)。
- 无显式映射时回退现有 `emotion_classifier.resolve_voice_for_emotion`,保证旧行为不变。
- `emotion=None` 时内部调用现有 `classify_emotion(text)` 自动分类。

---

## 九、接口与 API 设计

### 9.1 VoiceIdentityManager 公共接口(Python)

```python
# 资产管理
create_profile(source, meta) -> VoiceProfile            # 异步编排全流程(六章)
get_profile(voice_id) / list_profiles(owner=None, type=None)
update_profile(voice_id, patch) -> VoiceProfile          # 权限: modify
delete_profile(voice_id)                                 # 权限: delete, 级联清理
activate(voice_id) / deactivate(voice_id)                # 权限: use

# 权限
authorize(voice_id, principal, action, constraints=None) # 权限: owner 或 transfer
revoke(voice_id, principal, action)

# 缓存/诊断
cache_stats() -> dict                                    # 各级缓存大小/命中
usage_stats(voice_id=None, scenario=None) -> list        # voice_usage 查询

# 合成(核心)
generate(text, voice_id, emotion, quality_mode, scenario, style=None, **kw)
```

### 9.2 REST 端点(挂载于 backend/main.py, 前缀 `/api/voice`)

| 方法 | 路径 | 说明 | 对应模块 |
|---|---|---|---|
| POST | `/api/voice/upload` | 上传样本(文件 + 元数据), 返回上传票据 | manager.create_profile ① |
| POST | `/api/voice/profiles` | 创建声音身份(引用上传票据), 异步返回 task_id | create_profile 全流程 |
| GET | `/api/voice/profiles` | 列表(owner/type/status 过滤) | registry.list |
| GET | `/api/voice/profiles/{voice_id}` | 详情(含 style/cache/permission) | registry.get |
| PUT | `/api/voice/profiles/{voice_id}` | 更新元数据/风格/引擎偏好 | update_profile |
| DELETE | `/api/voice/profiles/{voice_id}` | 删除(级联) | delete_profile |
| POST | `/api/voice/profiles/{voice_id}/activate` | 激活 | activate |
| POST | `/api/voice/profiles/{voice_id}/deactivate` | 停用 | deactivate |
| GET | `/api/voice/profiles/{voice_id}/preview` | 重新试听(或取缓存 preview.wav) | 试听步骤 |
| POST | `/api/voice/synthesize` | `{text, voice_id, emotion, quality_mode, scenario}` → 音频 | manager.generate 单发 |
| POST | `/api/voice/synthesize/stream` | 同上, NDJSON 流式(对齐现有 /synthesize/stream 风格) | manager.generate 流式 |
| GET | `/api/voice/cache` | 缓存统计与预算 | cache_manager |
| GET | `/api/voice/usage` | 使用统计 | voice_usage |
| POST | `/api/voice/permissions` | 授权/回收 | permission |

### 9.3 任务模型(长流程)

创建声音身份是秒~分钟级流程,采用 **task 模式**:

```json
POST /api/voice/profiles  →  {"task_id": "t-001", "profile_id": null}
GET  /api/voice/tasks/t-001 → {"status": "processing", "stage": "preprocess",
                                "progress": 0.4, "profile_id": null}
```
- 阶段枚举: upload → detect → preprocess → embedding → model_prepare → cache → preview → ready。
- WebUI 前端轮询进度;失败返回 stage + 诊断信息。

---

## 十、角色绑定与场景融合

### 10.1 与人格/记忆/外观绑定

```
Character = Personality + Memory + Appearance + Voice Identity
                   │            │            │             │
            personality.json  memories_v2   Live2D model  voice_id
                   └────────────┴────────────┴─────────────┘
                                    │
                    character.yaml (新增轻量绑定文件, 推荐位于 backend/data/)
                    {character_id: "yuanheng", voice_id: "8f2c1a9e-...", live2d_model: "hiyori", ...}
```

- `voice_identity_manager.get_default_voice_id(character_id)` 提供角色 → 声音的默认解析,缺省回退系统默认音色。
- 与 Live2D: 一个 Live2D 模型可绑定一个声音身份(WebUI 角色设置页联动);口型/表情链路不变。
- 与人格: 风格预设可在 personality.json 中追加 `voice_style` 字段作为默认 style 覆盖。

### 10.2 与直播系统融合(live_stream)

| 现状(硬编码) | 目标(voice_id 驱动) |
|---|---|
| `cfg.sovits_model` / `cfg.gpt_model` 全局单一权重对 | 每个主播角色一个 voice_id, `prepare()` 时热切换权重 |
| `cfg.ref_audio_path` / `cfg.ref_text_path` 全局参考音频 | profile.reference_audio 自动生成(含清洗与转录) |
| 直播直接 import tts_service | live_control 插件改调 `voice_identity_manager.generate(quality_mode="high", scenario="live")` |
| 无权限概念 | `room:xxx` 需 `use` 授权(permission.grants) |

兼容: `tts_service.py` 原接口保留为 legacy 层,adapter 复用其实现(见 8.5)。

### 10.3 与桌宠/WebUI/批量生产

| 场景 | quality_mode | 说明 |
|---|---|---|
| 桌宠实时聊天 | realtime | Qwen3 克隆流式, 首块延迟 ~0.4s(沿用 CUDA graph 预热) |
| 虚拟主播直播 | high | GPT-SoVITS, 接受 3-10s 合成延迟, 最高拟真 |
| 视频/动画配音 | high | 批量任务, 支持脚本文件 → 分段合成 → 导出 |
| 批量内容生产 | high / 自定义 | usage 统计支撑限额; 未来多 worker 并行 |

---

## 十一、错误处理与降级策略

### 11.1 异常体系(`errors.py`)

| 异常 | 触发 | 处理 |
|---|---|---|
| `VoiceNotFoundError` | voice_id 不存在 | 回退系统默认音色,日志告警 |
| `VoiceNotReadyError` | status != active | 返回明确提示(未激活/创建中) |
| `PermissionDenied` | 权限校验失败 | 拒绝并记录 audit(voice_usage) |
| `SampleInvalidError` | 样本检测 FAIL | 返回诊断报告 |
| `EngineUnavailableError` | 首选引擎不可用 | 按 fallbacks 降级 |
| `CacheCorruptionError` | 缓存文件哈希不匹配 | 惰性重建缓存 |

### 11.2 降级链(永不静默失败,对齐项目原则)

```
voice_id 合成失败
   │
   ├─ 引擎不可用 → quality_mode 内引擎降级 (gpt-sovits → qwen3-tts → edge)
   ├─ 引擎全部失败 → profile.fallbacks 降级 (再试一轮)
   ├─ 缓存损坏 → 惰性重建该 voice 的 embedding/prompt cache
   └─ 全链路失败 → 返回 mock 静音(现有引擎行为) + 错误日志
```

### 11.3 并发与资源安全

- `prepare(binding)` 为重量操作,按 voice_id 加锁,防止同一声音并发重复 prepare。
- 显存释放: `release_gpu()` 与 `cache_manager.unpin` 联动,与现有 `/modules/stop` 生命周期一致。
- 所有磁盘写入先写临时文件再原子 rename,防断电损坏。

---

## 十二、配置体系

### 12.1 `.env` 新增键(全部可选, 带默认)

```
# 声音身份系统
VIS_DB_PATH=backend/voice_identity/voice_identity.db   # 默认相对项目根
VIS_CACHE_DIR=backend/voice_identity/cache
VIS_DEFAULT_QUALITY_MODE=high
VIS_DEFAULT_VOICE_ID=                                  # 空=使用系统默认音色
VIS_ACTIVE_LIMIT=4                                     # 内存热区 profile 上限
VIS_EMBEDDING_RAM_BUDGET_MB=32
VIS_GPU_BUDGET_MB=0                                    # 0=自动估算
GPT_SOVITS_URL=http://127.0.0.1:9872                  # 复用直播模块约定
GPT_SOVITS_SSL_VERIFY=false
```

### 12.2 目录结构

```
backend/voice_identity/
├── voice_identity.db              # SQLite (运行时生成)
└── cache/
    ├── profiles/  <voice_id>/profile.json + ref_clean_24k.wav + ref_text.txt
    ├── embeddings/ <voice_id>/xvector.npy
    ├── models/     <voice_id>/prompt_cache.pt | sovits.pth | gpt.ckpt
    ├── previews/   <voice_id>/preview.wav
    └── staging/    上传临时区 (创建成功后清理)
```

### 12.3 兼容配置

- `TTS_ENGINE` 语义不变(默认激活的基底引擎);VIS 在其上叠加 voice_id 层。
- 现有 `QWEN3_TTS_REF_AUDIO` 等环境变量继续有效,作为"无 VIS 配置时的旧默认值"。

---

## 十三、演进路线

### 13.1 v1.0(本白皮书范围)

1. `backend/voice_identity/` 全部模块落地(第三章目录),`voice_identity.db` 四表(第五章)。
2. 声音创建 8 步流程 + task 模式 API(第六、九章)。
3. 三级缓存 + 8GB 预算管理(第七章)。
4. GPT-SoVITS / Qwen3-Clone / CustomVoice / Edge 四个适配器,`tts.generate(text, voice_id, emotion, quality_mode)` 上线。
5. WebUI 声音管理页(上传/创建/试听/激活/权限)与角色绑定。

### 13.2 v1.1(近期增强)

1. 长数据微调管线挂接(model_prepare 步骤扩展: 样本集 → 训练任务 → 微调权重入库)。
2. 虚拟角色声音创建增强: 预置音色混合 / 参数化声线(风格调制生成)。
3. 直播场景全量迁移至 voice_id 驱动,移除 live_stream 硬编码权重对。

### 13.3 v2.0(长期演进, 已预留)

1. **多用户**: owner 体系 + permission 全量启用,WebUI 用户空间隔离。
2. **云端同步**: voice_models 哈希表支持增量上传/拉取,profile JSON 天然可迁移。
3. **声音市场/交易**: `transfer` 动作 + voice_usage 计费 + constraints 限次限时。
4. **声音安全检测**: 克隆样本真实性校验、深度伪造检测报告入库(voice_models.model_type='safety_report')。
5. **IndexTTS 接入**: 补齐 `engines/index_tts.py` 实现,supports_quality={"high"}。

---

## 十四、附录: 与现有代码的映射关系

| 现有代码 | VIS 对应 | 动作 |
|---|---|---|
| `backend/tts/manager.py` TTSManager | 引擎层,被 adapter 调用 | **不动** |
| `backend/tts/base.py` BaseTTSEngine | `engines/base.py` 适配器基类的参考 | 不动, 适配器另立 |
| `backend/tts/qwen3_tts.py`(prompt cache 全局) | qwen3_clone 适配器 + 引擎"按 voice 切换 prompt cache"增强 | 最小增强 |
| `backend/tts/qwen3_customvoice.py`(SPEAKERS) | qwen3_customvoice 适配器 | 零改动 |
| `backend/tts/edge.py` | edge 适配器 | 零改动 |
| `backend/tts_engine.py`(兼容层) | 保留, 供无 voice_id 的旧调用 | 不动 |
| `backend/emotion_classifier.py`(全局音色映射) | style_controller 内按 profile 映射, 旧表作回退 | 复用函数 |
| `backend/audio_enhancer.py` / `noise_suppression.py` | extractor 预处理链 | 直接复用 |
| `backend/main.py` /synthesize* 端点 | 新增 `/api/voice/*`, 旧端点保留 | 新增 |
| `backend/conversation_manager.py` | 调用点改为 `voice_identity_manager.generate` | 1 行改造 |
| `updates/live_stream/backend/tts_service.py`(Gradio :9872) | gpt_sovits 适配器实现模板 | 复制重构, 保留 legacy |
| `updates/live_stream/backend/live_stream_manager.py` | 经 live_control 插件改调 VIS | 改造 |
| `backend/config.py` | 新增 VIS 配置组 | 扩展 |
| 现有 `/modules/start|stop` 生命周期 | cache_manager pin/unpin + release_gpu 联动 | 对齐 |
| `personality.json` | 追加 `voice_style` 可选字段 | 扩展 |

---

*文档基于 2026-08-03 仓库实际代码与《YHLZ 2.0 架构与技术白皮书》生成,是 Voice Identity System 开发的唯一设计依据;实现与本文档冲突时,以本文档为准并同步更新。*
