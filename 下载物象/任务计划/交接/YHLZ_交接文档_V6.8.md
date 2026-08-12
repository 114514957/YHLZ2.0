# YHLZ 会话交接文档（V6.8）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-09

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V7.0 Embodied AI Partner（具身伙伴层）**

- 任务文件：`下载物象\任务计划\四阶段\YHLZ_V7.0_下一步开发Prompt.txt`
- 方向：虚拟形象/动作表达 + HIL 接真实模型 + HIL 与视觉/语音任务联动
- 专项目标 ≥5991（当前 5591 + 400），Failed=0
- 备注：**V6.7 阶段未实施**（用户直接下达 V6.8），v6.8.txt 规格中
  "V6.7 已完成"描述与仓库实际不符，勿引用

---

## 1. V6.8 已实现（本会话）

### 1.1 混合智能层 `companion/hybrid/`（新子包 16 文件）

| 目录 | 文件 | 内容 |
|---|---|---|
| router/ | `task_classifier.py` | TaskClassifier.classify(ctx) → {type, complexity, privacy_level, latency_requirement, creativity_requirement, type_reason}；11 任务类型 + TYPE_KEYWORDS 中文关键词推断；TASK_PROFILES 默认特征 |
| router/ | `capability_matcher.py` | Capability + CapabilityMatcher：register/unregister/get/match(task_type)；register_defaults() 注册 8 能力（local 5 + cloud 3）；TASK_CAPABILITIES 任务→能力映射 |
| router/ | `routing_engine.py` | RoutingEngine.route(ctx) → {route, reason, confidence, checks}；规则序：隐私铁律→身份任务→实时→能力缺失→高复杂度/创造(成本约束)→混合→默认本地 |
| local/ | `local_capability.py` | LocalCapability(name, handler) + LocalCapabilityRegistry；default_local_handlers() 纯规则 Mock 5 能力 |
| local/ | `local_provider.py` | LocalProvider.execute(capability, request)；异常→结构化错误帧（不外抛） |
| cloud/ | `api_gateway.py` | ApiGateway + ModelEndpoint(model, family, cost_per_1k_tokens, handler)；register_defaults() 5 模型；request() 全记录（record_id/time/model/tokens/cost/latency）；handler 可注入真实调用 |
| cloud/ | `cloud_provider.py` | CloudProvider.execute(capability)；CLOUD_CAPABILITY_MODELS 映射；结果标记 temporary=True（默认临时） |
| policy/ | `privacy_policy.py` | PrivacyPolicy.evaluate(ctx) → cloud_allowed；身份任务强制 high 禁云端 |
| policy/ | `cost_policy.py` | CostPolicy.evaluate(value_score, model) → allowed（低价值<0.3 + 高成本>0.01 → 拦截）；record(model, tokens, cost, value_score)；optimization() 成本优化建议；_model_cost 映射（deep/creative/analysis→high，local→free） |
| policy/ | `routing_policy.py` | RoutingPolicy.evaluate(ctx, desired_route) → final_route（隐私否决/成本否决/实时→HYBRID） |
| validation/ | `result_validator.py` | ResultValidator.validate(result) 4 检查：structure/identity（中英文修改信号）/safety/temporary；云端未标记临时→拒 |
| audit/ | `inference_audit.py` | InferenceAudit.record/report/replay/stats（全调用可查询/回放） |
| — | `__init__.py` | HybridIntelligenceLayer 门面：route(ctx)（含策略修正+云端停用降级）/ execute(ctx, request)（路由→执行→验证→审计）/ gateway_request(model, payload, value_score)（成本前置拦截）/ stats / audit_report / audit_replay / cost_optimization / clear |

### 1.2 集成

- Service API 5 个：`companion_hybrid_route` / `companion_hybrid_execute` /
  `companion_hybrid_gateway_request` / `companion_hybrid_stats` /
  `companion_hybrid_audit`
- service property：`companion_hybrid`（懒加载，initialize_defaults 已调用）
- config 6 项新（companion_hybrid_enabled / cloud_enabled /
  high_cost_threshold=0.01 / low_value_threshold=0.3 / max_tokens /
  audit_max=2000）
- main_agent：`_hybrid` + 5 方法；**HIL 不触碰成长审批**（execute 不调
  growth_apply，不写 experience——云端结果默认临时）
- companion/__init__ 导出 16 符号（无同名冲突：HybridIntelligenceLayer/
  TaskClassifier/RoutingEngine/... 全唯一）

### 1.3 关键语义（勿破坏）

- **隐私铁律**：identity_query/permission_check/memory_retrieval 永远 LOCAL；
  privacy_level=high 禁云端（PrivacyPolicy）
- **成本铁律**：低价值（<low_value_threshold）禁高成本模型
  （>high_cost_threshold）；gateway_request 前置拦截
- **云端结果铁律**：temporary=True 默认；验证器 4 检查不通过 → blocked
  （不应用）；禁止改身份/人格/权限/记忆
- **云端停用降级**：HIL.route 检查 `_cloud._enabled`，停用 → LOCAL
- **路由判定顺序**（RoutingEngine）：隐私→身份→实时→能力缺失→
  云端分支（complexity≥0.75 或 creativity≥0.7，成本通过才 CLOUD）→
  混合（complexity≥0.45 且 creativity≥0.35）→ 默认 LOCAL

---

## 2. 测试现状（V6.8 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **5591**（V6.8 新增 407, Skipped=2） | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **6327** | **0** |

V6.8 新增测试 8 个文件：
`test_v680_router(58)` / `test_v680_provider(42)` / `test_v680_policy(42)` /
`test_v680_security(36)` / `test_v680_integration(45)` /
`test_v680_extra(80,生成式)` / `test_v680_extra2(59,生成式)` /
`test_v680_extra3(45,生成式)`。

---

## 3. 关键事实清单（供新会话直接使用）

### 3.1 生成式测试纪律（延续）

setattr 生成时 test.__name__ 在工厂函数体内赋值（_i 为当前循环值）；
闭包默认参数绑定当前循环值；records/lambda 注意 `[...] * n` 展开。

### 3.2 HIL 默认状态

- `HybridIntelligenceLayer.initialize_defaults()` 必须调用（注册 matcher 8
  能力 + local 5 + gateway 5 模型）；service/main_agent 构造时已调用
- 所有外部能力 Mock（ModelEndpoint.handler / LocalCapability.handler
  可注入真实实现）
- execute 每次调用都审计（audit_id 回传）；stats() 聚合 10 个子模块统计

### 3.3 版本号

6.8.0 已写入：`embodied/__init__.py` / `service.py`（report 4 处）/
`governance/__init__.py` / `main_agent.py` / `creative_engine` /
`continuity_engine`（schema_version + stats）/ `storage/snapshot/restore/
identity_snapshot` / 全部测试断言（96 处批量更新）。

### 3.4 临时脚本目录

`C:\Users\lenovo\AppData\Local\Temp\opencode\`：
`bump_v660_version.py`（版本批量脚本，V6.8 用一次性 python -c 执行）。

---

## 4. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| V6.7 未实施（趋势双窗口/偏好学习） | 规格描述与仓库不符 | 已按 V6.8 规格直接实现 HIL；V6.7 内容并入 V7 规划 |
| 云端真实调用未接入 | 全部 Mock | V7 接真实 API（config 已有 api_provider/key） |
| 身份检测关键词匹配 | 语义弱 | V7 增强 |
| 路由静态规则 | 无任务历史学习 | V7 路由偏好 |
| Tesseract 未安装 | skipIf 保护 | 安装后自动启用 |

---

## 5. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 测试文件 CRLF
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：权限默认拒绝 / 记忆必须批准 / 成长必须审批 / 身份守护 /
  反思≠意识 / 云端≠核心（结果必须验证）
- property 与 API 方法禁止同名；新 API 独立命名避冲突

---

## 6. 下一阶段

V7.0 Embodied AI Partner：具身伙伴层（虚拟形象/动作 + HIL 接真实模型）。
任务文件：`下载物象\任务计划\四阶段\YHLZ_V7.0_下一步开发Prompt.txt`。
验收报告：`下载物象\任务计划\四阶段\YHLZ_V6.8_验收报告.md`。

**YHLZ · 元 · 亨 · 利 · 贞**
