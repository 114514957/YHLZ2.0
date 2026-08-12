# YHLZ 会话交接文档（V9.5 热机版）

> 上下文压缩前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 热机阶段目录：`下载物象\任务计划\热机阶段\`。
> 工作区：`backend/`（对话层）+ `backend/embodied/`（认知层）。
> venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。
> 生成日期：2026-08-09

---

## 0. 当前最高优先级（下一会话先处理）

**任务：V10.0 Warm Runtime Phase 1（热机运行第一阶段）**

- 任务文件：`热机阶段\YHLZ_V10.0_Warm_Runtime_Phase1_Prompt.md`
- 核心：**Architecture Freeze + Controlled Runtime**（架构冻结 + 受控热机 + 长期验证）
- Alpha 完成项：依赖冻结 / 日志系统 / 状态保存 / 异常恢复
- 验收：长期运行稳定 / 状态可恢复 / 数据可追踪 / 记忆可治理 /
  模型可替换 / 安全边界保持 / 优化可验证

---

## 1. 热机基线（V9.5.0 确认）

```
版本:    9.5.0 (embodied __version__ / service.report / companion.status 一致)
测试:    8330 全部 Failed=0
         embodied 7594 | vision 136 | action 151 | agent 131
         personality 137 | voice_identity 181 (Skipped=2 Tesseract 保护)
能力栈:  身份/记忆/反思/成长/调度/表达/治理/创造/研究/元认知 全链路
双栈:    对话系统 (backend 根目录) + Embodied AI (backend/embodied)
热机判定: ✅ V9.5.0 进入热机阶段 (详见 热机建议_V9.5.txt)
```

## 2. 双栈架构（热机运行对象）

```
[对话系统层] backend/ 根目录 (实时语音链路)
  main.py :8000 → asr/vad/llm/tts/audio/context/conversation/emotion
  webui_server.py :5000 (WebUI) + :8000 (API) + :8081 (Live2D)

[Embodied AI 层] backend/embodied/ (认知伙伴 V2.1~V9.5)
  service.py (EmbodiedService, 唯一 API 入口)
  companion/ 21 个子包 (personality~meta_cognition)

[独立子系统] agent/ vision/ action/ personality/ voice_identity/ (全部 Failed=0)
```

## 3. 热机运行手册

### 3.1 启动

```bash
python backend/main.py        # 后端 API :8000
python webui_server.py        # WebUI :5000 (自动拉起后端)
start.bat                     # 单击启动 (惯例)
```

### 3.2 回归纪律（每次改动必跑）

```bash
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
venv\Scripts\python.exe -m unittest discover -s backend.vision.tests
venv\Scripts\python.exe -m unittest discover -s backend.action.tests
venv\Scripts\python.exe -m unittest discover -s backend.agent.tests
venv\Scripts\python.exe -m unittest discover -s backend.personality.tests
venv\Scripts\python.exe -m unittest discover -s "D:\YHLZ2.0\backend\voice_identity\tests"
# 验收: Failed = 0
```

### 3.3 配置

- 全部配置进 `backend/config.py`（环境变量 + 默认值）
- 前缀：`asr_*` / `tts_*` / `llm_*` / `vad_*` / `vision_*` /
  `perception_*` / `agent_*` / `embodied_*` / `companion_*`
- 测试模式：`YHLZ_TEST_MODE` / `YHLZ_VOICE_IDENTITY_TEST_MODE` /
  `YHLZ_VISION_TEST_MODE` / `YHLZ_PERCEPTION_TEST_MODE` /
  `YHLZ_RUN_REAL_TESTS`（真实设备）
- **禁止重复定义同名配置项**

### 3.4 数据

```
backend/data/personality.json        (人格配置)
backend/data/vision_memories.db      (视觉记忆)
backend/data/voice_identity.db       (声音身份)
backend/data/voice_cache/            (声音克隆缓存)
定期备份; 快照恢复经 companion_persistence_load
```

## 4. 热机阶段核心约束（架构冻结）

```
优先级:  Identity > Safety > Constitution > Cognition > Optimization
禁止:    自动修改核心身份 / 自动修改最高原则 / 自动扩大权限 /
         未验证写入核心记忆
重大变化: Proposal → Constitution Check → Validation → Apply
稳定优先: 禁止为了增加能力破坏系统稳定
可追踪:   任何优化必须记录 来源/原因/修改内容/验证结果
```

## 5. V10 热机规划（衔接）

| 版本 | 目标 | 完成项 |
|---|---|---|
| V10.0 Alpha | 稳定运行 | 依赖冻结/日志系统/状态保存/异常恢复 |
| V10.1 | Memory Stabilization | 压缩/淘汰/权重评估/冲突检测 |
| V10.2 | Cognitive Optimization | 错误模式学习/策略评价/风险预测 |
| V10.5 | Multimodal Experience Layer | Text/Vision/Audio/Video/Action 统一 Experience Object |

（注：此前四阶段 `YHLZ_V10.0_下一步开发Prompt.txt` 为认知综合路线，
热机阶段以本目录 Phase1 Prompt 为准；两者可合并：先热机稳定，
再在 V10.1/V10.2 中完成认知综合四项）

## 6. 关键事实清单（热机维护速查）

### 6.1 版本字面量陷阱

test_snapshot/test_v60 版本语义：minor "9.1.0" / major 拒绝 "10.0.0" /
篡改 replace 9.0.0→10.0.0。**热机阶段不升主版本**（架构冻结），
如确需升版批量替换 "9.5.0"→"X" 后必须同步这三处。

### 6.2 生成式测试纪律

setattr 生成时 test.__name__ 在工厂函数体内赋值；闭包默认参数绑定
当前循环值；any(...) 生成器需括号包裹；测试文件 CRLF。

### 6.3 工程铁律

- 先读后写 / 接口先行 / 配置驱动 / 向后兼容
- 中文 docstring / 类型注解 / 完整日志 / RLock / 单例+reset
- Mock 优先 / 无测试不交付 / 禁止静默吞异常 / 禁止跨层调用
- 分层: Interface → Service → Manager → Storage/Adapter
- property 与 API 方法禁止同名；新 API 独立命名避冲突
- PowerShell GBK: 读写 UTF-8 中文文件用 Python，禁 Get-Content 无编码

### 6.4 能力域速查（embodied/companion）

```
personality(V5.5) relationship(V5.6) experience(V5.7)
reflection(V5.8/6.5/6.6) creative(V5.9) continuity/persistence(V6.0)
emotion/rhythm(V6.1.1) expression(V6.2) perception(V6.2~6.4)
memory(V6.3) verification(V5.8) growth(V6.5/6.6) identity(V6.5)
hybrid(V6.8) embodied_presence(V7.0) constitution(V8.0)
creative_intelligence(V8.5) research_engine(V9.0) meta_cognition(V9.5)
```

## 7. 已知遗留 / 风险（热机关注）

| 问题 | 影响 | 热机处置 |
|---|---|---|
| 记忆膨胀/重复 | 长期运行内存增长 | V10.1 Memory Stabilization |
| 认知记忆内存驻留 | 重启丢失 | V10.0 状态保存/快照 |
| 真实模型未接入 | HIL 全 Mock | Model Abstraction 层就绪, 可替换 |
| 对话层与认知层未融合 | 双栈并行 | V10.5 多模态统一 |
| Tesseract 未安装 | skipIf 保护 | 安装后自动启用 |
| 对话DEMO/ 旧目录 | 冗余 | 可归档（建议书） |

## 8. 工程文档索引

```
下载物象\任务计划\四阶段\      (V6.0~V9.5 验收报告 + 开发 Prompt)
下载物象\任务计划\五阶段\      (V7.0/V8.0/V8.5/V9.0/V9.5 宪章+Prompt)
下载物象\任务计划\交接\        (V6.5/V6.6/V6.8/V7.0/V8.0/V8.5/V9.0/V9.5 交接
                                + 模块依赖清单_V9.5 + 热机建议_V9.5)
下载物象\任务计划\热机阶段\    (V10.0 Warm Runtime Phase1 Prompt
                                + 本交接文档 + 开发习惯 V4.0)
```

---

**YHLZ · 元 · 亨 · 利 · 贞**
