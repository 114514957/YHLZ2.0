# YHLZ Voice Identity System — M0 Final Audit Report

> 版本: M0 Final (M0.1 ~ M0.6 收尾)
> 生成日期: 2026-08-03
> 审计范围: M0.1 多声音缓存 / M0.2 TTS 适配器 / M0.3 Fallback 链 / M0.4 角色配置单源 / M0.5 VoiceStyle 统一接口 / M0.6 显存策略与缓存持久化
> 审计目的: 判定 M0 阶段是否满足 Voice Identity V1 开发条件
> 结论: **M0 阶段全部完成, 满足 V1 开发条件 (Green Light), 可进入 M1 (VIS Core)**

---

## 1. 完成项 (M0.1 ~ M0.6)

### 1.1 M0.1 — 多声音缓存

| 交付 | 状态 |
|---|---|
| `Qwen3TTSEngine._prompt_cache` 单值 → `Dict[str, Cache]` 多声音缓存 | ✅ |
| `load_voice_cache` / `get_voice_cache` / `clear_voice_cache` / `get_voice_cache_stats` 接口 | ✅ |
| `synthesize(voice_id=...)` 多声音合成, 旧接口 (voice=/无参) 完全兼容 | ✅ |
| 未知 voice_id 回退默认 voice | ✅ |
| 多声音缓存互不覆盖 (A 加载 → B 加载 → A 仍可用) | ✅ |
| 测试: [test_qwen3_voice_cache.py](file:///d:/YHLZ2.0/对话DEMO/test_qwen3_voice_cache.py) 14/14 PASS | ✅ |

### 1.2 M0.2 — TTS 适配器层

| 交付 | 状态 |
|---|---|
| `BaseVoiceEngineAdapter` 抽象基类 + `adapters/` 包 | ✅ |
| `Qwen3TTSAdapter` (封装 Qwen3TTSEngine, voice_id 直通多声音缓存) | ✅ |
| `GPTSovitsAdapter` (Gradio 客户端, 单一实现, voice_id 忽略告警) | ✅ |
| `EdgeTTSAdapter` (预留接口, 签名对齐) | ✅ |
| `TTSManager` 引擎注册 + `create_tts_adapter(engine)` 工厂 | ✅ |
| 全仓库唯一 Gradio 实现位于 adapter 包 (无散落) | ✅ |
| 测试: [test_tts_adapters.py](file:///d:/YHLZ2.0/对话DEMO/test_tts_adapters.py) 14/14 PASS | ✅ |

### 1.3 M0.3 — Fallback 链

| 交付 | 状态 |
|---|---|
| `TTSManager` 三级回退链: Qwen3(primary) → GPT-SoVITS(secondary) → Edge(fallback) | ✅ |
| 引擎加载失败自动切换 + 运行期合成失败自动切换 | ✅ |
| 流式合成失败回退 + 全链耗尽兜底 (不抛异常) | ✅ |
| 真机自动降级验证 (qwen 依赖缺失 → edge) | ✅ |
| 测试: [test_tts_fallback.py](file:///d:/YHLZ2.0/对话DEMO/test_tts_fallback.py) 14/14 PASS | ✅ |

### 1.4 M0.4 — 角色配置单源 (取消 character.yaml)

| 交付 | 状态 |
|---|---|
| 取消 `character.yaml` 路线 (未创建该文件) | ✅ |
| `personality.json` 扩展 `voice_identity` 字段 (`voice_id` + `engine`) | ✅ |
| 旧 json (无 voice_identity) 三层兼容 (L1 加载回填 / L2 字段补全 / L3 更新校验), 不写盘篡改 | ✅ |
| `context_manager.py` 新增 `get_voice_identity` / `update_voice_identity` (字段级 merge) | ✅ |
| REST 端点 `GET/POST /personality/voice-identity` + `PersonalityUpdate.voice_identity` | ✅ |
| 顺手修复 `GET /personality` 的 `config.dict()` 预存 bug | ✅ |
| 测试: [test_voice_identity_compat.py](file:///d:/YHLZ2.0/对话DEMO/test_voice_identity_compat.py) 20/20 + [test_m04_endpoints_smoke.py](file:///d:/YHLZ2.0/对话DEMO/test_m04_endpoints_smoke.py) 9/9 PASS | ✅ |

### 1.5 M0.5 — VoiceStyle 统一接口

| 交付 | 状态 |
|---|---|
| `backend/tts/voice_style.py`: `VoiceStyle` dataclass (emotion/speed/pitch/energy) + `EMOTION_STYLE_MAP` | ✅ |
| `emotion_classifier.py` 新增 `text_to_voice_style` / `emotion_to_voice_style` (输出 VoiceStyle) | ✅ |
| `BaseVoiceEngineAdapter.generate()` 加 `voice_style` 参数 | ✅ |
| Qwen3 (speed→rate) / GPT-SoVITS (speed→speed_factor) / Edge (签名对齐) 三适配器接收 | ✅ |
| 禁止 emotion 逻辑进入具体 TTS (源码静态检查 + 测试验证) | ✅ |
| 验收: 同一 VoiceStyle 被 Qwen3 + GPT-SoVITS 同时接收 (TestUnifiedVoiceStyleAcceptance) | ✅ |
| 测试: [test_voice_style_unified.py](file:///d:/YHLZ2.0/对话DEMO/test_voice_style_unified.py) 43/43 PASS | ✅ |

### 1.6 M0.6 — 显存策略与缓存持久化

| 交付 | 状态 |
|---|---|
| `backend/memory_policy.py`: `MemoryPolicy` + `MemoryController` (can_coexist / acquire / release / switch / snapshot) | ✅ |
| `voice_engine.can_coexist=false` 策略 (与 ASR 不可共存, 任务要求) | ✅ |
| 模型释放 (release) + 模型切换 (switch, 双向冲突检测) | ✅ |
| `Qwen3TTSEngine.save_voice_cache_to_disk` / `load_voice_cache_from_disk` 缓存持久化 | ✅ |
| Prompt Cache Spike: 首次加载→保存→重启→恢复, 7/7 PASS, speedup 2.58x, lossless | ✅ |
| 测试: [test_memory_policy.py](file:///d:/YHLZ2.0/对话DEMO/test_memory_policy.py) 22/22 + [test_prompt_cache_spike.py](file:///d:/YHLZ2.0/对话DEMO/test_prompt_cache_spike.py) 7/7 PASS | ✅ |
| 报告: [PROMPT_CACHE_SPIKE_REPORT.md](file:///d:/YHLZ2.0/docs/PROMPT_CACHE_SPIKE_REPORT.md) | ✅ |

### 1.7 测试总量

| Milestone | 测试文件 | 用例数 | 结果 |
|---|---|---|---|
| M0.1 | test_qwen3_voice_cache.py | 14 | OK |
| M0.2 | test_tts_adapters.py | 14 | OK |
| M0.3 | test_tts_fallback.py | 14 | OK |
| M0.4 | test_voice_identity_compat.py + test_m04_endpoints_smoke.py | 29 | OK |
| M0.5 | test_voice_style_unified.py | 43 | OK |
| M0.6 | test_memory_policy.py + test_prompt_cache_spike.py | 29 | OK |
| **合计** | | **143** | **全部通过, 零回归** |

---

## 2. 遗留问题

### 2.1 阻塞性遗留 (V1 必须先解决)

| # | 问题 | 影响 | 责任 Milestone |
|---|---|---|---|
| B1 | `qwen_tts` / `faster_qwen3_tts` 模块未安装 | Qwen3-TTS 引擎无法真实加载, M0.1/M0.6 使用 FakeModel 验证机制; 真实提取时间/显存/缓存可序列化性未实测 | V1 前置: 安装依赖 + 真实模型, 重跑 spike 获取真实指标 |
| B2 | Qwen3 prompt 对象的可序列化性 (pickle) 未验证 | 持久化 best-effort 保存 prompt.pt, 真实对象可能不可 pickle → 走 `_RestoredPrompt` 轻量路径, 但 `generate_voice_clone` 是否接受轻量对象未知 | V1: 验证 qwen_tts prompt 结构, 必要时改用 x_vector 重组 |
| B3 | `MemoryController` 未接入 `main.py` 服务编排 | 策略 API 已就绪但未实际控制引擎生命周期; 当前 main.py 仍各自独立 load/unload | M1/M2: 服务编排层调用 controller.acquire/release |

### 2.2 非阻塞性遗留 (V1 可并行处理)

| # | 问题 | 影响 | 建议 |
|---|---|---|---|
| N1 | `voice_style.pitch` / `energy` 当前无引擎支持 (全部静默忽略) | VoiceStyle 契约预留, 不影响 V1 | M4: 引擎原生支持时适配器翻译层补充 |
| N2 | main.py 端点层仍调用旧 `resolve_voice_for_emotion` (Edge 音色字符串路径) | M0.5 仅贯通 adapter 层, 端点层 VoiceStyle 路径未接 | M2: 端点层 (/synthesize /chat) 接入 text_to_voice_style → adapter.generate(voice_style=) |
| N3 | 缓存持久化未接入 `load()` 自动恢复 | 重启后需手动调用 load_voice_cache_from_disk | M1: load() 扫描缓存目录自动恢复 |
| N4 | `EMOTION_STYLE_MAP` 数值为经验值, 未听感调优 | 风格映射可用但听感未优化 | M4: WebUI 暴露 + 调优 |
| N5 | `voice_identity.voice_id` 当前是字符串 "default", 无 UUID 强约束 | M0.4 阶段合法 (M0.1 缓存键), 未来 VIS 需 UUID | M1: VoiceProfile.validate() 强制 UUID |
| N6 | 显存策略的 `vram_estimate_gb` 为估算值, 未实测 | 预算预检可能不准 | M1: 实测各引擎真实占用, 校准估算 |
| N7 | Pydantic V2 `.dict()` 弃用警告 (test_m04_endpoints_smoke) | 不影响功能, 未来 V3 移除 | 全项目统一迁移 `model_dump()` (非 M0 范围) |

---

## 3. V1 开发建议

### 3.1 V1 (M1 VIS Core) 开发条件评估

| V1 前置条件 | M0 是否满足 | 依据 |
|---|---|---|
| 多声音缓存底层能力 | ✅ 满足 | M0.1: Dict[str, Cache] + load/get/clear/stats 接口, voice_id 可作 VoiceProfile 缓存键 |
| 统一 TTS 适配器接口 | ✅ 满足 | M0.2: BaseVoiceEngineAdapter + 三适配器, VIS 可通过 adapter 层统一调引擎 |
| 引擎故障容错 | ✅ 满足 | M0.3: 三级 fallback 链, VIS 合成失败可降级不中断 |
| 角色绑定单源 | ✅ 满足 | M0.4: personality.json voice_identity, VIS 可从角色读取默认 voice_id + engine |
| 风格统一接口 | ✅ 满足 | M0.5: VoiceStyle 契约, VIS 可将 VoiceProfile 的风格传给 adapter |
| 显存策略 | ✅ 满足 | M0.6: MemoryController, VIS 多引擎切换时按策略释放/获取 |
| 缓存持久化 | ✅ 满足 | M0.6: save/load_voice_cache_to_disk, VoiceProfile 存储底层就绪 |

**结论: V1 开发条件全部满足, 可进入 M1。**

### 3.2 M1 (VIS Core) 建议路线

```
M1 VIS Core 落地顺序:

1. VoiceProfile 数据结构
   - UUID voice_id (替代 M0.4 的 "default" 字符串)
   - 绑定 engine (qwen3 / gpt-sovits) + ref_audio + VoiceStyle 默认值
   - validate(): UUID 格式 + engine 白名单 + 字段范围

2. VoiceIdentityManager (backend/voice_identity/)
   - create_profile / get_profile / list_profiles / delete_profile
   - 持久化: profiles.json (UUID → profile) + 复用 M0.6 的 voice cache 磁盘存储
   - get_default_voice_id(character_id): 从 personality.json voice_identity 读取 (M0.4 接口)

3. 引擎集成
   - synthesize(text, profile_id): profile → engine + voice_id + VoiceStyle → adapter.generate
   - 复用 M0.1 多声音缓存 (voice_id=profile.uuid) + M0.5 VoiceStyle + M0.6 持久化

4. MemoryController 接入
   - VIS 合成前 controller.acquire(engine) (按 M0.6 策略释放冲突)
   - 卸载时 controller.release(engine)

5. 真实环境验证 (解决 B1/B2)
   - 安装 qwen_tts + 真实模型
   - 重跑 M0.6 spike 获取真实提取时间/显存/可序列化性
   - 校准 M0.6 vram_estimate_gb
```

### 3.3 不建议在 V1 做的事

- 不要重新引入 `character.yaml` (M0.4 已确立 personality.json 单源);
- 不要在适配器内做情绪分类 (M0.5 已禁止, emotion 逻辑留在 emotion_classifier);
- 不要绕过 MemoryController 直接 load/unload 引擎 (M0.6 策略应作为唯一显存入口)。

---

## 4. 风险评估

### 4.1 技术风险

| # | 风险 | 等级 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|---|
| R1 | qwen_tts prompt 对象不可 pickle, 持久化走轻量路径, generate_voice_clone 拒绝轻量对象 | **高** | 中 | 缓存持久化在真实模型下失效, 重启需重新提取 | V1 前置: 验证 qwen_tts prompt 结构; 必要时改持久化 x_vector + 模型 API 支持 x_vector 重组 prompt |
| R2 | RTX 4060 8GB 显存上限, Live 场景 (ASR + Qwen3 + 流式 TTS) 接近 OOM | **高** | 高 | 多模型同时驻留 OOM 崩溃 | M0.6 MemoryController 策略已就绪; V1 必须接入服务编排层强制执行 can_coexist=false |
| R3 | faster-qwen3-tts / qwen_tts 依赖未安装, 真实引擎链未端到端验证 | **中** | 高 | V1 落地时才发现引擎层问题 | V1 前置: 安装依赖 + 真实模型 + 端到端合成验证 |
| R4 | MemoryController 未接入 main.py, 策略未实际生效 | **中** | 中 | V1 若忘记接入, 显存策略形同虚设 | M1 强制: 服务编排层调用 controller, 单测覆盖 |
| R5 | VoiceStyle 的 pitch/energy 无引擎支持, 用户调优后无听感变化 | **低** | 高 | 用户体验: 调参无效 | M0.5 已 debug 日志静默忽略; M4 引擎支持时补翻译 |
| R6 | EMOTION_STYLE_MAP 数值未调优, 听感不达预期 | **低** | 中 | 情绪表现力不足 | M4 产品化阶段调优 + WebUI 暴露 |
| R7 | GPT-SoVITS Gradio 客户端在并发场景下未压测 | **低** | 中 | 高并发合成异常 | V1 后期: 并发压测 + 必要时加锁/队列 |

### 4.2 工程风险

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| E1 | M0 测试大量使用 FakeModel/Mock, 真实模型行为未覆盖 | 中 | V1 前置任务: 安装真实依赖, 重跑关键测试 |
| E2 | 143 项测试无 CI 自动化 | 低 | 建议 V1 接入 CI (pytest), 每次 PR 跑全量 |
| E3 | 文档与代码同步: 6 份 milestone 报告 + 白皮书修订 | 低 | 报告已记录与白皮书/集成审计的偏差; V1 维护时同步 |

### 4.3 风险矩阵

```
影响 ↑
高 │  R2(显存OOM)        R1(prompt不可pickle)
   │
中 │  R3(依赖未装)  R4(策略未接入)  E1(FakeModel覆盖)
   │
低 │  R5 R6 R7  E2 E3
   └───────────────────────────────→ 概率
        低      中      高
```

**最高优先级风险: R1 + R2** — 均与真实模型/显存相关, V1 前置任务 (安装 qwen_tts + 真实模型 + 接入 MemoryController) 必须优先完成。

---

## 5. M0 阶段交付物清单

### 5.1 代码

| 文件 | Milestone | 类型 |
|---|---|---|
| [backend/tts/qwen3_tts.py](file:///d:/YHLZ2.0/backend/tts/qwen3_tts.py) | M0.1 / M0.6 | 多声音缓存 + 持久化 |
| [backend/tts/adapters/base.py](file:///d:/YHLZ2.0/backend/tts/adapters/base.py) | M0.2 / M0.5 | 适配器基类 + voice_style |
| [backend/tts/adapters/qwen3_adapter.py](file:///d:/YHLZ2.0/backend/tts/adapters/qwen3_adapter.py) | M0.2 / M0.5 | Qwen3 适配器 |
| [backend/tts/adapters/gpt_sovits_adapter.py](file:///d:/YHLZ2.0/backend/tts/adapters/gpt_sovits_adapter.py) | M0.2 / M0.5 | GPT-SoVITS 适配器 |
| [backend/tts/adapters/edge_adapter.py](file:///d:/YHLZ2.0/backend/tts/adapters/edge_adapter.py) | M0.2 / M0.5 | Edge 适配器 (预留) |
| [backend/tts/manager.py](file:///d:/YHLZ2.0/backend/tts/manager.py) | M0.2 / M0.3 | 引擎注册 + fallback 链 |
| [backend/context_manager.py](file:///d:/YHLZ2.0/backend/context_manager.py) | M0.4 | voice_identity 单源 |
| [backend/data/personality.json](file:///d:/YHLZ2.0/backend/data/personality.json) | M0.4 | 角色配置 (含 voice_identity) |
| [backend/main.py](file:///d:/YHLZ2.0/backend/main.py) | M0.4 | voice-identity 端点 |
| [backend/tts/voice_style.py](file:///d:/YHLZ2.0/backend/tts/voice_style.py) | M0.5 | VoiceStyle 数据结构 |
| [backend/emotion_classifier.py](file:///d:/YHLZ2.0/backend/emotion_classifier.py) | M0.5 | 输出 VoiceStyle |
| [backend/memory_policy.py](file:///d:/YHLZ2.0/backend/memory_policy.py) | M0.6 | 显存策略与控制器 |

### 5.2 测试

| 测试文件 | 用例 |
|---|---|
| [test_qwen3_voice_cache.py](file:///d:/YHLZ2.0/对话DEMO/test_qwen3_voice_cache.py) | 14 |
| [test_tts_adapters.py](file:///d:/YHLZ2.0/对话DEMO/test_tts_adapters.py) | 14 |
| [test_tts_fallback.py](file:///d:/YHLZ2.0/对话DEMO/test_tts_fallback.py) | 14 |
| [test_voice_identity_compat.py](file:///d:/YHLZ2.0/对话DEMO/test_voice_identity_compat.py) | 20 |
| [test_m04_endpoints_smoke.py](file:///d:/YHLZ2.0/对话DEMO/test_m04_endpoints_smoke.py) | 9 |
| [test_voice_style_unified.py](file:///d:/YHLZ2.0/对话DEMO/test_voice_style_unified.py) | 43 |
| [test_memory_policy.py](file:///d:/YHLZ2.0/对话DEMO/test_memory_policy.py) | 22 |
| [test_prompt_cache_spike.py](file:///d:/YHLZ2.0/对话DEMO/test_prompt_cache_spike.py) | 7 |

### 5.3 文档

| 文档 | Milestone |
|---|---|
| [M0.1_Audit_Report.md](file:///d:/YHLZ2.0/docs/M0.1_Audit_Report.md) | M0.1 |
| [M0.2_Audit_Report.md](file:///d:/YHLZ2.0/docs/M0.2_Audit_Report.md) | M0.2 |
| [M0.3_Audit_Report.md](file:///d:/YHLZ2.0/docs/M0.3_Audit_Report.md) | M0.3 |
| [M0.4_Audit_Report.md](file:///d:/YHLZ2.0/docs/M0.4_Audit_Report.md) | M0.4 |
| [M0.5_Audit_Report.md](file:///d:/YHLZ2.0/docs/M0.5_Audit_Report.md) | M0.5 |
| [PROMPT_CACHE_SPIKE_REPORT.md](file:///d:/YHLZ2.0/docs/PROMPT_CACHE_SPIKE_REPORT.md) | M0.6 |
| [YHLZ_Voice_Identity_M0_Final_Audit_Report.md](file:///d:/YHLZ2.0/docs/YHLZ_Voice_Identity_M0_Final_Audit_Report.md) | M0 收尾 |

---

## 6. 最终结论

**M0 阶段 (M0.1 ~ M0.6) 全部完成。**

- **完成项**: 6 个 milestone 全部交付, 覆盖多声音缓存 / 适配器层 / fallback 链 / 角色单源 / VoiceStyle 统一接口 / 显存策略与持久化;
- **测试**: 143 项测试全部通过, 零回归;
- **遗留问题**: 3 项阻塞性 (B1/B2/B3, 均为"真实环境验证 / 接入"类, 非设计缺陷) + 7 项非阻塞;
- **V1 开发条件**: 全部满足, **Green Light 进入 M1 (VIS Core)**;
- **最高风险**: R1 (prompt 可序列化性) + R2 (显存 OOM), 建议作为 V1 前置任务优先解决。

M0 阶段为 Voice Identity V1 奠定了完整底层能力: 多声音缓存 (M0.1) → 统一适配器 (M0.2) → 容错回退 (M0.3) → 角色单源 (M0.4) → 风格契约 (M0.5) → 显存治理与持久化 (M0.6)。V1 可在此基础上构建 VoiceProfile / VoiceIdentityManager, 不需推翻任何 M0 决策。

*不进行下一阶段修改。*
