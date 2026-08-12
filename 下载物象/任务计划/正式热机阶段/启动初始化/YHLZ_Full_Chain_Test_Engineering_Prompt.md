# YHLZ Full Chain Test Engineering Prompt

版本：
V10.1.5

项目：
YHLZ AI伙伴「元亨」

模块：
Full Chain Validation System

全链路验证系统

---

# 一、测试目标

当前阶段：
热机启动阶段。

核心目标：
验证YHLZ完整运行链路。

不是测试：
- 高级智能
- 自主成长
- 复杂Agent能力

优先验证：
系统是否稳定运行。

---

# 二、测试范围

用户
↓

WebUI
↓

Frontend Layer
↓

API Gateway
↓

Backend
↓

Runtime Core
↓

Context Manager
↓

Memory Layer
↓

Model Router
↓

LLM Provider
↓

Response
↓

Logging
↓

Monitoring
↓

User Display

---

# 三、测试原则

1. 先保证闭环。
基础链路失败时禁止进入高级模块测试。

2. 每个模块必须：
- 可观察
- 可记录
- 可定位

3. 所有失败必须产生 Error Trace。

---

# 四、测试阶段

## Phase 0 环境验证

检查：
- OS
- CPU
- GPU
- RAM
- Storage
- Python
- Dependencies
- Config Files
- Frontend Port
- Backend Port
- Database
- API Service

输出：
Environment Report

---

## Phase 1 前端链路测试

验证：
- 页面加载
- 静态资源
- 配置读取
- 用户请求发送

测试输入：

你好

记录：
- Request ID
- Timestamp
- Payload

---

## Phase 2 Backend API测试

检查：
- Route
- Controller
- Middleware
- Exception Handler
- Response Format

验证：
请求进入、处理、返回完整。

---

## Phase 3 Runtime核心测试

验证：
- Runtime启动
- User Identity加载
- Project Context加载
- Rules加载
- 状态保持

---

## Phase 4 LLM调用测试

测试：

你好

记录：
- Model
- API Status
- Latency
- Token Usage
- Response

---

## Phase 5 Memory测试

验证：

写入测试记忆。

读取测试记忆。

确认Memory不阻塞主流程。

---

## Phase 6 Model Router测试

模拟主模型不可用。

验证：

检测异常

↓

保存上下文

↓

切换模型

↓

恢复任务

---

## Phase 7 Token优化测试

验证：

- Context压缩
- Memory检索
- Token统计

记录：

- Input Token
- Output Token
- Total Token
- Cost

---

## Phase 8 日志监控测试

记录：

- 启动时间
- 请求ID
- 用户输入
- 模型调用
- 错误
- 延迟
- Token
- Memory操作

---

## Phase 9 WebUI状态测试

显示：

系统：

- Runtime Online
- Backend Online
- LLM Connected
- Memory Active

性能：

- Latency
- Token
- CPU
- GPU
- Memory Usage

错误：

- 最近错误
- 异常次数
- 恢复状态

---

# 五、压力测试

连续对话：

100轮。

长期运行：

8小时。

观察：

- 崩溃
- 内存泄漏
- 服务中断
- 延迟变化

---

# 六、失败处理

任何FAIL：

记录错误

↓

定位模块

↓

生成报告

↓

修复

↓

重新测试

禁止跳过。

---

# 七、最终验收报告

输出：

YHLZ Full Chain Test Report

Environment:
PASS / FAIL

Frontend:
PASS / FAIL

Backend:
PASS / FAIL

Runtime:
PASS / FAIL

LLM:
PASS / FAIL

Memory:
PASS / FAIL

Router:
PASS / FAIL

Token:
PASS / FAIL

Monitoring:
PASS / FAIL

User Experience:
PASS / FAIL

Final Result:
READY / NOT READY

Blocking Issues:
xxx

Next Action:
xxx

---

# 八、热机通过标准

必须达到：

✓ 可以正常对话

✓ 请求链路完整

✓ 错误可追踪

✓ 状态可观察

✓ Memory可读写

✓ 模型调用稳定

✓ WebUI显示正常

✓ 长时间运行稳定

达到：

YHLZ Runtime Heatup Ready

---

YHLZ
元 · 亨 · 利 · 贞
