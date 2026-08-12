# YHLZ Voice Identity System V2.2 执行报告

> 版本: V2.2.0
> 生成日期: 2026-08-04
> 依据: YHLZ_V2.2_开发实现_Prompt.txt
> 范围: TTS Adapter 接入 + REST API + WebUI 克隆面板 + 真实端到端克隆闭环

---

## 一、修改文件列表

### 1.1 新增文件(9 个)

| 文件 | 行数 | 职责 |
|---|---|---|
| `backend/voice_identity/adapter/__init__.py` | 48 | 包导出 + 版本号 `2.2.0` |
| `backend/voice_identity/adapter/tts_adapter.py` | 167 | `TTSAdapter` 抽象基类 + `VoiceCacheInfo` + 注册表 |
| `backend/voice_identity/adapter/qwen3_adapter.py` | 230 | Qwen3 适配器 (mock + real) |
| `backend/voice_identity/adapter/gpt_sovits_adapter.py` | 222 | GPT-SoVITS 适配器 (mock + real) |
| `backend/voice_identity/adapter/config.py` | 130 | 配置加载器 + dataclass |
| `backend/voice_identity/adapter/tests/__init__.py` | 1 | 测试包标记 |
| `backend/voice_identity/adapter/tests/test_tts_adapter.py` | 296 | 25 个 Adapter 单元测试 |
| `backend/voice_identity/adapter/tests/test_voice_clone_api.py` | 200 | 9 个 REST API 测试 |
| `voice_clone_config.json` | 32 | 配置文件 (mock 默认) |

### 1.2 修改文件(5 个,均向后兼容)

| 文件 | 改动 |
|---|---|
| `backend/voice_identity/clone/clone_pipeline.py` | CloneResult 增加 4 个扩展字段(adapter/cache_path/embedding_hash/quality_score);Pipeline 新增 `adapter` 参数 + `set_adapter()` + `clone_voice(auto_prepare=True)` |
| `backend/voice_identity/clone/__init__.py` | 版本号 `2.1.0` → `2.2.0`;移除 TTSAdapter 导出(避免循环导入) |
| `backend/voice_identity/service.py` | 新增 `set_adapter()` / `get_adapter()` / `load_adapter_from_config()` / `synthesize()`;`clone_voice` 增加 `auto_prepare` 参数 |
| `backend/voice_identity/__init__.py` | 导出 adapter 全部符号;版本号 `2.1.0` → `2.2.0` |
| `backend/main.py` | 新增 `POST /voice/clone` + `POST /voice/synthesize` 端点;FastAPI import 增加 `UploadFile, File, Form` |
| `webui_server.py` | 新增 `/api/voice/clone` + `/api/voice/synthesize` 代理路由 |
| `webui_templates/index.html` | MODULES 列表新增 `voice_clone` 项;新增 `<div id="page-voice_clone">` 页面 + 3 个 JS 函数 |

---

## 二、新增 API

### 2.1 TTSAdapter 抽象接口(模块级)

```python
class TTSAdapter(abc.ABC):
    name: str
    def prepare_voice(audio_path, feature, metadata=None) -> Result[VoiceCacheInfo]
    def synthesize(voice_id, text, language="zh") -> Result[str]
    def can_serve() -> bool
    def health_check() -> dict
```

### 2.2 VoiceCacheInfo 数据类(对齐 Prompt)

```python
@dataclass(frozen=True)
class VoiceCacheInfo:
    adapter: str
    cache_path: Optional[str]
    embedding_hash: Optional[str]
    quality_score: Optional[float]
    extra: Dict[str, Any]
```

### 2.3 具体适配器(2 个)

| 适配器 | 模式 | 行为 |
|---|---|---|
| `Qwen3TTSAdapter` | mock | `prepare` 返回 `mock_<audio_md5>`;`synthesize` 写正弦波 wav |
| `Qwen3TTSAdapter` | real | 调 `backend.tts.adapters.qwen3_adapter.load_voice` + `save_voice_cache_to_disk`;`synthesize` 调 `engine.synthesize` |
| `GPTSoVITSAdapter` | mock | 同 Qwen3 mock,hash 前缀 `gptsv_` |
| `GPTSoVITSAdapter` | real | 调 Gradio Client `/change_sovits_weights` + `/change_gpt_weights` + `/inference` |

### 2.4 注册表 API(4 个)

```python
register_adapter(name)       # 装饰器注册
get_adapter_class(name)      # 按名取类
list_adapters()              # 列出已注册名
build_adapter(name, config)  # 按名构造实例 → Result[TTSAdapter]
```

### 2.5 配置加载 API(3 个)

```python
load_config(path=None) -> VoiceCloneConfig
build_adapter_from_config(engine, config=None) -> Result[TTSAdapter]
VoiceCloneConfig (dataclass: default_engine/auto_prepare/qwen3/gpt_sovits/validation/upload)
```

### 2.6 Service 新增方法(4 个)

```python
class VoiceIdentityService:
    def set_adapter(adapter: Optional[TTSAdapter]) -> None
    def get_adapter() -> Optional[TTSAdapter]
    def load_adapter_from_config(engine=None, config=None) -> Result[TTSAdapter]
    def synthesize(voice_id, text, language="zh") -> Result[str]
    # clone_voice 新增 auto_prepare 参数
```

### 2.7 Pipeline 升级

```python
class VoiceClonePipeline:
    def __init__(..., adapter: Optional[TTSAdapter] = None)
    def set_adapter(adapter) -> None
    @property
    def adapter -> Optional[TTSAdapter]
    def clone_voice(..., auto_prepare: bool = True) -> Result[CloneResult]

@dataclass(frozen=True)
class CloneResult:
    # V2.1 字段 (向后兼容)
    profile, feature, audio_info, cache_prepared, warnings
    # V2.2 新增字段
    adapter: Optional[str] = None
    cache_path: Optional[str] = None
    embedding_hash: Optional[str] = None
    quality_score: Optional[float] = None
```

### 2.8 REST API(2 个端点)

#### `POST /voice/clone`

**参数**(multipart/form-data):
- `audio`: wav/mp3/flac/ogg/m4a(必填)
- `name`: 声音展示名(必填)
- `engine`: qwen3 / gpt_sovits(默认 qwen3)
- `voice_id`: 显式 ID(可选)
- `language`: zh/en/ja(默认 zh)
- `metadata`: JSON 字符串(gpt_sovits 需含 sovits_model/gpt_model)

**返回**:
- 成功:`{success, voice_id, name, status, engine, warnings, adapter, cache_path, embedding_hash, quality_score}`
- 失败:`{success: false, error, stage: validate|analyze|create_voice|register|cache|service_init}`

#### `POST /voice/synthesize`

**参数**: `voice_id`, `text`, `language`
**返回**: `{success, audio_path, text}` 或 `{success: false, error}`

### 2.9 WebUI 代理路由(2 个)

- `POST /api/voice/clone`:multipart 转发到 `:8000/voice/clone`
- `POST /api/voice/synthesize`:form 转发到 `:8000/voice/synthesize`

---

## 三、架构变化

### 3.1 新增层次(对齐 Prompt `Pipeline → TTSAdapter → 引擎`)

```
WebUI (:5000)                    backend FastAPI (:8000)
  │                                │
  │  /api/voice/clone (代理)        │  POST /voice/clone
  ├───────────────────────────────▶│
  │                                │  _get_voice_identity_service() (懒加载)
  │                                │  ├─ VoiceIdentityService.create_default()
  │                                │  └─ load_adapter_from_config() (mock 默认)
  │                                │
  │                                │  Service.clone_voice(auto_prepare=True)
  │                                ▼
  │                              VoiceClonePipeline (V2.2 升级)
  │                                │  1. validate_audio → AudioInfo
  │                                │  2. analyze_voice → VoiceFeature
  │                                │  3. manager.create_voice → VoiceProfile
  │                                │  4. registry.register_voice
  │                                │  5. cache.exists 检查
  │                                │  6. V2.2 adapter.prepare_voice → VoiceCacheInfo
  │                                ▼
  │                              TTSAdapter (V2.2 抽象接口)
  │                                │
  │                                ├─ Qwen3TTSAdapter
  │                                │   ├─ mock: 返回 fake VoiceCacheInfo
  │                                │   └─ real: load_voice + save_voice_cache_to_disk
  │                                │
  │                                └─ GPTSoVITSAdapter
  │                                    ├─ mock: 同上
  │                                    └─ real: Gradio /change_weights + /inference
  │                                ▼
  │                              backend.tts.adapters / Gradio Client
```

### 3.2 关键约束落实

| 约束(Prompt 第七章) | 落实 |
|---|---|
| V1.1~V2.1 接口兼容 | ✅ V2.1 测试 29 个 + V1.x 兼容测试 20 个全部通过 |
| Pipeline 不直接调用模型 | ✅ 经 TTSAdapter 抽象基类间接 |
| Service 不包含业务逻辑 | ✅ 薄封装委托 Pipeline/Adapter |
| Adapter 可替换 | ✅ 抽象基类 + 注册表 + `build_adapter(name, config)` |
| 所有异常转换为 Result | ✅ prepare/synthesize/clone_voice 全返 Result |
| 类型注解 + docstring + logging + 单元测试 | ✅ 全部新代码满足 |

### 3.3 循环导入解决

`clone/__init__.py` 最初导出 `TTSAdapter` 导致 `adapter ↔ clone` 循环。修复:
- `clone/__init__.py` 移除 TTSAdapter 导出(它属于 adapter 包)
- `clone_pipeline.py` 用 `TYPE_CHECKING` 延迟导入 `TTSAdapter` 类型,运行时不导入
- 顶层 `voice_identity/__init__.py` 分别从 `clone` 和 `adapter` 导入

### 3.4 V2.1 兼容性

| 场景 | V2.1 行为 | V2.2 行为(无 adapter 注入) |
|---|---|---|
| `clone_voice(auto_prepare=True)` 无 adapter | 不存在此参数 | 跳过 adapter.prepare,扩展字段全 None |
| `clone_voice(auto_prepare=False)` | N/A | 完全等价 V2.1 |
| `CloneResult.adapter` 等扩展字段 | N/A | 默认 None,不影响 V2.1 调用方 |

---

## 四、测试结果

### 4.1 V2.2 新增测试(34 个,全部通过)

#### `test_tts_adapter.py`(25 个)

```
Ran 25 tests in 8.237s
OK
```

| 测试类 | 用例数 | 覆盖 |
|---|---|---|
| `TestAdapterRegistry` | 5 | 注册表/构造/未知引擎/非法参数 |
| `TestQwen3MockAdapter` | 7 | prepare 成功/失败 + synthesize 成功/空文本/空 voice_id + can_serve/health_check |
| `TestGPTSoVITSAdapter` | 4 | mock prepare/synthesize + real 缺 metadata + real 无 Gradio |
| `TestConfigLoader` | 5 | 默认配置/项目配置/build_adapter_from_config(qwen3/gpt_sovits/unknown) |
| `TestPipelineWithAdapter` | 4 | auto_prepare 填充扩展字段/False 跳过/无 adapter V2.1 兼容/Adapter 失败保留 Profile |

#### `test_voice_clone_api.py`(9 个)

```
Ran 9 tests in 18.740s
OK
```

> **测试修复(本次验证)**: `test_duplicate_voice_id` 原用固定 voice_id `dup_api_test_001`,因 `DEFAULT_DB_PATH` 不读环境变量 `YHLZ_VOICE_IDENTITY_DB`,跨运行残留导致首次请求即失败。已改为 `dup_api_{uuid.hex[:8]}` 唯一 ID,测试通过。

| 用例 | 覆盖 |
|---|---|
| `test_upload_normal_wav` | 上传正常 wav → 200 + status=ready + adapter=qwen3 |
| `test_synthesize_after_clone` | 克隆后调 /voice/synthesize → audio_path 存在 |
| `test_missing_name` | 缺 name → 422 |
| `test_missing_audio` | 缺 audio → 422 |
| `test_invalid_engine` | engine 不存在 → stage=validate |
| `test_duplicate_voice_id` | 重复 voice_id → stage=create_voice |
| `test_invalid_metadata_json` | metadata JSON 解析失败 → stage=validate |
| `test_empty_audio_bytes` | 空音频字节 → stage=validate |
| `test_short_audio_rejected` | 超短音频(<3s)→ stage=validate |

### 4.2 回归测试(全部通过)

| 测试套件 | 用例数 | 结果 |
|---|---|---|
| V2.1 `test_clone_pipeline.py` | 29 | OK(8.381s) |
| V1.x `test_voice_identity_compat.py` | 20 | OK(0.111s) |

### 4.3 测试覆盖矩阵

| 模块 | 正常路径 | 异常路径 | 边界条件 | 集成 |
|---|---|---|---|---|
| `tts_adapter.py` | ✅ build/registry | ✅ 未知/非法 | — | — |
| `qwen3_adapter.py` | ✅ mock prepare/synth | ✅ 音频不存在 | ✅ 空文本/空 voice_id | — |
| `gpt_sovits_adapter.py` | ✅ mock | ✅ real 缺 metadata | ✅ real 无 Gradio | — |
| `config.py` | ✅ load | ✅ 不存在文件 | ✅ 默认值 | — |
| `clone_pipeline.py` | ✅ auto_prepare | ✅ adapter 失败 | ✅ V2.1 兼容 | ✅ |
| `service.py` | — | — | — | ✅(经 API 测试) |
| `main.py /voice/clone` | ✅ 正常上传 | ✅ 缺参/重复/坏 engine/坏 metadata/空音频/短音频 | — | ✅ |
| `main.py /voice/synthesize` | ✅ 克隆后合成 | — | — | ✅ |

---

## 五、已知风险

### 5.1 高风险

1. **real 模式未端到端验证**:`Qwen3TTSAdapter.real` 与 `GPTSoVITSAdapter.real` 因 GPU/Gradio 依赖未在测试中真实运行,仅 mock 路径被覆盖。**首次部署到生产时需手动验证 real 模式**。
2. **GPT-SoVITS Gradio API id 假设**:`/change_sovits_weights` / `/change_gpt_weights` / `/inference` 的 api_name 基于常见 GPT-SoVITS WebUI 约定,不同版本可能不同。若 Gradio 版本差异大需调整。
3. **临时音频文件清理**:`/voice/clone` 上传的音频保存到 `cache/voice_clone/_uploads/`,当前无自动清理逻辑,长期运行会累积。

### 5.2 中风险

4. **mock synthesize 写正弦波**:合成测试仅生成 440Hz 正弦波,无法验证克隆音色质量。**需后续接 real adapter 做真实合成质量评估**。
5. **质量评分启发式**:`quality_score` 基于 SNR + 时长启发式,非真实克隆质量评估。SNR 缺失时固定 0.7~0.8。
6. **WebUI 上传大小限制**:WebUI 代理层未单独限制大小,依赖 backend 的 `max_size_mb=50`。超大文件可能 OOM。
7. **adapter 切换非线程安全**:`Service.set_adapter` 直接覆盖 `_adapter`,并发请求中切换可能影响进行中的克隆。

### 5.3 低风险

8. **embedding_hash 非真实向量**:mock 模式用 audio MD5,real 模式用 `qwen3_<md5>`/`gptsv_<md5>`,不是真实说话人向量哈希。仅用于去重标识。
9. **voice_clone_config.json 路径硬编码**:`DEFAULT_CONFIG_PATH` 假设项目根目录,移动项目需同步调整。
10. **API 测试 reload main**:`test_voice_clone_api.py` 用 `importlib.reload(_main)` 重新加载 main 模块,会触发 asr/tts 引擎初始化副作用(测试中已通过懒加载规避)。
11. **测试 DB 隔离失效(本次验证发现)**:`database.py` 的 `DEFAULT_DB_PATH` 在模块导入时硬编码为 `backend/data/voice_identity.db`,不读 `YHLZ_VOICE_IDENTITY_DB` 环境变量。`test_voice_clone_api.py` 设置该环境变量实际无效,所有 API 测试共用生产 DB,导致 voice_id 残留。已通过唯一 voice_id 规避,但建议后续让 `DEFAULT_DB_PATH` 支持环境变量或注入式 DB 路径,实现真正隔离。

---

## 六、下一阶段建议

### 6.1 P0(立即,真实验证)

1. **real 模式端到端验证**:
   - 启动 Qwen3-TTS 引擎,`voice_clone_config.json` 改 `qwen3.mode=real`,上传真实人声音频验证 `load_voice` + `save_voice_cache_to_disk` + `synthesize` 全链路
   - 启动 GPT-SoVITS WebUI(:9872),`gpt_sovits.mode=real` + 提供 sovits/gpt 权重路径,验证 Gradio `/inference` 返回
2. **真实合成质量评估**:用 ASR + WER 对 real 模式合成结果回测,验证克隆音色相似度
3. **临时音频清理**:`/voice/clone` 上传文件加 TTL 清理(如 24h 后自动删),或克隆成功后立即删

### 6.2 P1(短期,体验优化)

1. **WebUI 音频预览**:克隆结果区添加 `<audio>` 标签试听 mock 合成结果
2. **WebUI 已克隆声音列表**:增加 `/api/voice/list` 端点 + WebUI 列表展示,支持删除/激活
3. **adapter 热切换 UI**:WebUI 加 engine 下拉框联动切换 adapter(已支持,但 UI 仅传 engine 参数)
4. **metadata 表单生成**:gpt_sovits 选中时自动展开 sovits_model/gpt_model 文件选择器
5. **质量评分可视化**:WebUI 用进度条展示 quality_score

### 6.3 P2(中期,能力扩展)

1. **真实 embedding_hash**:real 模式提取 Qwen3 x-vector 后计算 SHA256,替代 audio MD5
2. **批量克隆 API**:`POST /voice/clone/batch` 支持多音频并行克隆
3. **克隆去重**:上传音频 MD5 已存在时返回已有 voice_id,避免重复克隆
4. **adapter 健康检查 UI**:WebUI 展示各 adapter 的 can_serve/health_check 状态
5. **AEC 接入克隆链**:克隆前自动调 `audio_enhancer.py` 降噪,提升 embedding 质量
6. **克隆质量真实评估**:用 ASR 转写合成音频,与原文计算 WER,低分自动回滚

### 6.4 待关闭的设计决策

| 决策点 | 现状 | 待选项 |
|---|---|---|
| 克隆后自动 select_voice | 否(仅 ready) | 加 `auto_select=True` 参数 |
| mock 模式是否注册到生产 | 是(配置默认 mock) | 生产环境改 real,或加环境变量切换 |
| adapter 单例 vs 每请求新建 | Service 单例 | 每请求新建(隔离)+ 池化 |
| GPT-SoVITS api_name 版本兼容 | 硬编码 | 配置化 + 版本探测 |
| 临时文件清理策略 | 无 | TTL / 克隆后立即删 / 手动清理端点 |

---

## 七、健康度自评

| 维度 | 评分 | 说明 |
|---|---|---|
| 架构合规 | A | 严格分层 Pipeline → TTSAdapter → 引擎,不破坏 V1.1~V2.1 |
| 接口完整 | A+ | 抽象基类 + 注册表 + 2 具体 Adapter + mock/real 双模式 + 配置加载 |
| 向后兼容 | A+ | V2.1 29 测试 + V1.x 20 测试全通过,CloneResult 扩展字段默认 None |
| 测试覆盖 | A | 34 新测试(25 adapter + 9 API)+ 49 回归测试全通过 |
| 文档完整 | A | 模块/类/方法/端点均有 docstring,报告完整 |
| 风险控制 | B+ | real 模式未端到端验证(高风险 1),mock 路径全覆盖 |
| 工程质量 | A | 循环导入已解决,类型注解齐全,异常转 Result |

**整体评级: A-**

> 扣分项:real 模式未真实运行验证(P0 待办),mock 合成质量不足以验证克隆效果。

---

## 八、交付清单

### 8.1 代码交付

- ✅ `backend/voice_identity/adapter/` 完整包(5 模块 + 2 测试文件)
- ✅ `backend/voice_identity/clone/clone_pipeline.py` 升级(auto_prepare + 扩展字段)
- ✅ `backend/voice_identity/service.py` adapter 注入方法
- ✅ `backend/main.py` 2 个 REST 端点
- ✅ `webui_server.py` 2 个代理路由
- ✅ `webui_templates/index.html` Voice Clone 面板
- ✅ `voice_clone_config.json` 配置文件

### 8.2 测试交付

- ✅ `test_tts_adapter.py` 25 测试通过
- ✅ `test_voice_clone_api.py` 9 测试通过
- ✅ V2.1 回归 29 测试通过
- ✅ V1.x 兼容 20 测试通过
- ✅ 总计 **83 个测试全部通过**

### 8.3 闭环验证

```
Audio Upload → validate_audio → analyze_voice → create VoiceProfile
  → Adapter.prepare_voice → VoiceCacheInfo (adapter/cache_path/embedding_hash/quality_score)
  → registry.register → CloneResult
  → POST /voice/synthesize → Adapter.synthesize → wav 文件
```

**端到端闭环已打通(mock 模式),real 模式待生产验证。**

---

*本报告基于 YHLZ_V2.2_开发实现_Prompt.txt 执行生成,V2.2.0 版本已落地,mock 模式全链路通过测试,real 模式待真实 GPU/Gradio 环境验证。*

---

## 九、本次验证运行记录 (2026-08-04)

### 9.1 测试运行结果

| 测试套件 | 用例数 | 耗时 | 结果 |
|---|---|---|---|
| `test_tts_adapter.py` | 25 | 8.237s | OK |
| `test_voice_clone_api.py` | 9 | 18.740s | OK |
| `test_clone_pipeline.py` (V2.1 回归) | 29 | 8.381s | OK |
| `test_voice_identity_compat.py` (V1.x 兼容) | 20 | 0.111s | OK |
| **合计** | **83** | **35.469s** | **全部通过** |

### 9.2 验证中发现并修复的问题

| 问题 | 根因 | 修复 |
|---|---|---|
| `test_duplicate_voice_id` 首次请求即失败 | `database.py:DEFAULT_DB_PATH` 模块导入时硬编码,不读 `YHLZ_VOICE_IDENTITY_DB` 环境变量,测试设置的隔离 DB 路径无效,`dup_api_test_001` 跨运行残留 | `test_voice_clone_api.py:158-160` 改用 `dup_api_{uuid.uuid4().hex[:8]}` 唯一 ID |

### 9.3 待后续处理的技术债

1. **测试 DB 隔离失效**:建议 `database.py` 的 `DEFAULT_DB_PATH` 支持环境变量 `YHLZ_VOICE_IDENTITY_DB`,或 `_get_voice_identity_service()` 支持注入式 DB 路径,实现测试与生产 DB 真正隔离
2. **生产 DB 残留测试数据**:本次验证在 `backend/data/voice_identity.db` 累积了若干测试 voice_id(如 `voice_*`、`dup_api_*`),建议后续清理或加测试 teardown 自动删除
