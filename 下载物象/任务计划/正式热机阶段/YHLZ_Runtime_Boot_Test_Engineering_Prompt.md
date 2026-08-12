# YHLZ Runtime Boot Test Engineering Prompt

版本：
V10.1.4

项目：
YHLZ AI伙伴「元亨」

模块：
Runtime Boot Diagnostic System

---

## 一、当前任务目标

当前阶段：热机启动阶段。

首要目标：

不是扩展功能。

不是验证高级能力。

而是确保 YHLZ 核心运行链路完整。

必须首先实现：

用户
↓

前端
↓

Backend
↓

Runtime
↓

LLM
↓

Response
↓

Memory

完整闭环。

---

## 二、故障原则

如果无法正常对话：

禁止继续添加功能。

必须进入诊断模式。

优先解决：

- 通信问题
- 配置问题
- 模型调用问题
- 上下文问题

---

## 三、启动检查流程

### Step 1 环境检查

检查：

- Python版本
- 依赖包
- 环境变量
- 配置文件
- API Key
- 端口状态
- 数据库状态
- Memory路径
- 日志路径

输出：

Environment Report

### Step 2 Backend检查

检查：

- main.py
- 路由注册
- API接口
- 异常处理
- Middleware

验证 Backend 是否正常启动。

### Step 3 Frontend检查

检查：

- 页面加载
- API连接
- WebSocket
- 请求发送
- 错误显示

确认前端请求是否到达Backend。

### Step 4 LLM调用检查

测试：

你好

记录：

- Model
- Latency
- Token
- Error

### Step 5 Memory检查

测试：

- 写入测试记忆
- 读取测试记忆

确认 Memory 不阻塞主流程。

---

## 四、最小可运行模式

如果完整系统失败：

启动 Minimal Runtime Mode。

关闭：

- Memory增强
- Agent循环
- 多模型调度
- 高级模块

只保留：

Input → LLM → Output

目标：

恢复基础对话。

---

## 五、日志系统要求

必须开启：

Runtime Debug Log

记录：

- 启动时间
- 请求ID
- 用户输入
- 调用模型
- 响应时间
- 错误信息
- Token消耗
- 异常堆栈

---

## 六、错误定位规则

A类：启动失败

检查：
依赖、配置、路径。

B类：接口失败

检查：
Route、请求、返回格式。

C类：模型失败

检查：
API、额度、模型名称、参数。

D类：Memory失败

检查：
数据库、权限、路径。

E类：性能问题

检查：
延迟、阻塞、循环。

---

## 七、热机启动顺序

严格执行：

Phase 0
环境启动

↓

Phase 1
基础聊天测试

↓

Phase 2
Memory测试

↓

Phase 3
Runtime测试

↓

Phase 4
Agent功能测试

↓

Phase 5
高级模块启用

禁止跳过基础阶段。

---

## 八、基础聊天验收测试

测试1：

输入：
你好

期望：
正常返回。

测试2：

输入：
介绍一下自己

期望：
读取身份记忆。

测试3：

输入：
现在YHLZ是什么状态？

期望：
读取项目上下文。

测试4：

连续对话10轮。

验证：
上下文保持。

---

## 九、热机阶段暂时关闭模块

如果影响稳定：

暂时关闭：

- Model Router
- 自动Memory总结
- 多Agent
- 复杂规划
- 多模态

原因：

先建立稳定核心。

---

## 十、启动报告格式

返回：

YHLZ Runtime Boot Report

环境：
PASS / FAIL

Backend：
PASS / FAIL

Frontend：
PASS / FAIL

LLM：
PASS / FAIL

Memory：
PASS / FAIL

基础对话：
PASS / FAIL

当前阻塞：
xxx

下一步：
xxx

---

## 十一、最终目标

达到：

Stable Runtime State

标准：

- 用户可以正常交流
- 系统可以记录状态
- 错误可以追踪
- 模块可以逐步开启

---

YHLZ

元 · 亨 · 利 · 贞
