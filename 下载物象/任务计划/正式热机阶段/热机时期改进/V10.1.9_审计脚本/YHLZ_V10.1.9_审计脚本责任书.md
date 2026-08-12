# YHLZ V10.1.9 审计脚本 文件责任书

> 版本：V10.1.9 基础设施可靠性审计
> 生成日期：2026-08-11
> 依据：`YHLZ_V10.1.9_Full_Infrastructure_Reliability_Audit_Prompt.txt`
> 报告：`YHLZ_V10.1.9_基础设施可靠性审计报告.md`（同目录上级：`热机时期改进\`）

---

## 一、文档目的

本责任书定义 V10.1.9 基础设施审计脚本集的**文件职责、责任分工、运行方式、
修改纪律与证据管理**，保证审计可复现、可追踪、可问责（热机变更流程：
来源/原因/修改内容/验证结果 全程记录）。

## 二、审计脚本总览

| 文件 | 审计域（对应 Prompt 章节） | 负责人角色 | 证据输出 |
|---|---|---|---|
| `audit_01_startup.py` | §五 启动可靠性（冷启动×10/端口冲突/依赖缺失） | 启动测试工程师 | `runs/startup_*.log` `runs/startup_summary.json` |
| `audit_02_chain.py` | §六 核心链路（health/chat短/chat长/并发/transcribe/synthesize/interrupt/clear-history）+ §十四 错误路径探针 | 链路测试工程师 | `runs/chain_server*.log` `runs/chain_summary.json` |
| `audit_02b_probe.py` | §十 打断边界（VAD 打断 bug）/ §十三 语音层（TTS 引擎链）/ §十四 恢复（SSE 中断） | 语音测试工程师 | `runs/probe_server*.log` `runs/probe_summary.json` |
| `audit_03_runtime_unit.py` | §七 对话运行时（R1/R2/R3/R6 实证）/ §十一 输入治理（1000 条）/ §八 上下文（20 轮窗口） | 运行时测试工程师 | 控制台输出（unittest 报告） |
| `audit_04_interrupt_soak.py` | §十 打断边界（LLM 层实证）/ §十五 资源稳定（30 轮浸泡 + 内存/日志采样） | 稳定性测试工程师 | `runs/soak_server*.log` `runs/interrupt_soak_summary.json` |

## 三、责任分工表

| 角色 | 职责 | 负责文件 |
|---|---|---|
| 审计总负责（高级工程师） | 架构静态扫描（前端/运行时/语音三层）、风险判定、最终报告、24H 方案审批 | 报告 + 全部脚本的验收 |
| 启动测试工程师 | 冷启动 10 次、端口冲突、启动耗时统计、依赖缺失检查 | `audit_01_startup.py` |
| 链路测试工程师 | 核心链路逐节点（输入→WebUI→API→Runtime→LLM→SSE→TTS）、SSE 协议校验、错误路径探针 | `audit_02_chain.py` |
| 语音测试工程师 | VAD 打断 bug 复现、TTS 引擎链检查（qwen3/gpt-sovits/edge）、SSE 中断恢复 | `audit_02b_probe.py` |
| 运行时测试工程师 | Turn 状态机/队列/打断分层/内存增长的单元级实证、输入治理 1000 条、上下文 20 轮 | `audit_03_runtime_unit.py` |
| 稳定性测试工程师 | 打断边界动态实证、浸泡采样（RSS/日志增量）、长跑（24H）执行与报告 | `audit_04_interrupt_soak.py` |
| 证据保管员 | `runs/` 目录归档、证据文件命名与完整性、禁止覆盖历史证据 | `runs/` 全部 |

## 四、运行手册

前置条件：
- 工作目录 = 项目根 `D:\YHLZ2.0`；解释器 = `venv\Scripts\python.exe`
- 依赖：requests / numpy / psutil / websockets（venv 已具备）
- **隔离端口 8900**：脚本自动 spawn 独立后端实例，不影响运行中的
  WebUI(:5000) 与后端(:8000)
- 运行期间 8900 端口不可被占用

```bash
# 1. 启动可靠性（约 6 分钟）
venv\Scripts\python.exe "下载物象\任务计划\正式热机阶段\热机时期改进\V10.1.9_审计脚本\audit_01_startup.py"

# 2. 核心链路（约 2 分钟，含真实 LLM 调用）
venv\Scripts\python.exe "...\audit_02_chain.py"

# 2b. 针对性探针（约 1 分钟，含 edge-tts 网络）
venv\Scripts\python.exe "...\audit_02b_probe.py"

# 3. 运行时单元级实证（约 1 分钟）
venv\Scripts\python.exe "...\audit_03_runtime_unit.py"

# 4. 打断 + 浸泡（约 1 分钟；扩展 --hours 24 即长跑模式）
venv\Scripts\python.exe "...\audit_04_interrupt_soak.py"
```

验收标准：
- 脚本退出码 0；`runs/*_summary.json` 生成且字段完整
- 报告章节结论与 summary.json 一致
- 全量回归 Failed=0（每轮审计前后均须执行，见 §六）

## 五、证据管理（runs/ 目录）

```
runs/
  startup_01.log ~ startup_10.log / .err.log   冷启动各次 stdout/stderr
  conflict_a.log / conflict_b.err.log          端口冲突测试证据
  chain_server.log / .err.log                  链路测试实例日志
  chain_summary.json                           链路逐节点结果
  probe_server.log / .err.log                  探针实例日志
  probe_summary.json                           探针结果
  soak_server.log / .err.log                   浸泡实例日志
  interrupt_soak_summary.json                  打断+浸泡结果
  startup_summary.json                         启动测试汇总
```

- 证据文件**只追加不覆盖**（重跑前将旧 runs 改名为 `runs_<日期>/` 归档）
- 关键证据（僵尸 turn 日志、非法迁移日志、HTTP 500 报文）需在报告中引用行号

## 六、修改纪律（热机阶段）

### 6.1 谁可以改

| 变更类型 | 审批人 | 说明 |
|---|---|---|
| 脚本 bug 修复（注释/断言/路径） | 审计总负责 | 必须记录来源/原因/修改内容/验证结果 |
| 新增审计节点 | 审计总负责 | 需同步更新责任书与报告章节 |
| 修改端口/超时等参数 | 稳定性测试工程师 | 需确认 8900 空闲、超时 ≥ 真实 LLM 上限 |
| 删除/重命名脚本 | 禁止 | 保持历史可追溯 |

### 6.2 禁止事项

1. 禁止修改 `backend/`、`webui_server.py`、`frontend/` 任何业务代码（审计脚本是只读观察者）
2. 禁止在运行中 WebUI/后端实例的 8000/5000 端口上做破坏性测试
3. 禁止覆盖历史证据文件
4. 禁止用 PowerShell 读写 UTF-8 中文脚本（编码铁律：用 Python/编辑器 UTF-8 保存）
5. 禁止把脚本临时 hack 进主架构（审计脚本独立于业务代码）

### 6.3 回归纪律

每次修改脚本后执行（业务代码未动时仅跑受影响脚本即可，全部脚本涉及
审计结论则全量回归）：

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
# ...（7 个子系统全量，验收 Failed=0，基线 9472）
```

## 七、审计结论责任链

```
Prompt(§五~§十九 检查项)
  → 审计脚本（本目录 5 个文件，每项可复现）
  → runs/ 证据（日志 + JSON 汇总）
  → 报告（PASS/FAIL 判定 + 风险清单 + P0 修复建议）
  → 下一阶段（修复 → 回归 → 复审）
```

每项 PASS/FAIL 判定必须能在 30 分钟内由脚本复现，判定负责人为对应
角色；最终 READY/NOT READY 判定由审计总负责签署。

## 八、验收签字

| 角色 | 签字 | 日期 |
|---|---|---|
| 审计总负责（高级工程师） | | |
| 启动测试工程师 | | |
| 链路测试工程师 | | |
| 语音测试工程师 | | |
| 运行时测试工程师 | | |
| 稳定性测试工程师 | | |

---

**YHLZ · 元 · 亨 · 利 · 贞**
