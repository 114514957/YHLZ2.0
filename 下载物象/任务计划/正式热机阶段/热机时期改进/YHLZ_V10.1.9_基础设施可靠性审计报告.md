# YHLZ V10.1.9 基础设施可靠性审计报告

> Full Infrastructure Reliability Audit Report
> 版本：V10.1.9（审计目标版本，embodied __version__ 仍 9.5.0，热机不升主版本）
> 测试时间：2026-08-11 21:50 ~ 22:40
> 测试环境：D:\YHLZ2.0（venv Python 3.11 / RTX 4060 Laptop 8GB / Windows 11）
> 审计方式：静态架构扫描（3 路并行） + 隔离端口动态实测（127.0.0.1:8900，不干扰运行中的 WebUI:5000/后端:8000）
> 审计脚本：`热机时期改进\V10.1.9_审计脚本\`（audit_01_startup / audit_02_chain / audit_02b_probe / audit_03_runtime_unit / audit_04_interrupt_soak）

---

## 〇、总体判定

```
最终判断：NOT READY
下一阶段：继续修复基础设施（P0 修复清单见 §十一）
```

**基础设施存在 5 项 Critical 级缺陷**，虽不影响"能跑"，但违反 V10.1.7/8 承诺的
对话运行时可靠性要求（分层打断/队列串行/错误事件/恢复机制在生产路径全部未接线）。

---

## 一、审计结论总表

| 项目 | 判定 | 证据摘要 |
|---|---|---|
| Architecture | **FAIL** | 10+ 模块存在但未接线（死代码），详见 §三 |
| Startup | **PASS** | 冷启动 10/10 成功，平均 11.67s（6.53~18.1s）；端口冲突正确失败 |
| Frontend | **FAIL** | 无重连、错误通道断裂、状态面板只显示 2/11 态、停止后残留流污染界面 |
| Backend | **FAIL** | 3 处运行时硬 bug（set_interrupted/connect/transcribe_file 方法不存在）；/ws 死端点 |
| Conversation Runtime | **FAIL** | 僵尸 turn 实证、队列失效实证、分层打断未接线实证（打断后 964 个 TOKEN 继续流出） |
| Context | **FAIL** | 窗口 8 条功能正常，但裁剪不对称（user 被裁 assistant 残留）+ 无锁 + 双压缩机制竞争 |
| Streaming | **PASS** | 短/长/并发/中断恢复均正常；sequence 单调、turn 隔离正确 |
| Voice | **FAIL** | TTS 全链回退产出近静音 mock（rms=0.0175），"无声"根因在 TTS 侧而非扬声器 |
| Memory | **FAIL** | _turns 无上限、response_text 无限累加、ASR 未加载返回编造文本 |
| Model Pool | **FAIL** | V10.1.3 模型池/Token 优化/显存仲裁全部未接线，主模型失败不会自动切换 |
| Monitoring | **FAIL** | /health 恒 healthy、/metrics 只覆盖 voice 克隆、日志无轮转、turn 无 latency 落盘 |
| Recovery | **FAIL** | Streaming 异常无 ERROR 事件、turn 卡死无看门狗、/interrupt 不恢复状态 |
| 24H Stability | **PENDING** | 见 §十；短时浸泡已实测日志 ~4.5KB/s 无轮转增长 |

---

## 二、启动可靠性测试（§五 对应）

```
Success: 10 / 10
Failed:  0
端口冲突: OK（实例 B 快速退出 code=1，检测延迟 13.3s ≈ 模块导入耗时）
平均启动耗时: 11.67s（min 6.53s / max 18.1s）
依赖缺失: 无启动崩溃；TTS 引擎链缺失（见 Voice 节）
```

| Run | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| 秒 | 18.1 | 15.59 | 15.6 | 11.07 | 15.08 | 8.05 | 7.56 | 8.03 | 6.53 | 11.1 |

**注意**：启动耗时波动大（6.5~18s），首跑含 edge-tts 预热 10s 超时；端口冲突检测
延迟 = 启动耗时本身（先 import 再 bind），属可接受但有优化空间。

---

## 三、架构完整性检查（§四 对应）

### 3.1 分层存在性

```
Frontend (index.html/webui_server.py/frontend壳)    ✅ 存在
API Layer (backend/main.py FastAPI)                ✅ 存在
Runtime (conversation_controller 等)               ✅ 存在
Conversation (context_manager/input_aggregator)    ⚠️ 部分未接线
Model (llm_engine)                                 ⚠️ 无超时无重试
Memory (context_manager/记忆层)                    ⚠️ 双历史并存
Voice (tts/asr/vad/audio_buffer)                   ⚠️ 2 个硬 bug
Agent (embodied 22 子包)                           ✅ 存在 (独立子系统)
Storage (db/json/log)                              ⚠️ 日志无轮转
Monitoring (/health /metrics)                      ❌ 健康检查恒真
```

### 3.2 死代码 / 未接线清单（Critical 级架构缺陷）

| 模块 | 状态 | 影响 |
|---|---|---|
| `input_aggregator.py`（V10.1.8 输入治理） | 仅测试引用 | 分类/合并/优先级在生产**完全不生效**，1000 条直播输入全量进 /chat |
| `model_pool/`（V10.1.3 模型池） | 仅测试引用 | 主模型失败**不会**自动切换备用模型 |
| `token_opt/`（V10.1.3） | 仅测试引用 | Token 压缩/预算不生效 |
| `memory_policy.py`（显存仲裁） | 仅测试引用 | 8GB 显存 OOM 依赖"碰巧不同时加载" |
| `echo_cancellation.py`（AEC） | 全仓库零 import | 回声抑制实际靠"自播窗口丢弃"方案 |
| `asr_engine_qwen.py` | 零 import | 误导性死文件 |
| `conversation_manager.handle_ws` | 方法不存在 | /ws 端点每次必 AttributeError（已在日志实证） |

---

## 四、核心链路逐节点测试（§六 对应）

隔离实例实测（真实 LLM qwen-turbo 在线、TTS 全链回退、ASR 未加载）：

| 节点 | 结果 | 耗时 | 详情 |
|---|---|---|---|
| 服务启动 → /health | PASS | - | status=healthy（llm/tts/vad true，asr false） |
| /chat 短回复（SSE） | PASS | 1.91s | START→TOKEN×N→COMPLETE，sequence 单调，turn_id 唯一 |
| /chat 长回复（SSE） | PASS | 3.35s | 626 个 TOKEN，约 624 字，COMPLETE 含 full_content |
| /chat 并发 ×3 | PASS* | 5.55s | 3/3 全部 COMPLETE；但 3 个 turn **同时流式输出**（队列失效，见 R8） |
| /transcribe（静音） | FAIL* | 0.02s | 返回**编造文本**（ASR 未加载时 mock 幻觉，见 R17） |
| /synthesize（默认引擎） | FAIL* | 0.04s | 返回 24000 样本**近静音音频**（rms≈0），全链回退 mock |
| /synthesize（edge 引擎） | FAIL* | 0.05s | 同样近静音（rms=0.0175），edge 报 `Invalid voice 'Vivian'` |
| /interrupt | PASS | 0.002s | 仅清音频缓冲；LLM 流不取消（见 R11） |
| /clear-history | PASS | 0.02s | 正常 |
| /vad/interrupt（连续2次） | FAIL | 0.03s | 第 2 次调用 HTTP 500：`AudioBufferManager has no attribute 'set_interrupted'` |
| /modules/start llm | FAIL | 0.002s | `LLMEngine has no attribute 'connect'` → success=false |
| /ws（WebSocket） | FAIL | - | 连接即关闭：`ConversationManager has no attribute 'handle_ws'` |
| SSE 中断恢复 | PASS | 1.69s | 客户端断开后新 /chat 正常；但旧 turn 永久卡 STREAMING（见 R9） |

\* = 链路通但结果错误（静默失败，用户无感知）

---

## 五、Conversation Runtime 专项（§七 对应）

Turn 状态机（11 态）定义完整、RLock 到位、迁移表可解释。**但生产路径严重脱节**：

- `mark_tts_playing` / `interrupt_turn` / `recover_turn` / `error_turn` **在生产代码零调用**
  （仅测试覆盖）
- 生产实际发射事件仅 START / TOKEN / COMPLETE；ERROR / INTERRUPTED / FLUSH /
  HEARTBEAT 四种事件类型定义但**永不发射**（前端对应分支为死代码）

### 动态实证

**R9（Critical）僵尸 turn**：SSE 客户端中途断开 → 日志显示 turn 卡在 STREAMING，
无 COMPLETE/ERROR/INTERRUPTED，`_active_turn` 永不释放，`_turns` 永久残留。

**R8（Critical）队列失效**：并发 3 请求全部 `QUEUED` 却同时流式输出（日志实证
`非法迁移 QUEUED → STREAMING` 仅警告仍执行）；turn COMPLETED 后又被队列
`_release_active` 重复弹出置 READY（二次非法迁移）。

**R1（High）非法迁移仍执行**：`_transition` 对非法迁移仅 warning 后照常赋值
（单元测试实证 COMPLETED→STREAMING 被实际执行）。

**R2（High）孤儿 turn**：队满时 turn 已写入 `_turns`（QUEUED）后抛异常，
且外层 `except` 中 `turn_id` 未定义触发 NameError 被 `pass` 吞掉 → error_turn
实际未执行（单元测试实证）。

**R3（High）内存无上限**：`_turns` 字典无淘汰（500 turn 全部留存，单元测试实证）；
`response_text` 逐 TOKEN 无限累加。

**R6（Medium）TTFT 失真**：`latency_summary` 的 first_token 字段**从未被写入**，
TTFT 实际 = llm_start - turn_start（单元测试实证）。

---

## 六、Context 系统检查（§八 对应）

| 项 | 结果 |
|---|---|
| 20 轮连续对话 | 窗口稳定 8 条（12 轮后 history=8，实证） |
| 压缩触发 | 溢出 4 条触发 `_compress_to_working_summary`，摘要含"目标"等保留字段（实证） |
| 遗忘/串话 | **窗口裁剪不对称**：12 条消息裁到 8 条时出现"user 被裁、对应 assistant 残留"（实证，末条 role=assistant） |
| 并发安全 | **无任何锁**（RLock 缺失）；`asyncio.create_task` 不持有引用（GC 风险） |
| 双压缩竞争 | 8 条窗口规则压缩 与 LLM 全量摘要（token≥7000 清空 history）**互相竞争可覆盖历史** |

---

## 七、Streaming 可靠性（§九 对应）

| 场景 | 结果 |
|---|---|
| 短回复（首 token/首句/完成） | PASS（1.91s 完整闭环） |
| 长回复（626 token 流式） | PASS（3.35s，sequence 单调，COMPLETE 完整） |
| 并发流式 | 功能 PASS，但队列未串行（R8） |
| 网络断开（客户端中途断开） | 服务不卡死，新请求可恢复；旧 turn 僵尸化（R9） |
| 模型失败 | llm_engine 内部降级为固定离线文案（被当正常回复写入历史，用户无感知，Medium） |
| 前端刷新 | 无重连机制，需用户手动重发（Frontend FAIL） |

---

## 八、Interrupt 边界测试（§十 对应）

**R11（Critical）分层打断全部未接线**，动态实证：

```
POST /interrupt（流式中）→ HTTP 200，0.015s
→ 之后 LLM 继续流出 964 个 TOKEN（17.2 万字符）并 COMPLETE
```

- `llm` 层：LLM 流无取消机制，流到结束（实证）
- `tts` 层：tts_producer 无中断检查，打断后向已清空缓冲**继续追加音频**
- `queue` 层：turn 队列完全不清理
- `interrupt_time` / `stopped_layer` / `recovery_time` 生产环境**永不记录**
- 前端等 INTERRUPTED 事件永远等不到（死代码分支）
- VAD 自动打断同时存在硬 bug（`set_interrupted` 不存在 → HTTP 500）

---

## 九、Input Aggregator / 模型池 / 日志 检查（§十一~十四 对应）

### 9.1 Input Aggregator（1000 条模拟，单元级）

模块本身功能正确（实证）：200 重要/300 普通/300 闲聊/200 噪声/20 重复 →
噪声丢弃 ✓ 重复合并 ✓ 优先级（important 先出）✓ 队列上限 30 ✓ 队满挤压 ✓。
**但模块未接入任何生产路径 → 全部治理不生效**（Critical）。

### 9.2 模型池 / Memory / Token 优化

- 模型池 Router（V10.1.3）：66 个单测全过、RLock 齐全、切换/交接逻辑完整，
  但 `selector.should_switch` 的 latency 条件永不满足（latency 不回写 registry），
  且**整体未接线** → 主模型失败无自动切换（Critical）
- MemoryController（显存仲裁）：无锁，未接线 → OOM 无仲裁

### 9.3 日志与可观测性

- Turn 日志有 turn_id/conversation_id/state（backend.log），**缺 latency/model/error 字段**
- **无 turn 日志 JSONL 落盘**、无 HTTP 查询端点、无逐 turn latency
- `/health` 恒 healthy（ASR 未加载也 healthy，动态实证）——健康检查盲区
- `/metrics` 仅 voice 克隆指标，无对话/LLM/进程指标
- backend.log 单文件无轮转：浸泡实测 **~4.5KB/s**（30 轮对话 108KB/23.6s）
  → 24h 连续对话约 **300~400MB 单文件增长**
- `backend_stdout.log` 管道块缓冲 0 字节（后端崩溃日志可能永久丢失）
- 前端对话状态面板仅 STREAMING/COMPLETED 两态可达（11 态只显示 2 态）

---

## 十、24H 稳定性（§十五 对应）

**本会话无法完成 24h 实测，标记 PENDING（热机监控期执行）**。已交付：
- `audit_04_interrupt_soak.py`（含 30 轮浸泡 + RSS/日志增长采样框架，可直接
  扩展为 `--hours 24` 长跑模式）
- 短时浸泡结论：功能稳定（30 轮 0 错误），但日志无轮转增长已实测
- 静态确认的内存泄漏点（修复前长跑必然增长）：`_turns` 无上限、
  `response_text` 无限累加、`audio_buffer` 无界队列

---

## 十一、P0 修复清单（下一阶段）

| # | 级别 | 问题 | 修复方向 |
|---|---|---|---|
| 1 | Critical | /chat 生成器无 try/finally → 僵尸 turn 卡 STREAMING | generate() 加 finally → error_turn + ERROR 事件 + 释放 turn |
| 2 | Critical | claim_ready_turn() 返回值被忽略 → 队列失效 | 尊重 claim 结果：未轮到则等待；修复 _release_active 重复弹出 |
| 3 | Critical | 分层打断未接线 | /interrupt 接线 interrupt_turn + INTERRUPTED 事件 + LLM 取消标志 + tts_producer 中断检查 |
| 4 | Critical | LLM 流无超时无重试 | generate_stream 加 asyncio.wait_for 超时（配置化）+ 错误帧 |
| 5 | Critical | TTS 全链静音 mock（faster_qwen3_tts/qwen_tts 模块缺失，edge 声线 'Vivian' 无效） | 安装/修复引擎依赖或修正默认声线；合成失败发错误帧而非静音 |
| 6 | High | 3 处方法名硬 bug | `set_interrupted`→`interrupt()`；`llm_engine.connect/disconnect` 实现；`transcribe_file` 实现；/ws 移除或实现 handle_ws |
| 7 | High | InputAggregator 未集成 | /chat 入口接入 process() |
| 8 | High | ContextManager 无锁 + 双压缩竞争 | RLock + 单一压缩机制 + create_task 持引用 |
| 9 | High | _turns/response_text/audio_buffer 无上限 | 上限 + 淘汰（配置化） |
| 10 | High | 日志/监控 | backend.log 轮转、turn JSONL、/health 真检查、metrics 扩展 |
| 11 | Medium | ASR 未加载返回编造文本 | 返回空串+错误帧，禁 mock 幻觉 |
| 12 | Medium | 前端断线重连/状态面板/残留流 | EventSource/重试、全态显示、AbortController |

---

## 十二、测试结果（全量回归）

```
embodied:        8618   OK (skipped=2)
vision:           136   OK
action:           151   OK
agent:            131   OK
personality:      137   OK
voice_identity:   181   OK
frontend:         118   OK
TOTAL:           9472   Failed=0 ✅（基线保持）
```

## 十三、修改内容记录（可追踪）

| 文件 | 操作 | 说明 |
|---|---|---|
| `热机时期改进\V10.1.9_审计脚本\`（5 个脚本 + runs/ 证据） | 新增 | 审计证据落盘（startup/chain/probe/runtime_unit/interrupt_soak + JSON 汇总） |
| 业务代码 / 配置 / 数据 | 未修改 | 本次为纯审计，未触碰冻结接口 |

## 十四、架构影响

- 审计发现的修复均不触碰冻结接口：修复集中在 main.py 接线层 + llm/audio 两个
  无单测模块（asr/vad/audio/llm 四模块零单测是硬 bug 无人拦截的原因，建议补测）
- 后端 8000 / WebUI 5000 运行实例全程未受影响（隔离端口实测）

---

**YHLZ · 元 · 亨 · 利 · 贞**
