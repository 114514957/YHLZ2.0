# YHLZ Voice Identity System v1.0 Integration Audit Report

> 版本: v1.0
> 生成日期: 2026-08-03
> 审计对象: 《YHLZ 2.0 架构与技术白皮书》 / 《YHLZ Voice Identity System v1.0 架构设计白皮书》 / 当前仓库实际代码
> 审计结论: **有条件通过 —— 架构方向正确, 依赖方向与接口抽象与现有代码高度吻合; 但存在 4 个必须修改点、6 个高风险项, 需按第七部分执行后再进入 V1 编码。**

---

## 目录

1. [现有架构扫描](#第一部分-现有架构扫描)
2. [当前 TTS 架构分析](#第二部分-当前-tts-架构分析)
3. [Voice Identity 架构映射](#第三部分-voice-identity-架构映射)
4. [接口兼容性分析](#第四部分-接口兼容性分析)
5. [数据库设计审计](#第五部分-数据库设计审计)
6. [模型生命周期分析 (RTX 4060 Laptop 8GB)](#第六部分-模型生命周期分析)
7. [风险发现](#第七部分-风险发现)
8. [修改建议](#第八部分-修改建议)
9. [最终实施路线 Milestone V1-V5](#第九部分-最终实施路线-milestone-v1-v5)
10. [审计判定清单](#第十部分-审计判定清单)

---

## 第一部分: 现有架构扫描

### 1.1 相关目录树(实测, 非文档描述)

```
YHLZ2.0/
├── backend/                          # 后端核心 (FastAPI :8000)
│   ├── main.py                       # 1513 行: 全部路由/WS/装配/播放线程
│   ├── config.py                     # Pydantic 单例, 读取根目录 .env (唯一权威配置)
│   ├── tts_engine.py                 # [兼容层] 构建 TTSManager 单例 (47 行)
│   ├── tts/                          # TTS 多引擎包 (核心审计对象)
│   │   ├── base.py                   # BaseTTSEngine 抽象基类 (66 行)
│   │   ├── manager.py                # TTSManager 注册表/激活/自动回退 (168 行)
│   │   ├── qwen3_customvoice.py      # 主引擎: faster-qwen3-tts 真流式 + CUDA graph (203 行)
│   │   ├── qwen3_tts.py              # 语音克隆引擎: Qwen3-TTS-0.6B-Base (176 行)
│   │   └── edge.py                   # Edge-TTS 在线引擎 (482 行, 已实现未注册)
│   ├── emotion_classifier.py         # 情绪五分类 → Edge-TTS 音色映射 (138 行)
│   ├── conversation_manager.py       # 连续对话状态机 (377 行)
│   ├── context_manager.py            # 上下文/摘要/性格(读 personality.json)/记忆(stub)
│   ├── sync_manager.py               # 多模态同步事件总线 (WS 广播)
│   ├── audio_buffer.py               # 播放缓冲/打断/口型计算
│   ├── audio_enhancer.py             # ASR 预增强 (VIS extractor 复用点)
│   ├── noise_suppression.py          # 降噪链 (VIS extractor 复用点)
│   ├── vad_engine.py / asr_engine.py / llm_engine.py
│   └── data/
│       ├── personality.json          # 角色性格 (元亨, 唯一角色载体)
│       ├── memories.db               # 记忆库 v1 (13 条历史数据)
│       ├── memories_v2.db            # 记忆库 v2 (5 表空壳)
│       └── memories.json
├── updates/live_stream/              # 直播子模块 (独立插件化方案)
│   ├── backend/
│   │   ├── tts_service.py            # GPT-SoVITS Gradio 客户端 + 双队列 (420 行)
│   │   ├── live_stream_manager.py    # 直播状态机/能量/冷场
│   │   ├── models.py                 # LiveSettings (含 sovits_model/gpt_model/ref_audio_path)
│   │   └── cognitive_avatar_controller.py / events.py / mouth_sync.py ...
│   ├── plugins/                      # bilibili_live / vtube_studio / live_control
│   └── config/*.json                 # 直播配置
├── checkpoints/                      # GPT-SoVITS 基底权重: gpt.pth (3.4GB) + s2mel.pth (1.2GB)
├── GPT-SoVITS/                       # GPT-SoVITS 源码仓库 (Gradio 服务 :9872)
├── models/qwen3-tts/                 # Qwen3-TTS 模型
├── assets/live2d/                    # 5 个 Cubism4 模型 (hiyori/akari/wanko/tororo/hijiki)
├── webui_server.py / webui_templates/ / webui_static/   # WebUI 总控制台 (:5000)
├── 对话DEMO/voice_chat_demo.py       # 进程内直连的语音闭环 Demo
└── .env                              # 环境配置 (config.py 唯一权威)
```

### 1.2 模块职责与 VIS 相关度

| 模块 | 职责 | 与 VIS 关系 |
|---|---|---|
| `backend/tts/` | 引擎抽象 + 注册 + 合成 | **引擎层, 只增强不改核心** |
| `backend/tts_engine.py` | 兼容层: 构建并激活 TTSManager | 保留, 作为无 voice_id 的旧入口 |
| `backend/emotion_classifier.py` | 情绪→音色全局映射 | style_controller 的**回退来源** |
| `backend/main.py` | 路由/装配/模块生命周期 | 挂载 `/api/voice/*`, 旧端点保留 |
| `backend/conversation_manager.py` | 对话状态机, `_synthesize_and_play` 直接调 tts | **1 行改造点** |
| `backend/config.py` | 配置单例 | 新增 VIS 配置组 |
| `backend/data/personality.json` | 角色人格(元亨) | **角色绑定锚点(现无 voice 字段)** |
| `updates/live_stream/backend/tts_service.py` | GPT-SoVITS 硬编码调用 | gpt_sovits 适配器实现模板 |
| `backend/audio_enhancer.py` / `noise_suppression.py` | 音频清洗链 | extractor 直接复用 |
| `webui_server.py` | WebUI 总控制台 (:5000) | 新增声音管理页 |

---

## 第二部分: 当前 TTS 架构分析

### 2.1 现状验证(逐文件)

**`backend/tts/base.py` — BaseTTSEngine**
```python
synthesize(text, voice="zh-CN-XiaoxiaoNeural", rate="+0%", **kwargs) -> (np.ndarray, int)
stream_synthesize_text(text, voice="zh-CN-XiaoxiaoNeural", **kwargs) -> AsyncGenerator
```
- `voice` 是**普通字符串音色名**, 无生命周期、无身份语义。
- 有 `load/unload/release_gpu/get_available_voices` —— 与 VIS 生命周期需求吻合。

**`backend/tts/manager.py` — TTSManager**
- 注册表 + `activate("auto")` + 执行期自动回退 + `release_gpu()` —— 结构与白皮书"引擎层不动"的假设**一致**。
- 缺: voice_id 概念、引擎可用性上报(`can_serve`)、按 voice 的绑定管理。

**`backend/tts/qwen3_tts.py` — 克隆引擎(白皮书改造点)**
- `self._prompt_cache` 是**全局单值**, 由 `QWEN3_TTS_REF_AUDIO` 环境变量决定, 每次 `load()` 重新提取。
- `synthesize(text, voice="default")` **忽略 voice 参数** —— 多声音切换完全不可用, 现状是"单 ref_audio 全局克隆"。

**`backend/tts/qwen3_customvoice.py` — 主引擎**
- `SPEAKERS = {"Vivian": ...}` 常量表, 只有 1 个预置说话人; `voice not in SPEAKERS` 时静默回退默认。
- 流式 + CUDA graph 预热齐全, 是 realtime 场景正确基底。

**`backend/tts/edge.py` — 在线引擎**
- 实现完整(分块/预热/中文音色映射), 但 `backend/tts_engine.py:26-27` **只注册了 2 个引擎**:
```python
manager.register_engine("qwen3-tts-customvoice", Qwen3TTSCustomVoiceEngine())
manager.register_engine("qwen3-tts", Qwen3TTSEngine())
```
- 白皮书已知问题 #6 属实: edge 从未被注册, `TTS_ENGINE=edge-tts` 配置无效, 兜底链实际只有 2 级。

### 2.2 结论: 当前抽象是否支持 Voice Identity Layer?

| 能力 | 现状 | 支持 VIS? |
|---|---|---|
| 引擎注册/激活/回退 | ✔ TTSManager | 是 |
| 按 voice_id 合成 | ✘ voice 只是字符串参数 | **否** |
| 多声音切换(克隆) | ✘ 全局单 prompt_cache | **否** |
| 引擎可用性上报 | ✘ 无 `can_serve()` | 否(需适配器层补充) |
| 显存生命周期 | ✔ load/unload/release_gpu + /modules/start\|stop | 是 |
| 情绪驱动 | ✘ 全局 EMOTION_VOICE_MAP 换"音色"而非"风格" | 否(设计已正确改为 style 映射) |
| 音频预处理复用 | ✔ audio_enhancer/noise_suppression | 是 |

**结论: 抽象骨架足够(分层正确), 但"音色即身份"的能力完全缺失。** VIS 作为 `backend/voice_identity/` 独立层**上叠**在 TTSManager 之上是正确决策 —— 不需要改 TTSManager 核心, 但必须:
1. 增强 `qwen3_tts.py` 支持按 voice 切换 prompt cache(白皮书 8.5 已列);
2. 补齐引擎可用性上报(适配器 `can_serve()`);
3. 注册 edge 引擎, 否则 fallback 链无法兑现(白皮书 8.4 的兜底策略依赖它)。

---

## 第三部分: Voice Identity 架构映射

### 3.1 设计模块 → 代码位置映射

| 设计模块 (白皮书) | 代码位置 | 状态 | 说明 |
|---|---|---|---|
| `VoiceIdentityManager` | `backend/voice_identity/manager.py` | **新增** | 门面, 上层唯一入口 |
| `registry` | `backend/voice_identity/registry.py` | **新增** | 激活态 + DB 桥 |
| `profile` (VoiceProfile) | `backend/voice_identity/profile.py` | **新增** | 数据模型 + JSON 读写校验 |
| `extractor` | `backend/voice_identity/extractor.py` | **新增** | 复用 `audio_enhancer` / `noise_suppression` |
| `cache_manager` | `backend/voice_identity/cache_manager.py` | **新增** | 三级缓存 + 8GB 预算 |
| `permission` | `backend/voice_identity/permission.py` | **新增** | 权限策略引擎 |
| `style_controller` | `backend/voice_identity/style_controller.py` | **新增** | 情绪/风格/quality_mode → 引擎参数; 回退 `emotion_classifier.EMOTION_VOICE_MAP` |
| `db` (voice_identity.db) | `backend/voice_identity/db.py` | **新增** | 4 表 schema, 无现存物 |
| `engines/` 适配器 | `backend/voice_identity/engines/` | **新增** | gpt_sovits 模板 = `updates/live_stream/backend/tts_service.py` |
| TTSManager (引擎层) | `backend/tts/manager.py` | **已有, 不动** | ✔ 审计确认无需改 |
| BaseTTSEngine | `backend/tts/base.py` | **已有, 不动** | ✔ |
| qwen3_tts (prompt cache 全局) | `backend/tts/qwen3_tts.py` | **已有, 需最小增强** | `set_prompt_cache()` / 按 voice 切换 |
| qwen3_customvoice (SPEAKERS) | `backend/tts/qwen3_customvoice.py` | **已有, 零改动** | ✔ (SPEAKERS 常量经 adapter 映射) |
| edge | `backend/tts/edge.py` | **已有 + 必须注册** | `tts_engine.py` 未注册 — 见风险 R5 |
| tts_engine 兼容层 | `backend/tts_engine.py` | 已有, 保留 | 旧调用入口 |
| emotion_classifier | `backend/emotion_classifier.py` | 已有, 复用 | 回退来源 |
| 情绪→音色改造点 | `backend/main.py:655/674/736/770` | 已有, 改造 | `/chat` `/synthesize` `/synthesize/stream` |
| 调用点改造 | `backend/conversation_manager.py:284` | 已有, 1 行 | `_synthesize_and_play` |
| 直播调用点 | `updates/live_stream/backend/live_stream_manager.py` | 已有, v1.1 迁移 | 经 live_control 插件 |
| 角色绑定 | `backend/data/personality.json` | 已有, 扩展 | **见风险 R3** |
| 配置 | `backend/config.py` + `.env` | 已有, 扩展 | VIS_* 键组 |
| REST 挂载 | `backend/main.py` | 已有, 新增 | `/api/voice/*` |

### 3.2 关键结构性事实

- `backend/voice_identity/` **完全不存在**(白皮书设想的模块是全新目录, 无冲突)。
- `voice_identity.db` 不存在 —— 与 `memories.db` / `memories_v2.db` 同为 SQLite 但属独立领域, 无合并需求(见第五部分)。
- **角色系统现状**: 只有 `personality.json`(无 `character.json` / `character.yaml`, 全仓 grep 无结果); 无 avatar 绑定配置; Electron 桌宠配置在 `%APPDATA%/yuanheng-avatar/avatar-config.json`(运行时, 仅位置持久化)。
- 直播硬编码确认: `models.py:46-51` `sovits_model/gpt_model/ref_audio_path/ref_text_path` 全局单值, `tts_service.py:262-266` 每次任务校验权重签名并 `change_sovits_weights` 热切换 —— **与白皮书 10.2 描述完全一致**。

---

## 第四部分: 接口兼容性分析

### 4.1 TTS 接口演进判定: 扩展, 不重构

```
现状:  tts.generate(text)                      # 实际签名 synthesize(text, voice="Vivian")
未来:  tts.generate(text, voice_id, emotion, quality_mode, scenario)
```

**判定: 扩展接口 + 保持旧接口双轨。**

依据:
- `TTSManager.synthesize/stream_synthesize_text` 的 `**kwargs` 透传机制(manager.py:128/161)已为 voice 类扩展参数留了口子, 但 **VIS 不应走这条路径** —— 白皮书设计正确: 上层只调 `voice_identity_manager.generate(...)`, TTSManager 保持原签名给旧调用方。
- 兼容保障: `voice_identity_manager.generate` 内部产出 `(audio, sr)` 流, 与 `stream_synthesize_text` 消费方(conversation_manager / main.py 播放线程 / 桌宠)协议一致, 替换点只在一处。
- **必须保留旧端点**: `/synthesize`、`/synthesize/stream`、`/chat`(SSE)是 WebUI 与测试脚本(`对话DEMO/test_*.py`)的硬依赖, 不可破坏。

**修改位置**:
- 新增 `backend/voice_identity/manager.py` 的 `generate()`(新接口);
- `backend/main.py` `/api/voice/synthesize*`(新端点, 旧端点不动);
- `backend/conversation_manager.py:284` `_synthesize_and_play` 改为经 VIS(1 行, 注入 voice_id 后调用)。

### 4.2 Character 绑定分析

**现状**: 角色 = `personality.json`(名字/性格词/口头禅), 无 voice / live2d 绑定; WebUI 有 `/personality` 端点读写它。

**设计冲突点(必须解决)**:
- 白皮书 10.1 提出新增 `backend/data/character.yaml` 绑定文件;
- 但项目**现有角色载体是 `personality.json`**, 且 `context_manager.py:34` 已硬编码 `DATA_DIR / "personality.json"`, WebUI `/personality` 端点已对接。

**审计建议: v1 直接扩展 `personality.json`**(追加 `voice_id` / `live2d_model` / `voice_style` 可选字段), **不新建 character.yaml** —— 避免"两个角色文件"双源真相; 若未来多角色, 再以 character registry 收编。白皮书 10.1 需按此修订(它是唯一设计依据, 文档与实现冲突时需同步更新, 白皮书自己也如此规定)。

### 4.3 Emotion 系统分析

**现状链路**:
```
/chat:  LLM 文本 chunk → resolve_voice_for_emotion(text, base_voice, enabled=config.emotion_enabled)
        → 返回 Edge-TTS 音色 ID → tts_engine.stream_synthesize_text(text, voice=该ID)
```

**已发现的现存缺陷(设计落地前必须先修)**:
- `config.emotion_enabled` 默认 `"false"`(config.py:62), 情绪→音色在默认配置下**完全不生效**;
- 即使开启: `resolve_voice_for_emotion` 返回的是 Edge ID(如 `zh-CN-XiaoyiNeural`), 而默认引擎是 `qwen3-tts-customvoice`, 其 `synthesize` 里 `voice not in SPEAKERS → 静默回退默认音色`(qwen3_customvoice.py:123-124) —— **情绪映射对默认引擎是静默失效的**;
- 全局 `EMOTION_VOICE_MAP` 把"情绪"映射成"换一个人", 与 VIS 的"同一声音换风格"哲学相悖。

**VIS 设计验证**: style_controller 以 `profile.style.emotions` 为准(rate/pitch/引擎情绪参数), 无映射时回退 `emotion_classifier.resolve_voice_for_emotion` —— 方向正确。落地要求:
- style_controller 必须**按引擎类型区分**: customvoice 用风格参数(无多音色), edge 用音色映射, gpt-sovits 用 `gpt_sovits_emotion` + `ref_audio`;
- 显式传入 `emotion=None` 时内部调 `classify_emotion(text)`(已有, 直接复用);
- 修复现存缺陷 1/2(见第八部分 S1)。

---

## 第五部分: 数据库设计审计

### 5.1 现状

| 项目 | 现状 |
|---|---|
| SQLite | ✔ `backend/data/memories.db`(v1 真实数据)、`memories_v2.db`(5 表空壳) |
| ORM | ✘ 无(项目全程 `sqlite3` 原生/直接文件, 无 SQLAlchemy 依赖) |
| 配置库 | ✘ 无(配置 = `.env` + `config.py` Pydantic 单例) |

### 5.2 voice_identity.db: 独立 vs 合并

**判定: 独立, 不合并。** 理由:

1. **生命周期不同**: memories 由对话/摘要驱动(待重建), voice_identity 由声音资产管理驱动 —— 各自独立演进、独立备份/迁移;
2. **访问并发域不同**: 直播/桌宠/WebUI 多场景访问 voice_identity, 与记忆写入并发路径不同, WAL 独立更安全;
3. **已有先例**: 项目本身就是"一域一库"(memories.db / memories_v2.db), VIS 独立库符合既有模式;
4. **合并的代价**: 需要改 memories schema + 重建记忆管线时牵动 VIS, 违反"不破坏现有架构"硬约束。

**落地建议**:
- 文件位置按白皮书: `backend/voice_identity/voice_identity.db`(SQLite, WAL);
- **不使用 ORM** —— 与项目现状一致, 用 `sqlite3` 标准库 + `SCHEMA` 常量 + 幂等 `CREATE TABLE IF NOT EXISTS`(白皮书 db.py 设计已如此, ✔);
- 时间字段统一 ISO 字符串(与白皮书 schema 一致), 与 memories.db 现状风格对齐;
- `PRAGMA foreign_keys=ON` + 删除级联事务(白皮书 5.5, ✔);
- 补一条白皮书未提的: `voice_models.file_hash` 建**唯一索引**(内容寻址去重依赖它, 当前 schema 未声明 UNIQUE)。

---

## 第六部分: 模型生命周期分析 (RTX 4060 Laptop 8GB)

### 6.1 显存账本(实测依据)

| 项 | 估算 | 说明 |
|---|---|---|
| ASR SenseVoiceSmall (FP16) | ~1.5GB | 已有, /modules 管理 |
| Qwen3-TTS 0.6B CustomVoice (bf16) | ~2.0-2.5GB | faster-qwen3-tts + CUDA graph 常驻 |
| Qwen3-TTS 0.6B Base (bf16, 克隆) | ~2.0-2.5GB | 与 CustomVoice **互斥**(模型不同) |
| GPT-SoVITS 推理态 | ~3.0-3.5GB | **独立进程**(Gradio :9872), 权重在 checkpoints/ 本地存在(gpt.pth 3.4GB / s2mel.pth 1.2GB 为磁盘, 加载后显存另计) |
| Live2D / LLM / 系统 | ~1GB | 常驻 |

**关键事实**: GPT-SoVITS 是**独立 Gradio 进程**, 其显存不归 backend 进程管 —— VIS 的 `cache_manager` 无法直接 `release_gpu()` 它, 只能经 `/change_sovits_weights` 热切换(已有能力)或按场景互斥加载。

### 6.2 三引擎加载/切换成本

| 操作 | 成本 | 对策 |
|---|---|---|
| CustomVoice load + CUDA graph 预热 + 端到端预热 | ~30-60s | 已有, 维持; VIS 不应反复 load |
| Qwen3 Clone `create_voice_clone_prompt` | **3-10s/次**(实测量级) | **必须磁盘持久化 prompt cache, 激活时加载** —— 见风险 R6 |
| GPT-SoVITS 权重热切换 | ~1-3s/次 | 已由 tts_service 实现, 复用 |
| 引擎间切换(Clone ⇄ CustomVoice) | ~60s+ | 8GB 下必须互斥 —— `can_coexist()` 返回 False |

### 6.3 Model Cache Manager 设计要求(审计修订)

白皮书第七章方向正确, 补充硬约束:

1. **热区上限**: 显存热区只允许**一个** Qwen3 引擎实例(CustomVoice 或 Clone)+ 一个激活 prompt cache; `VIS_ACTIVE_LIMIT` 控制的是**内存热区 profile 数**(白皮书已有), 显存层面另加 `active_engine=1` 强约束;
2. **预算检查实现**: 用 `torch.cuda.memory_allocated()` 实测 + 白皮书估算表, 提供 `can_coexist(engine_a, engine_b)`(白皮书 7.2 已有);
3. **prompt cache 持久化**: profile 激活时从磁盘 `prompt_cache.pt` 加载(白皮书 7.1), 但需先验证 faster-qwen3-tts 是否暴露 prompt 序列化 API —— **未验证项, 见风险 R6**;
4. **对齐 `/modules/stop`**: VIS `release_gpu()` 必须与 main.py:1415 的模块生命周期联动(白皮书 11.3 ✔);
5. **live 场景**: GPT-SoVITS 常驻 Gradio 进程 + backend 内 ASR+Qwen3 时, 总显存 ≈ 1.5+2.5+3.5 = 7.5GB —— **在 8GB 边缘**, 直播时建议 backend 释放 Clone 引擎, 只留 CustomVoice 做弹幕 realtime 兜底。

---

## 第七部分: 风险发现

### R1 [架构-高] 直播 TTS 与主链路 TTS 双轨脱节
- **证据**: `live_stream_manager` → `tts_service.enqueue_text` 直连 Gradio :9872; 主链路 `conversation_manager` → `TTSManager`。两套调用链、两套播放器(winsound vs sounddevice)。
- **影响**: VIS 若在 v1 只做主链路, 直播仍是"第二张皮"; 白皮书 v1.1 才迁移, 风险被接受但**必须明确 API 冻结点**。
- **方案**: gpt_sovits 适配器以 `tts_service.GradioClient` 为模板独立实现(v1); v1.1 让 live_stream 改调 VIS 后**删除/降级** tts_service 为 legacy 壳, 避免双维护。

### R2 [架构-中] GradioClient 重复实现漂移
- **证据**: 白皮书 8.5 明确 gpt_sovits 适配器"复制其 GradioClient/权重热切换逻辑"。
- **影响**: 两份协议代码(api_name 发现 / change_sovits_weights / inference 参数序)未来升级时漂移。
- **方案**: 适配器内新建 `engines/_gradio.py` 作为**唯一实现**, 直播 legacy 层暂留原文件; v1.1 迁移后统一引用。比"复制粘贴"多一层, 但消除漂移。

### R3 [数据-高] 角色绑定双源真相风险
- **证据**: 白皮书 10.1 新增 `character.yaml`, 但 `personality.json` 已是事实角色载体(`context_manager.py:34` + `/personality` 端点)。
- **影响**: 两个文件都含角色信息, WebUI 改人格时 voice 绑定不同步。
- **方案**: v1 扩展 `personality.json`(追加 `voice_id` 等字段), 不建 character.yaml(见 4.2)。**需修订白皮书 10.1。**

### R4 [性能-高] 8GB 显存临界共存
- **证据**: 第六部分账本, live 场景 ≈7.5GB。
- **影响**: GPT-SoVITS + Qwen3 Clone 同时激活必 OOM。
- **方案**: cache_manager `can_coexist()` + 场景互斥策略(白皮书 7.2 已有, 落地为**硬开关**而非建议); 直播时自动释放 Clone 引擎。

### R5 [数据-中] 引擎注册表缺口 —— edge 未注册
- **证据**: `tts_engine.py:26-27` 仅注册 2 引擎; 白皮书 8.4 兜底策略依赖 edge。
- **影响**: `quality_mode=fallback` 路径无法兑现; 现有 `/tts/engine` 热切换选不到 edge。
- **方案**: 必须修改 `tts_engine.py._build_default_manager()` 注册 edge(白皮书已知问题 #6 的修复并入 V1)。

### R6 [数据-高] prompt cache 持久化可行性未验证
- **证据**: `qwen3_tts.py:93` 用 `model.create_voice_clone_prompt(ref_audio, x_vector_only_mode=True)`; 白皮书 7.1 假设可存 `prompt_cache.pt` 并加载。
- **影响**: 若 faster-qwen3-tts 无 prompt 序列化 API, 每次激活需重提取(3-10s), 多声音切换延迟不可接受。
- **方案**: **V1 前必须先做 spike**(见 M1 验收): 验证 `create_voice_clone_prompt` 返回值可否 save/load。备选方案: 持久化 `embedding.npy`(x-vector 向量)+ 引擎侧重建 prompt; 最坏情况退化为"激活时提取 + 会话级缓存", 仍比现状(每次 load 提取)好。

### R7 [接口-中] 情绪→音色现存缺陷(静默失效)
- **证据**: `config.emotion_enabled` 默认 false(config.py:62); customvoice 引擎下 edge 音色 ID 被 `voice not in SPEAKERS` 静默吞掉(qwen3_customvoice.py:123-124)。
- **影响**: 用户开情绪映射后无任何反馈, 调试困难; VIS style_controller 若继承此逻辑将同样失效。
- **方案**: 见 4.3 三条 + 第八部分 S1。

### R8 [数据-中] 声音文件生命周期管理
- **证据**: 白皮书 staging 临时区/原子 rename 已有设计; 现状 `QWEN3_TTS_REF_AUDIO` 指向 `index-tts/examples/voice_01.wav`(示例文件, 非受管资产)。
- **影响**: 文件散落、无哈希去重、误删风险。
- **方案**: extractor 产物全部进 `voice_identity/cache/<voice_id>/`, 源文件只读引用 + sha256 校验(白皮书 7.4 ✔); `delete_profile` 级联清理磁盘; staging 失败即清。

### R9 [低] 现存遗留缺陷(不影响 VIS, 但应在窗口期顺手修)
- `/ws` 路由 `handle_ws` AttributeError(main.py:1492-1499);
- 记忆 stub(context_manager.py:146-171)与 /memory 端点占位(main.py:1461-1490);
- 插件调度层 stub(plugin_sdk/plugin_manager)。

---

## 第八部分: 修改建议

### 8.1 必须修改(编码前冻结)

| # | 文件 | 修改 | 原因 |
|---|---|---|---|
| M1 | `backend/tts/qwen3_tts.py` | `_prompt_cache` 单值 → 按 voice 切换: 新增 `set_prompt_cache(prompt)` / 构造/`prepare(profile)` 接受 ref_audio; 默认行为不变 | 克隆引擎多声音切换的**唯一改造点**(白皮书 8.5 已列, 审计确认必要) |
| M2 | `backend/tts_engine.py` | `_build_default_manager()` 注册 `edge-tts` 引擎 | 兜底链兑现 + 修复已知问题 #6; VIS fallback 路径依赖 |
| M3 | `backend/data/personality.json` | 追加可选字段: `voice_id` / `live2d_model` / `voice_style` | 角色绑定锚点(替代 character.yaml, 见 R3) |
| M4 | `backend/config.py` | 新增 VIS 配置组(12.1 全部键 + 默认值) | 配置单例是项目唯一权威, VIS 不得另起配置 |
| M5 | `backend/main.py` | 挂载 `backend/voice_identity/api.py` 路由(前缀 `/api/voice`); `conversation_manager._synthesize_and_play` 改走 VIS(1 行) | 接口双轨落地 |

### 8.2 建议修改(随各 Milestone)

| # | 文件 | 修改 | 时机 |
|---|---|---|---|
| S1 | `backend/emotion_classifier.py` + `config.py` | `resolve_voice_for_emotion` 增加引擎感知(非 edge 引擎时返回原 voice + 情绪名, 供 style_controller 使用); `emotion_enabled` 默认值保持 false 但文档标注 | M3 |
| S2 | `updates/live_stream/backend/tts_service.py` | 提取 GradioClient 到共享模块(或适配器内唯一实现, legacy 壳保留) | M4 |
| S3 | `backend/voice_identity/db.py` | `voice_models.file_hash` 建唯一索引 | M1 |
| S4 | `webui_server.py` / `webui_templates/index.html` | 声音管理页(上传/创建/试听/激活/绑定) | M4 |
| S5 | `backend/main.py` /modules/stop | VIS `release_gpu()` 与模块生命周期联动 | M2 |
| S6 | `.env.example` | 补 VIS_* 键注释 | M1 |
| S7 | `对话DEMO/voice_chat_demo.py` | 预留 `--voice-id` 参数(可选, 保持默认路径) | M3 |

### 8.3 新增文件清单

```
backend/voice_identity/
├── __init__.py          # 导出 voice_identity_manager 单例
├── manager.py           # 门面 (generate / create_profile / activate / ...)
├── registry.py          # 激活态注册表 + DB 桥
├── profile.py           # VoiceProfile 模型 + validate + schema 迁移
├── extractor.py         # 检测/预处理/embedding (复用 audio_enhancer)
├── cache_manager.py     # 三级缓存 + pin/unpin + LRU + GPU 预算
├── permission.py        # check/authorize/revoke
├── style_controller.py  # 情绪/quality_mode → voice_spec (回退 emotion_classifier)
├── db.py                # SCHEMA + init_db + CRUD (sqlite3, 无 ORM)
├── constants.py         # 枚举 (VoiceType/QualityMode/Scenario/状态)
├── errors.py            # 异常体系 (VoiceNotFound/PermissionDenied/...)
├── api.py               # FastAPI APIRouter, 前缀 /api/voice (M5 挂载)
└── engines/
    ├── __init__.py      # 适配器工厂
    ├── base.py          # VoiceEngineAdapter 抽象基类 (prepare/stream/release/can_serve)
    ├── _gradio.py       # GradioClient 唯一实现 (防 R2 漂移)
    ├── gpt_sovits.py    # 高保真, 基于 tts_service 范式
    ├── qwen3_clone.py   # realtime, 基于 qwen3_tts + M1
    ├── qwen3_customvoice.py  # 预置说话人映射
    ├── edge.py          # 兜底
    └── index_tts.py     # 骨架 (NotImplemented)
```

---

## 第九部分: 最终实施路线 Milestone V1-V5

### M1: Voice Identity Core(领域骨架 + 接口冻结)

- **目标**: `backend/voice_identity/` 包落地、DB 建表、profile 生命周期 CRUD、配置组; **不做引擎合成**; 验证 prompt cache 序列化可行性(spike)。
- **修改文件**: `backend/config.py`(VIS 组)、`backend/tts_engine.py`(注册 edge)、`backend/data/personality.json`(绑定字段)、`.env.example`。
- **新增文件**: `voice_identity/__init__.py manager.py registry.py profile.py db.py constants.py errors.py`。
- **验收标准**:
  - `python -c "from backend.voice_identity import voice_identity_manager"` 零依赖启动;
  - `init_db()` 幂等建 4 表 + file_hash 唯一索引(PRAGMA foreign_keys=ON);
  - profile create/get/list/update/delete/activate/deactivate 全通过(单测或 CLI);
  - spike 报告: faster-qwen3-tts prompt cache 可持久化性结论(决定 M2 的 qwen3_clone 实现策略);
  - `GET /tts/engines` 出现 `edge-tts`。

### M2: 引擎适配器 + 引擎增强(合成链路打通)

- **目标**: 4 个适配器 + `qwen3_tts.py` 多声音改造 + `manager.generate()` 端到端可用(单引擎); quality_mode 选择器; 情绪/风格解析。
- **修改文件**: `backend/tts/qwen3_tts.py`(M1)、`backend/main.py`(挂载 api.py + /api/voice/synthesize*)、`backend/conversation_manager.py`(改调 VIS, 1 行)。
- **新增文件**: `voice_identity/engines/*`(全部)、`voice_identity/style_controller.py`、`voice_identity/api.py`(合成部分)。
- **验收标准**:
  - `voice_identity_manager.generate(text, voice_id, emotion="happy", quality_mode="realtime")` 经 qwen3_clone 产出音频流, 首块延迟与现有 CustomVoice 量级一致;
  - 克隆声音切换(2 个 profile 交替)不重载模型, 延迟 ≤ 10s(取决于 M1 spike 结论);
  - quality_mode=high → gpt_sovits(Gradio 可达时)/ qwen3_clone 降级; fallback → edge;
  - 引擎失败按 fallbacks 自动降级, 无异常上抛;
  - `/synthesize` 旧端点行为不变(回归)。

### M3: 提取管线 + 缓存 + 权限(资产生产闭环)

- **目标**: 声音创建 8 步流程 + task 模型; extractor(复用 audio_enhancer); cache_manager(pin/unpin/LRU/GPU 预算); permission 基础策略; 情绪缺陷修复(S1)。
- **修改文件**: `backend/emotion_classifier.py` / `config.py`(S1)、`backend/main.py`(/api/voice 资产管理端点)。
- **新增文件**: `voice_identity/extractor.py cache_manager.py permission.py api.py`(资产管理部分)。
- **验收标准**:
  - 上传 30s 素材 → 检测 → 清洗 → embedding → 试听 → 激活全流程 CLI/API 可跑通, 产物落 `cache/<voice_id>/`, DB 登记齐全;
  - 相同源文件二次创建命中哈希去重, 不重复计算;
  - `cache_stats()` 返回三级缓存大小与预算; `can_coexist()` 按预算返回正确值;
  - 未授权主体 delete/modify 被拒(PermissionDenied);
  - 情绪→风格: 同一 voice_id 在 happy/sad 下产出不同语速/音高参数(引擎支持处)。

### M4: API + WebUI + 角色绑定 + 直播接入

- **目标**: `/api/voice/*` 全端点 + 任务轮询; WebUI 声音管理页; personality.json 绑定生效(`/chat` 用角色 voice_id 说话); 直播经 live_control 改调 VIS(scenario="live", room 授权); GradioClient 单一实现(S2)。
- **修改文件**: `backend/main.py`(完整挂载)、`webui_server.py` + `webui_templates/index.html`、`updates/live_stream/backend/live_stream_manager.py` 与 `plugins/live_control/`、`updates/live_stream/backend/tts_service.py`(legacy 壳)。
- **新增文件**: WebUI 声音管理页资源(webui_static 或模板内联)。
- **验收标准**:
  - WebUI: 上传/创建进度(task 轮询)/试听/激活/绑定角色全流程可视可用;
  - WebUI 对话页说话声音 = 绑定的 voice_id(改 personality.json 后立即生效);
  - 直播场景: 弹幕以 room: 主体授权后经 VIS high 模式播出, 权重按 profile 热切换;
  - live_stream legacy 接口仍可用(兼容期);
  - `/api/voice/usage` 有 desktop/live 场景统计。

### M5: 优化加固 + 量化验证

- **目标**: 显存互斥策略硬落地; 多场景延迟基线; 批量合成; 错误/审计打磨; 回归全量。
- **修改文件**: `voice_identity/cache_manager.py`(预算水位细化)、`backend/main.py`(/modules 联动)、`voice_identity/manager.py`(并发锁/原子写收尾)。
- **新增文件**: 测试(`对话DEMO/test_voice_identity.py` 风格)、`docs/VIS 性能基线.md`(可选)。
- **验收标准**:
  - 直播(高保真)+ 桌宠(实时)并存场景: 显存实测 < 8GB, 引擎互斥热切换正确;
  - 端到端延迟基线表: realtime 首块 / high 合成 / 切换成本 / 缓存命中率;
  - 批量模式: 脚本 → 分段合成 → 导出, usage 限额生效;
  - 旧接口回归: /chat、/synthesize、/synthesize/stream、桌宠 WS、voice_chat_demo 全部通过(复用 `对话DEMO/test_comprehensive.py`)。

### 里程碑依赖图

```
M1 (骨架+冻结) ──▶ M2 (合成链路) ──▶ M3 (资产生产) ──▶ M4 (产品化) ──▶ M5 (加固)
        └── spike: prompt cache 持久化 决定 M2 qwen3_clone 实现
        └── edge 注册、personality 扩展 (M1 内完成, 解耦)
```

---

## 第十部分: 审计判定清单

| # | 白皮书设计项 | 判定 | 备注 |
|---|---|---|---|
| 1 | 分层架构 (Character → VIS → TTSManager → Audio) | **通过** | 依赖单向, 与现有代码吻合 |
| 2 | TTSManager / BaseTTSEngine 零改动 | **通过(有条件)** | 结构零改动成立; qwen3_tts 需最小增强 |
| 3 | `backend/voice_identity/` 独立模块 | **通过** | 全新增, 无冲突 |
| 4 | voice_identity.db 独立 | **通过** | 与一域一库既有模式一致 |
| 5 | 角色绑定 character.yaml | **不通过, 需修订** | 改为扩展 personality.json(R3) |
| 6 | 引擎选择策略 (quality_mode) | **通过(有条件)** | 依赖 edge 注册(M2), 否则 fallback 空转 |
| 7 | 三级缓存 + 8GB 预算 | **通过(有条件)** | prompt cache 持久化待 spike(R6); 互斥须硬约束 |
| 8 | 情绪/风格融合 | **通过(有条件)** | 先修现存静默失效缺陷(S1) |
| 9 | GPT-SoVITS 适配器 | **通过(有条件)** | 独立进程, 显存账本需纳入调度 |
| 10 | 错误处理与降级链 | **通过** | 与"永不静默失败"项目原则一致 |

**总体结论**: 白皮书架构与现有代码兼容度约 90%, 剩余 10% 为: 角色绑定载体修订、prompt cache 持久化 spike、edge 注册、情绪缺陷修复。**按第八部分 M1-M5 执行即可直接进入 V1 编码, 无需再返工架构层。**

---

*本报告基于 2026-08-03 仓库实测代码生成; 与白皮书冲突处已在正文标注, 请以本报告第七/八部分为准修订白皮书后再进入编码。*
