# YHLZ 会话交接文档（V10.1.8 热机版）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 热机阶段目录：`下载物象\任务计划\正式热机阶段\`。
> 工作区：`backend/`（对话层）+ `backend/embodied/`（认知层）+ `frontend/`（桌面壳）。
> venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-10

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V10.1.8 Real-time AI Companion Runtime 收尾与长期运行验证**

- 核心：Stable Conversation Runtime → Real-time AI Companion Runtime 已完成
- 待办：
  1. ⚠️ **系统音频输出排查**（tts_test.wav 播放无声，疑似系统扬声器/输出设备问题，非 YHLZ 软件）
  2. ⚠️ 浏览器实际语音体验实测（AEC/NS/AGC 生效 + TTS 自动播放）
  3. ⏳ 8h/72h 长期运行观察（内存/队列/状态泄漏）
  4. WebUI 完整对话状态面板接入

---

## 1. 热机基线（V10.1.8 确认）

```
版本:    10.1.8 (embodied __version__ 仍 9.5.0, 热机不升主版本)
测试:    9472 全部 Failed=0
         embodied 8618 | vision 136 | action 151 | agent 131
         personality 137 | voice_identity 181 | frontend 118
能力栈:  身份/记忆/反思/成长/调度/表达/治理/创造/研究/元认知/热机
对话:    Turn Controller + 事件协议 + 3句→8条窗口 + 输入治理 + 分层打断
双栈:    对话系统 (backend 根目录) + Embodied AI (backend/embodied)
         + 前端壳 (frontend/) + WebUI (webui_server)
热机判定: ✅ V10.1.8 进入 Real-time AI Companion Runtime
```

## 2. 双栈架构（热机运行对象）

```
[对话系统层] backend/ 根目录 (实时语音链路)
  main.py :8000 → /chat(事件协议SSE) /transcribe /synthesize /interrupt
  conversation_controller.py → Turn 状态机/事件/队列/打断/延迟
  input_aggregator.py → 输入分类/合并/优先级治理
  context_manager.py → 8条窗口 + 工作摘要压缩
  webui_server.py :5000 → 服务编排 + API 代理 + SSE 透传

[Embodied AI 层] backend/embodied/ (认知伙伴 V2.1~V10.1.8)
  service.py (EmbodiedService, 唯一 API 入口)
  companion/ 22 个子包 (personality~meta_cognition~memory_stabilization~interaction)

[前端壳] frontend/ (Companion Runtime Shell)
  main.py → 一键启动元亨 + 开发模式
  runtime/ → 状态机/事件/追踪
  avatar/ → 情绪驱动动画
  startup/ → 9步一键启动

[独立子系统] agent/ vision/ action/ personality/ voice_identity/ (全部 Failed=0)
```

## 3. 热机运行手册

### 3.1 启动

```bash
start.bat                      # 单击启动 (WebUI :5000 + 后端 :8000)
python backend/main.py         # 后端 API :8000 (WebUI 内可启停)
python webui_server.py         # WebUI :5000
python frontend/main.py        # 桌面伙伴壳 (一键启动元亨)
```

### 3.2 回归纪律（每次改动必跑）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
venv\Scripts\python.exe -m unittest discover -s backend.vision.tests
venv\Scripts\python.exe -m unittest discover -s backend.action.tests
venv\Scripts\python.exe -m unittest discover -s backend.agent.tests
venv\Scripts\python.exe -m unittest discover -s backend.personality.tests
venv\Scripts\python.exe -m unittest discover -s "D:\YHLZ2.0\backend\voice_identity\tests"
venv\Scripts\python.exe -m unittest discover -s frontend.tests -p "test_*.py"
# 验收: Failed = 0 (基线 9472)
```

### 3.3 配置

- 全部配置进 `backend/config.py`（环境变量 + 默认值）
- 前缀：`asr_*` / `tts_*` / `llm_*` / `vad_*` / `vision_*` / `perception_*` / `agent_*` / `embodied_*` / `companion_*`
- 模型：`api_provider=dashscope` / `dashscope_model=qwen-turbo` / `tts_engine=qwen3-tts-customvoice` / `asr_model=funasr-SenseVoiceSmall` / `vl_model=qwen-vl-plus`
- 测试模式：`YHLZ_TEST_MODE` / `YHLZ_VOICE_IDENTITY_TEST_MODE` / `YHLZ_VISION_TEST_MODE` / `YHLZ_PERCEPTION_TEST_MODE`
- **禁止重复定义同名配置项**

### 3.4 数据

```
backend/data/personality.json        (人格配置: 铁哥们)
backend/data/voice_identity.db       (声音身份)
backend/data/vision_memories.db      (视觉记忆)
backend/data/agent_memories.db       (Agent 记忆)
memory/                              (长期基础记忆: 用户身份/项目上下文/协作规则)
human_feedback/                      (每日反馈)
logs/                                (webui_YYYYMMDD.log / backend_stdout.log / stderr.log)
定期备份; 快照恢复经 companion_persistence_load
```

## 4. 对话运行时（V10.1.8 核心）

### 4.1 对话状态机（11 态）

```
IDLE → RECEIVING → READY → PROCESSING → STREAMING → TTS_PLAYING → COMPLETED → IDLE
异常: PROCESSING/STREAMING/TTS_PLAYING → INTERRUPTED → QUEUED/READY
      ERROR → RECOVERY → READY
```

### 4.2 事件协议

```
事件: START / TOKEN / FLUSH / COMPLETE / INTERRUPTED / ERROR / HEARTBEAT
字段: conversation_id / turn_id / timestamp / sequence / event_type / payload
前端: sequence 单调递增, 旧 turn 事件丢弃
```

### 4.3 分层打断

```
llm   → 取消生成
tts   → 停止播放 (最高优先级)
queue → 清理低优先级任务
记录: interrupt_time / stopped_layer / recovery_time
```

### 4.4 输入治理

```
分类: important / normal / chat / noise
合并: 重复问题 (重叠率 80%)
队列: 优先级队列 (重要>普通>闲聊), 上限 20
治理: 噪声丢弃 / 队满高优先挤掉最低 / 低优先被拒
```

### 4.5 上下文

```
窗口: 8 条 (~4轮), 超窗压缩 → 工作摘要
摘要保留: 用户目标 / 当前任务 / 已确认结论 / 未完成事项 / 关键实体
优先级: Current > Working Summary > Relevant Memory > Long-term
```

### 4.6 流式

```
LLM Streaming → SSE → WebUI (保留)
句级切分 (4/8/50 字) → 并行 TTS 预合成 → 顺序播放 (DEMO 流模式)
音频层: WebRTC AEC/NS/AGC (回声/降噪/增益)
防回声: 文本重叠率 > 60% (仅异常保护)
```

## 5. 热机阶段核心约束（架构冻结）

```
优先级:  Identity > Safety > Constitution > Cognition > Optimization
禁止:    自动修改核心身份 / 自动修改最高原则 / 自动扩大权限 /
         未验证写入核心记忆 / 推倒现有 Streaming
重大变化: Proposal → Constitution Check → Validation → Apply
稳定优先: 禁止为了增加能力破坏系统稳定
可追踪:   任何优化必须记录 来源/原因/修改内容/验证结果
```

## 6. 热机规划（衔接）

| 版本 | 目标 | 状态 |
|---|---|---|
| V10.0 | Warm Runtime Phase1 | ✅ 完成 |
| V10.1 | Memory Stabilization | ✅ 完成 |
| V10.1.2 | Human & Multimodal Layer | ✅ 完成 |
| V10.1.3 | Model Pool + Token Optimization | ✅ 完成 |
| V10.1.5 | Full Chain Test | ✅ READY |
| V10.1.7 | Turn Controller + 事件协议 | ✅ READY |
| **V10.1.8** | **Real-time AI Companion Runtime** | ✅ **当前** |
| V10.2 | Cognitive Optimization | ⏳ 规划 |
| V10.5 | Multimodal Experience Layer | ⏳ 规划 |

## 7. 关键事实清单（热机维护速查）

### 7.1 版本字面量陷阱

test_snapshot/test_v60 版本语义：minor "9.1.0" / major 拒绝 "10.0.0" /
篡改 replace 9.0.0→10.0.0。热机阶段不升主版本，如确需升版批量替换后
必须同步这三处。

### 7.2 生成式测试纪律

setattr 生成时 test.__name__ 在工厂函数体内赋值；闭包默认参数绑定
当前循环值；any(...) 生成器需括号包裹；测试文件 CRLF。

### 7.3 工程铁律

- 先读后写 / 接口先行 / 配置驱动 / 向后兼容
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 禁止静默吞异常 / 禁止跨层调用
- 分层: Interface → Service → Manager → Storage/Adapter
- property 与 API 方法禁止同名；新 API 独立命名避冲突
- PowerShell GBK: 读写 UTF-8 中文文件用 Python，禁 Get-Content 无编码
- 事件协议: 前端必须 sequence 单调, 旧 turn 不覆盖
- 上下文: 3句→8条窗口 + 工作摘要 (V10.1.8)

### 7.4 能力域速查（embodied/companion）

```
personality(V5.5) relationship(V5.6) experience(V5.7)
reflection(V5.8/6.5/6.6) creative(V5.9) continuity/persistence(V6.0)
emotion/rhythm(V6.1.1) expression(V6.2) perception(V6.2~6.4)
memory(V6.3) verification(V5.8) growth(V6.5/6.6) identity(V6.5)
hybrid(V6.8) embodied_presence(V7.0) constitution(V8.0)
creative_intelligence(V8.5) research_engine(V9.0) meta_cognition(V9.5)
memory_stabilization(V10.1) interaction(V10.1) warm_health(V10.0)
```

## 8. 已知遗留 / 风险（热机关注）

| 问题 | 影响 | 热机处置 |
|---|---|---|
| ⚠️ 系统音频输出（wav 无声） | TTS 播放无声 | 排查扬声器/输出设备 |
| ⚠️ 浏览器语音实测未确认 | 语音对话闭环 | 用户实测 (AEC/TTS播放) |
| WebUI 重启后不接管已有后端 | 崩溃监控缺口 | 记录 GAP-1 |
| 记忆膨胀 | 长期内存增长 | V10.1 稳定化已落地 |
| 真实模型未接入 | HIL 全 Mock | Model Abstraction 就绪 |
| 对话层与认知层未融合 | 双栈并行 | V10.5 多模态统一 |

## 9. 工程文档索引

```
下载物象\任务计划\正式热机阶段\
  ├─ YHLZ_开发者说明书.md              (启动/操作/测试)
  ├─ YHLZ_启动现状与启动测试方案书.md   (启动测试方案)
  ├─ YHLZ_启动测试报告_20260810.md     (启动测试报告)
  ├─ YHLZ_错误与检修报告_20260810.md   (UI异常排查)
  ├─ YHLZ_端口与配置白皮书.md          (端口/配置)
  ├─ YHLZ_链路功能与待测试目标白皮书.md (链路/功能/测试目标)
  ├─ 启动初始化\
  │   ├─ YHLZ_Full_Chain_Test_Report.md         (全链路验证)
  │   ├─ YHLZ_流式规则白皮书.md                 (流式规则)
  │   ├─ YHLZ_对话链路对比_DEMO_vs_当前.md      (DEMO对比)
  │   ├─ YHLZ_启动测试报告_第二次_20260810.md   (二次启动测试)
  │   └─ YHLZ_全链路全流程测试报告_第二次_20260810.md
  ├─ 热机时期改进\
  │   ├─ YHLZ_Heatup_Improvement_Report.md      (V10.1.7 改进)
  │   ├─ YHLZ_对话规则架构流式设计.md           (规则/架构/流式)
  │   ├─ YHLZ_V10.1.8_热机修正报告.md           (V10.1.8 修正)
  │   └─ 本交接文档
  ├─ 热机监控.md                     (每日 Runtime Report, 待填充)
  ├─ 开发者行为备忘录.txt            (每日使用原则)
  └─ 开发者身份注入.md               (身份锚点)
```

---

**YHLZ · 元 · 亨 · 利 · 贞**
