# YHLZ 会话交接文档（V9.0）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`backend/embodied/`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-09

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V10.0 Embodied Autonomy（具身自主）**

- 任务文件：`下载物象\任务计划\四阶段\YHLZ_V10.0_下一步开发Prompt.txt`
- 方向：研究结果持久化 + 探索-成长联动 + 深度语义化 + 主动探索节律
- 专项目标 ≥7594（当前 7194 + 400），Failed=0

---

## 1. V9.0 已实现（本会话）

### 1.1 自主研究探索引擎 `companion/research_engine/`（新子包 9 文件）

| 文件 | 内容 |
|---|---|
| `observation.py` | ObservationLayer：observe(4 类型)/from_knowledge_gaps/observations/stats |
| `question_discovery.py` | QuestionDiscoveryEngine.discover()：观察→问题（IMPORTANCE_WEIGHTS: user_need 0.9 > long_term_goal 0.8 > unresolved 0.7 > knowledge_gap 0.6），按 importance 降序，max_questions 截断 |
| `research_planner.py` | ResearchPlanner.plan(question, importance)：4 步拆解（获取/假设/分析/验证）+ 资源规划（≥0.8 全 4 资源）+ verification_path + 成本（≥0.8 high/≥0.5 medium/低 low） |
| `knowledge_acquisition.py` | KnowledgeAcquisition.acquire(query, source)：SOURCE_RELIABILITY（local 0.9/user_authorized 0.85/cloud 0.7/tool 0.75/unknown 0.0）；provider 注入；来源未知 → unreliable |
| `hypothesis_loop.py` | HypothesisLoop.run()：{loop_id, question, hypothesis, analysis, result, validation, knowledge_update}；失败也记录（有效探索数据）；仅验证通过才 knowledge_update |
| `reality_validation.py` | RealityValidation.validate(content, source, reliability)：5 级（fact=可靠+证据/evidence=可靠/inference=推理/hypothesis=有内容/speculation=无）；speculation ok=False（禁止入事实记忆） |
| `research_memory.py` | ResearchMemory.save()：Memory Filter（未验证/推测/宪法未过 → 拒绝）；保存来源/结论/level/验证状态/uncertainty |
| `research_audit.py` | ResearchAudit.record()：{time, question, source, method, result, validation}；report（by_source/by_method）+ replay |
| `__init__.py` | ResearchEngine 门面：explore（防失控 → 宪法 → 问题 → 计划 → 获取 → 现实验证 → 假设循环 → 记忆 → 审计）；RUNAWAY_SIGNALS（自定义终极目标/统治世界/无限扩展任务/脱离用户价值/自我强化/永久循环/override user values/infinite loop）；无问题 → error_frame |

### 1.2 集成

- Service API 5 个：`companion_research_explore(goal, user_value)` /
  `_observe(obs_type, content, source)` / `_questions()` / `_audit(limit)` /
  `_stats()`
- service property：`companion_research`（懒加载，constitution 注入）
- config 6 项新（companion_research_enabled / max_loops=3 / audit_max=2000 /
  constitution_link / creative_link / hybrid_link）
- main_agent：`_research` + 5 方法；**Creative 联动**：research_explore
  结果问题 → meta_creative.load_experience（creative_link 段）；**HIL
  联动**：附加 hybrid 段（research 类型路由）
- companion/__init__ 导出 22 符号（无同名冲突）

### 1.3 关键语义（勿破坏）

- **防失控铁律**：RUNAWAY_SIGNALS 命中 → error_frame（不探索）；
  空目标 → "目标为空 (禁止无目标探索)"
- **探索必须有观察**：无问题 → "无可探索问题 (需先观察)"
- **等级铁律**：speculation 永不入记忆；未验证/宪法未过 → 拒绝
- **失败有效**：假设循环失败结果也记录（有效探索数据）
- **成本按重要性**：低价值低成本（0.3 → low）
- **观察 None 容错**：content=str(content or "")（"None" 不写入）
- **max_loops 截断**：每轮探索最多处理 max_loops 个问题（默认 3）

---

## 2. 测试现状（V9.0 验收）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
```

| 子系统 | Total | Failed |
|---|---|---|
| embodied | **7194**（V9.0 新增 400, Skipped=2） | 0 |
| vision | 136 | 0 |
| action | 151 | 0 |
| agent | 131 | 0 |
| personality | 137 | 0 |
| voice_identity | 181 | 0 |
| **合计** | **7930** | **0** |

V9.0 新增测试 17 个文件（400 用例）：test_v900_observation_question(26) /
planner_acquisition(23) / loop_reality(23) / memory_audit(17) /
integration(46) / extra(22) / extra2(18) / extra3(20) / extra4(20) /
extra5(18) / extra6(12) / extra7(15) / extra8(17) / extra9(15) /
extra10(13) / extra11(12) / extra12(17) / extra13(7) / extra14(12) /
extra15(10) / extra16(12) / extra17(27)。
规格五测试已覆盖：Question Quality Test / Reality Test / Memory Safety
Test / Goal Boundary Test / Audit Test。

---

## 3. 关键事实清单（供新会话直接使用）

### 3.1 版本号

9.0.0 已写入全部模块与测试断言（120 处批量）。
**注意 test_snapshot/test_v60 版本语义**：minor 测试 "9.1.0"，major 拒绝
"10.0.0"，篡改测试 replace 9.0.0→10.0.0 —— V10 批量替换 "9.0.0"→"10.0.0"
后需检查这些字面量（major 拒绝测试会变成当前版本 → 需改 "11.0.0"！）

### 3.2 生成式测试纪律（延续）

setattr 生成时 test.__name__ 在工厂函数体内赋值；闭包默认参数绑定当前
循环值；any(...) 生成器需括号包裹。

### 3.3 V9.0 边界（勿越界）

- 探索必须有目标（防失控 + 空目标拒绝）
- 推测永不入事实记忆（speculation 铁律）
- 未知来源不入长期记忆（reliability 0.0）
- 探索不自动应用（只产生记忆与问题）
- 失败结果有效（假设循环记录）

### 3.4 联动开关

- companion_research_constitution_link（默认 true）
- companion_research_creative_link（默认 true）：探索 → 创造知识图
- companion_research_hybrid_link（默认 true）

---

## 4. 已知遗留 / 风险

| 问题 | 影响 | 处置 |
|---|---|---|
| 问题发现规则级 | importance 加权 | V10 语义化 |
| 知识获取默认规则 | Mock 可注入 | V10 真实来源 |
| 探索无持久化 | 内存驻留 | V10 research_state 域 |
| 探索-成长无联动 | 结论未进成长 | V10 联动 |
| Tesseract 未安装 | skipIf 保护 | 安装后自动启用 |

---

## 5. 工程规范（速查）

- **先读后写 / 接口先行 / 配置驱动 / 向后兼容**
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 测试文件 CRLF
- 禁止：硬编码 / 跨层调用 / 临时方案 / 静默吞异常 / 破坏既有 API
- 分层：Interface → Service → Manager → Storage/Adapter
- 安全：权限默认拒绝 / 记忆必须批准 / 成长必须审批 / 身份守护 /
  反思≠意识 / 云端≠核心 / 表达≠主体性 / 创造≠随机 / 探索≠无限
- property 与 API 方法禁止同名；新 API 独立命名避冲突

---

## 6. 下一阶段

V10.0 Embodied Autonomy：研究持久化 + 探索-成长联动 + 深度语义化 +
主动探索节律。
任务文件：`下载物象\任务计划\四阶段\YHLZ_V10.0_下一步开发Prompt.txt`。
验收报告：`下载物象\任务计划\四阶段\YHLZ_V9.0_验收报告.md`。

**YHLZ · 元 · 亨 · 利 · 贞**
