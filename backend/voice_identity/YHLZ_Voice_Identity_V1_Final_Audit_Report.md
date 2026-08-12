# YHLZ Voice Identity System v1.0
# Milestone V1 最终集成审计报告

> 审计阶段: V1.7 V1 完整审计与集成验证
> 审计日期: 2026-08-04
> 审计范围: V1.1 ~ V1.6 全部实现 + 架构独立性 + 兼容性
> 审计结论: **V1 通过** ✅

---

## 一、完成项

### V1.1 数据模型与数据库核心 ✅
- `voice_identity.db` 独立 SQLite 数据库 (位于 `backend/data/`)
- 三表就位: `voice_profiles` / `voice_models` / `voice_usage`
- `schema.py` 集中 DDL + 版本迁移 (v1→v2 幂等)
- `database.py` 线程安全 (`threading.RLock`) + CRUD 原语
- `models.py` Pydantic 类型安全模型 + JSON 序列化
- 模块导入无副作用 (懒初始化单例 `get_db()`)

### V1.2 Voice Profile 系统 ✅
- `profile.py` 提供 `VoiceProfileStore` CRUD
- 自动生成唯一 `voice_id` (`{slug(name)}_{8hex}`, 冲突重试)
- 完整状态机: `creating/processing/ready/active/disabled/deleted`
- 软删优先 (保留数据), 硬删能力保留
- 非法状态转移抛 `VoiceProfileError`

### V1.3 Voice Registry 注册中心 ✅
- `registry.py` 提供 `register_voice/unregister_voice/get_voice/list_voice`
- "可发现"语义层: `ready/active` 可发现, 其他不可发现
- 支持三类声音: `character` / `user` / `system`
- `list_voice` 优先级: 显式 `status` > `discoverable_only`
- 不直接调用 TTS, 不处理模型加载 (纯身份管理)

### V1.4 Voice Manager 生命周期管理 ✅
- `manager.py` 统一编排 Profile / Registry / Cache
- 生命周期: `CREATED → PROCESSING → READY → ACTIVE → DISABLED → DELETED`
- API: `create_voice / activate_voice / disable_voice / delete_voice / get_voice`
- Cache 协议 duck-typed (`prepare/load/unload/remove`), 可选注入
- **禁止直接调用 GPT-SoVITS / 任何 TTS 引擎** (AST 校验通过)

### V1.5 Cache Manager 缓存系统 ✅
- `cache_manager.py` 永久缓存管理 (磁盘 + 内存)
- 管理: embedding 缓存 / engine cache / prompt cache
- API: `save / load / remove / exists` (+ V1.4 协议)
- 兼容 M0: Qwen3 多 voice cache (embedding.pt + prompt.pt + metadata.json)
- 兼容 M0: GPT-SoVITS 权重路径登记 + 热切换
- 生命周期: 删除→清缓存, 禁用→保留缓存
- **不 import backend.tts** (AST 校验通过, duck-typed 适配器注入)

### V1.6 Voice Identity Service API ✅
- `service.py` 内部 Service Layer (非 Web API, 无 FastAPI)
- API: `create_voice / get_voice / list_voice / delete_voice / select_voice`
- 单激活策略: 同时仅一个 `active`, 切换时旧声音 `active→ready`
- 选中状态持久化 (`schema_meta` 表, 重启可恢复)
- `create_default()` 工厂便于生产接线
- `health()` 诊断快照

### V1.7 最终集成审计 ✅
- 30 项集成测试全部通过 (隔离临时 DB, 不污染生产)
- 架构独立性验证通过
- 兼容性验证通过

---

## 二、代码统计

### 新增文件 (9 个核心模块 + 6 个分阶段审计报告 + 1 个集成测试)

| 文件 | 行数 | 职责 |
|------|------|------|
| `__init__.py` | 99 | 统一导出 + 懒初始化入口 |
| `database.py` | 416 | SQLite 连接 + CRUD + 迁移 + meta |
| `models.py` | 175 | Pydantic 模型 (Profile/Model/Usage) |
| `schema.py` | 120 | DDL + 版本常量 + 枚举 |
| `profile.py` | 212 | ProfileStore CRUD + 状态机 |
| `registry.py` | 161 | Registry 发现层 |
| `manager.py` | 251 | Manager 生命周期编排 |
| `cache_manager.py` | 332 | Cache 永久缓存 + M0 桥接 |
| `service.py` | 239 | Service 统一 API + 单激活 |
| **核心代码合计** | **2005** | **9 个文件** |

### 测试覆盖
- 集成测试: `对话DEMO/test_v1_final_audit.py` (30 用例, 全通过)
- 隔离策略: 临时 DB + 临时缓存目录 + Duck-typed 假适配器
- 覆盖层次: Schema/DB → Profile 状态机 → Registry 发现 → Manager 生命周期 → Cache 桥接 → Service 单激活 → 启动隔离

### 数据库表结构

```
voice_profiles (声音身份主表)
├── id, voice_id (UNIQUE), owner_id, name, type, language
├── status, engine
├── reference_audio, style (JSON), metadata (JSON)
└── created_at, updated_at (触发器自动刷新)

voice_models (引擎模型/缓存路径登记)
├── id, voice_id (FK→profiles), engine
├── model_path, cache_path, hash, loaded
└── created_at

voice_usage (使用统计)
├── id, voice_id (UNIQUE, FK→profiles)
└── usage_count, last_used, duration

schema_meta (键值元数据, V1.6 选中状态持久化)
└── key (PK), value
```

---

## 三、架构图

```
                 Character / User / System
                          │
                          ▼
          ┌───────────────────────────────────┐
          │      VoiceIdentityService         │  ← V1.6 统一入口
          │  (create/get/list/delete/select)  │     未来 WebUI/CLI/Plugin 调用
          └───────────────┬───────────────────┘
                          │
                          ▼
          ┌───────────────────────────────────┐
          │          VoiceManager             │  ← V1.4 生命周期编排
          │  (create/activate/disable/delete) │
          └───────┬───────────────┬───────────┘
                  │               │
                  ▼               ▼
      ┌───────────────────┐  ┌───────────────────────┐
      │  VoiceRegistry    │  │  VoiceCacheManager    │  ← V1.5 永久缓存
      │  (V1.3 发现层)    │  │  (桥接 TTS Adapter)   │
      │  register/list    │  │  prepare/load/unload  │
      └────────┬──────────┘  └───────────┬───────────┘
               │                         │ duck-typed
               ▼                         ▼
      ┌───────────────────┐  ┌───────────────────────────────┐
      │ VoiceProfileStore │  │  TTS Adapter Layer (M0, 未污染)│
      │  (V1.2 CRUD+状态机)│  │  Qwen3 / GPT-SoVITS / Edge    │
      └────────┬──────────┘  └───────────────────────────────┘
               │
               ▼
      ┌───────────────────┐
      │  VoiceIdentityDB  │  ← V1.1 数据层
      │  (sqlite3 + 锁)   │
      └────────┬──────────┘
               │
               ▼
      backend/data/voice_identity.db
```

### 依赖方向 (严格单向, 无环)

```
Service → Manager → {Registry, Cache}
                   ↓
                 Store → DB → voice_identity.db
                 
Cache ──(duck-typed 适配器注入)──→ TTS Adapter (M0, 解耦)
```

**关键约束**: voice_identity 模块**不 import backend.tts**, 仅通过构造函数注入适配器实例 (duck-typed)。TTS Adapter 模块**不 import voice_identity**。双向解耦已 AST 校验确认。

---

## 四、架构独立性审计

### 4.1 Voice Identity 模块边界 ✅
- `voice_identity/` 独立子包, 不依赖 `backend.tts` / `backend.context_manager`
- 唯一外部依赖: `pydantic` (项目已有) + stdlib (`sqlite3/threading/hashlib/shutil`)
- DB 独立: `voice_identity.db` 与 `memories.db` / `personality.json` 物理隔离
- 单例懒加载: `get_db()` 首次调用才建文件, 模块导入零副作用

### 4.2 TTS Adapter 未被污染 ✅
- `backend/tts/qwen3_tts.py` 源码不含 `voice_identity` 引用
- `backend/tts/adapters/gpt_sovits_adapter.py` 源码不含 `voice_identity` 引用
- V1 通过 `VoiceCacheManager` 的 duck-typed 协议 (load_voice/save_voice_cache_to_disk 等) 间接调用, 不修改适配器源码

### 4.3 M0.4 personality.json 字段语义未被改动 ✅
- `context_manager.DEFAULT_VOICE_IDENTITY = {"voice_id": "default", "engine": "qwen3"}` 保持原样
- `main.py` 的 `/personality/voice-identity` 端点 (M0.4) 与 V1 `backend.voice_identity` 模块**完全无关** (同名不同义, M0.4 是 personality.json 字段, V1 是独立子系统)
- `test_voice_identity_compat.py` (M0.4 兼容性测试) 仍通过, 未受 V1 影响

---

## 五、数据库健康审计

### 5.1 自动初始化 ✅
- `VoiceIdentityDB.__init__` → `_connect()` + `init_db()` 幂等建表
- `PRAGMA foreign_keys = ON` + `PRAGMA journal_mode = WAL`
- `schema_meta` 记录 `schema_version = 2`
- `health()` 返回 `{ok, db_path, schema_version, voice_profiles, voice_models, voice_usage}`

### 5.2 表结构校验 ✅
- `voice_profiles` 13 列齐全 (含 V1.2 扩展的 `reference_audio/style/metadata`)
- v1→v2 迁移幂等 (`ALTER TABLE ADD COLUMN`, 缺失才补)
- 外键级联: `voice_models` / `voice_usage` `ON DELETE CASCADE`
- 触发器 `trg_voice_profiles_updated_at` 自动刷新 `updated_at`

### 5.3 CRUD 验证 ✅
- Profile: insert / get / update (字段白名单) / delete (软/硬) 全通过
- Model: insert / get_by_voice / update_loaded / delete 全通过
- Usage: upsert (计数递增) / add_duration / get / delete 全通过
- meta: get / set (UPSERT) / delete 全通过

---

## 六、VoiceManager 生命周期审计

### 6.1 状态机正确性 ✅
```
creating ──→ processing ──→ ready ──→ active ──→ ready (deactivate)
   │             │             │          │
   │             │             │          └──→ disabled
   │             │             └──→ disabled
   │             └──→ disabled
   └──→ ready / disabled / deleted
   
任何状态 ──→ deleted (终态, 仅硬删可移除)
disabled ──→ ready (enable) / creating (重新处理)
```
- 非法转移抛 `VoiceProfileError` (如 creating → active)
- `create_voice` 自动走 creating → processing(有cache时) → ready
- `activate_voice` 要求可发现 (ready/active), active 幂等
- `delete_voice` 软删保留缓存与数据, 硬删级联清理

### 6.2 Cache 联动 ✅
- `activate` → `cache.load` (Qwen3 从磁盘恢复 / GPT-SoVITS 切权重)
- `disable` → `cache.unload` (清内存, 保留磁盘)
- `delete(soft)` → 保留缓存; `delete(hard)` → `cache.remove` (清磁盘+内存+DB记录)
- Cache 操作失败不阻塞生命周期 (try/except 降级为 warning)

### 6.3 约束遵守 ✅
- Manager 不 import `backend.tts` (AST 校验通过)
- Manager 不直接调用 GPT-SoVITS, 仅经 Cache 间接
- Service 单激活: `select_voice` 切换时旧 active → ready (保留可发现)

---

## 七、兼容性审计

### 7.1 启动隔离 ✅
- `import backend.voice_identity` 不创建 db 文件 (懒初始化)
- V1 模块未被 `main.py` / `start.bat` 引用, 当前完全休眠
- 旧启动流程 (后端服务 / GUI / Live2D 桌宠) 零影响

### 7.2 TTS 引擎未受影响 ✅
- `qwen3_tts.py` / `gpt_sovits_adapter.py` 源码未被修改
- M0 多 voice cache 接口 (`load_voice_cache` / `save_voice_cache_to_disk` 等) 原样保留
- V1 `VoiceCacheManager` 通过 duck-typed 调用这些接口, 不改其签名

### 7.3 Live2D / 直播未受影响 ✅
- V1 不涉及 Live2D 模块 (`desktop_avatar_plus.py` 等)
- V1 不涉及直播模块 (`updates/live_stream/`)
- 无任何 import 反向依赖

### 7.4 M0.4 personality 字段共存 ✅
- `personality.json` 的 `voice_identity` 字段 (M0.4, 含 `voice_id`+`engine`) 语义未变
- V1 `backend.voice_identity` 是独立子系统, 与 M0.4 字段同名但不同义
- 两者当前互不引用, 未来 V2 可由 Service 桥接 (遗留项)

---

## 八、遗留问题

### 8.1 V1 未接入生产 (设计如此, 非缺陷)
- V1 Service 尚未被 `main.py` / 任何运行时调用
- `voice_identity.db` 未生成 (懒初始化, 待首次 `get_db()` 调用)
- **这是 V1 设计目标**: "管理声音"层就绪, 待 V2/V3 接线

### 8.2 M0.4 字段与 V1 模块的语义桥接待定
- `personality.json` 的 `voice_identity.voice_id` (M0.4) 与 V1 `VoiceProfile.voice_id` (V1) 当前无映射
- 未来需在 Service 层提供桥接: M0.4 字段 → V1 `select_voice(voice_id)`
- 建议 V2 处理, 不影响 V1 完整性

### 8.3 CacheManager 直接访问 DB 私有属性
- `cache_manager.py` 的 `_upsert_model_record` 使用 `self._db._lock` / `self._db._conn` (私有属性)
- 当前功能正确, 但破坏封装边界
- 建议后续在 `VoiceIdentityDB` 增加 `upsert_model` 公开方法

### 8.4 单激活策略未限制跨 owner
- `select_voice` 全局单激活, 未按 owner/type 隔离
- 多角色场景下可能需 owner 级单激活
- V1 单角色场景够用, 多角色留待 V2

### 8.5 无并发激活竞态保护
- `select_voice` 的 "去激活旧 → 激活新" 非原子操作
- 高并发下可能短暂出现双 active
- V1 内部 Service 低并发场景可接受, WebUI 并发场景需加锁

---

## 九、V2 建议

### V2.1 Voice Clone Engine Integration (主线)
- 声音上传: WebUI 上传参考音频 → Service 创建 Profile
- 音频分析: 校验采样率/时长/信噪比
- Speaker Embedding: 调用 Qwen3 `load_voice` 提取, 经 CacheManager 持久化
- GPT-SoVITS 自动创建: 上传音频 → 训练 → 权重路径登记到 `voice_models`
- Qwen3 Clone 自动绑定: 提取 embedding → 绑定到 Profile

### V2.2 M0.4 桥接
- `personality.json.voice_identity.voice_id` → V1 `select_voice()` 联动
- 启动时读 M0.4 字段, 自动激活对应 V1 Profile
- V1 Profile 变更时回写 M0.4 字段 (单源真相迁移)

### V2.3 WebUI 接入
- FastAPI 端点包装 `VoiceIdentityService` (REST CRUD + select)
- 前端声音管理面板: 列表 / 创建 / 试听 / 选择 / 删除
- 与现有 GUI "Role" 模块整合

### V2.4 多角色 owner 隔离
- `select_voice(owner, voice_id)` 按 owner 级单激活
- 角色切换时自动激活该角色当前选中声音

### V2.5 并发安全强化
- `select_voice` 加 Service 级锁, 保证原子性
- WebUI 并发场景下的竞态保护

### V2.6 缓存预热与显存策略
- 启动时按 `voice_models.loaded` 状态预加载 active 声音
- 显存压力下 LRU 淘汰非 active 的内存缓存
- 与 M0 显存策略 (Qwen3 + GPT-SoVITS 隔离) 对齐

---

## 十、V1 完成后的系统状态

```
                 Character / User / System
                          │
                          ▼
          Voice Identity Core (V1 ✅)
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
     Voice Profile              Voice Registry
     (V1.2 CRUD+状态机)         (V1.3 发现层)
            │
            ▼
     Voice Manager (V1.4 生命周期)
            │
            ▼
     Cache Manager (V1.5 永久缓存)
            │
            ▼
     TTS Adapter Layer (M0, 未污染)
            │
            ▼
     Qwen3 / GPT-SoVITS / Edge
```

### YHLZ 已拥有
- ✅ 声音资产系统 (Profile + Registry)
- ✅ 多声音身份 (voice_id 唯一标识 + 多 owner/type)
- ✅ 多角色基础 (type=character, owner 隔离)
- ✅ 永久缓存体系 (磁盘 + 内存 + voice_models 登记)
- ✅ TTS 解耦架构 (duck-typed 适配器, 双向不 import)
- ✅ 统一服务入口 (Service API, 未来 WebUI/CLI/Plugin 共用)

### 下一阶段 Milestone V2
> **Voice Clone Engine Integration** — 从"管理声音"进入"创造声音"
> - 声音上传 / 音频分析 / Speaker Embedding
> - GPT-SoVITS 自动创建 / Qwen3 Clone 自动绑定

---

## 审计结论

**V1 Voice Identity Core 实现完整, 架构独立, 兼容性良好, 测试通过。**

- 9 个核心模块, 2005 行代码, 30 项集成测试全通过
- 双向解耦 (voice_identity ↔ TTS Adapter) AST 校验确认
- 旧系统 (启动 / TTS / Live2D / 直播 / personality) 零影响
- 可进入 V2 Voice Clone Engine Integration 阶段
