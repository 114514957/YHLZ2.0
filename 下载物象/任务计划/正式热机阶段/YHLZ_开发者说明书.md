# YHLZ 2.0 开发者说明书

> 版本：V10.1（热机阶段）
> 适用：开发者（老万/老爹）日常操作
> 项目根目录：`D:\YHLZ2.0`
> 最后更新：2026-08-09

---

## 目录

1. [项目概览](#一项目概览)
2. [环境与依赖](#二环境与依赖)
3. [启动流程](#三启动流程)
4. [运行中的端口与进程](#四运行中的端口与进程)
5. [日常使用操作](#五日常使用操作)
6. [开发修改流程](#六开发修改流程)
7. [测试操作](#七测试操作)
8. [数据与文件位置](#八数据与文件位置)
9. [热机阶段操作](#九热机阶段操作)
10. [故障排查](#十故障排查)
11. [常用命令速查](#十一常用命令速查)

---

## 一、项目概览

YHLZ（元 · 亨 · 利 · 贞）是长期陪伴型 AI 伙伴系统，当前处于 **V10.1 热机阶段**（架构冻结，观察运行）。

### 系统组成

| 层 | 模块 | 端口 | 说明 |
|---|---|---|---|
| 前端 | `frontend/main.py`（桌面伙伴壳） | — | 一键启动元亨、伙伴状态显示、Ctrl+Shift+R 开发模式 |
| WebUI | `webui_server.py` | 5000 | 浏览器控制台（21 个功能页） |
| 后端 | `backend/main.py` | 8000 | FastAPI 服务（121 路由） |
| Live2D | `live2d_desktop_avatar.py` 等 | 8081/18765 | 桌宠形象 |

### 能力栈（全部 Failed=0）

```
有声音/有视觉/有记忆/有人格/有情绪/能思考/能创造/能表达/能感知/
能理解/能成长/能调度/能存在/能治理/能探索/能认知/能热机
+ 记忆稳定化(V10.1) + 交互协议(V10.1) + 模型池(V10.1.3)
+ Token优化(V10.1.3) + 人类/多模态层(V10.1.2)
```

---

## 二、环境与依赖

### 解释器

```
venv 路径: D:\YHLZ2.0\venv\Scripts\python.exe
（所有命令均用此解释器，勿用系统 python）
```

### 核心依赖（requirements.txt）

```
flask / flask-cors / fastapi / uvicorn / pydantic
openai / httpx / requests / psutil
torch / torchaudio / transformers / datasets
edge-tts / librosa / sounddevice
PyQt5 / PyQtWebSockets (前端桌面壳)
```

### 环境变量（backend/config.py 读取）

```
API 提供方:  api_provider=dashscope（当前）
LLM:         dashscope_model=qwen-turbo（百万 Token 额度）
             deepseek_model=deepseek-chat（备用）
视觉:        vl_model=qwen-vl-plus
TTS:         tts_engine=qwen3-tts-customvoice
ASR:         asr_model=funasr-SenseVoiceSmall
```

---

## 三、启动流程

### 方式一：一键启动（推荐，日常使用）

```
双击 start.bat
```

自动完成：
1. 检查 Python 与依赖（缺失自动安装 flask/PyQt5）
2. 创建 logs/webui_templates/webui_static 目录
3. 自动打开浏览器 `http://127.0.0.1:5000`
4. 启动 WebUI 服务（前台运行）

WebUI 内可启停：Backend(:8000) / Live2D / ASR / TTS / Avatar。

### 方式二：分步启动（开发调试用）

```powershell
# 1. 启动后端 API（必须最先，:8000）
D:\YHLZ2.0\venv\Scripts\python.exe backend\main.py

# 2. 启动 WebUI 控制台（:5000，新开终端）
D:\YHLZ2.0\venv\Scripts\python.exe webui_server.py

# 3. 启动桌面伙伴壳（新开终端，可选）
D:\YHLZ2.0\venv\Scripts\python.exe frontend\main.py
```

### 方式三：无界面启动检查（前端无 GUI 环境）

```powershell
D:\YHLZ2.0\venv\Scripts\python.exe frontend\main.py
# PyQt5 不可用时自动降级为启动检查 CLI：
#   [OK] environment / config / backend / runtime / ...
```

### 一键启动内部流程（StartupCore）

```
Environment Check → Load Config → Connect Backend(:8000/health)
→ Verify Runtime(/modules/status) → Load Identity(/personality/current)
→ Load Memory(/memory/list) → Init Model(/tts/engines)
→ Init Avatar(assets/live2d) → Ready → 元亨 ONLINE
```

每步返回状态（✓/✗），失败停止不崩溃，可跳过网络步骤。

---

## 四、运行中的端口与进程

| 端口 | 服务 | 说明 |
|---|---|---|
| 5000 | WebUI | 浏览器控制台 |
| 8000 | Backend API | 业务核心 |
| 8081 | Live2D | 桌宠服务模式 |
| 18765 | 桌宠内嵌查看器 | 优先于 8081 |

进程管理：WebUI 的 `/api/services/*` 启停；`/api/shutdown` 全停（顺序：avatar→live2d→backend→释放端口→存配置）。

---

## 五、日常使用操作

### 1. 聊天对话

```
浏览器 :5000 → 文本对话页 / 语音对话页
或 桌面伙伴壳（元亨 ONLINE 后直接对话）
```

### 2. 声音克隆

```
WebUI → 声音克隆页 → 上传音频 → 命名 → 克隆
（经质量门禁/去重，自动注册到 voice_identity）
```

### 3. 查看运行状态

```
WebUI → 服务总览页（服务卡片/端口/GPU）
WebUI → 系统页（CPU/内存/磁盘/GPU/基准测试）
桌面壳 → Ctrl+Shift+R（开发模式：System/AI/Memory/Trace 四区块）
```

### 4. 记忆管理

```
WebUI → 记忆页（搜索/查看/增删/优先级）
后端 API（记忆稳定化）:
  companion_memory_stabilize         # 压缩+权重+冲突报告
  companion_memory_prune_candidates  # 淘汰候选（不执行）
  companion_memory_prune_execute     # 显式执行淘汰
```

### 5. 模型池调度（V10.1.3）

```
后端 API:
  ModelPoolRouter.route(text)          # 分类任务→选择模型
  ModelPoolRouter.execute(model, fn)   # 执行调用（记录 Token/延迟）
  ModelPoolRouter.check_and_switch()   # Token 耗尽/异常→自动切换+交接
  ModelPoolRouter.model_status()       # 状态面板（Token 余额/等级）
```

### 6. Token 优化（V10.1.3）

```
后端 API:
  TokenOptimizer.compress_conversation()  # 对话压缩（结论/决定/问题/下一步）
  TokenOptimizer.cache_response()         # 响应缓存（减少重复调用）
  TokenOptimizer.budget_status()          # 预算状态（日/月/应急）
  TokenOptimizer.efficiency()             # Token 价值率
```

### 7. 每日反馈与多模态记录（V10.1.2）

```
后端 API:
  HumanOperatorLayer.daily_feedback(date, task, experience, problem, suggestion)
  HumanOperatorLayer.record(type, content)      # task/feedback/experience/issue/idea
  MultimodalExperienceLayer.process(input_type, content)
    # camera/screen/audio/video/stream/danmaku
    # 评分 0-10: 0-4 丢弃 / 5-7 短期 / 8-10 长期候选
```

---

## 六、开发修改流程

### 热机阶段铁律

```
冻结:  Agent Core / Identity / Constitution / Memory 架构 / Runtime 架构
冻结:  Frontend Runtime Shell / Startup Core / Avatar Framework
冻结:  Backend API 结构 / 数据接口
禁止:  换主体 LLM / 大规模改架构 / 加新能力模块 / 重做 UI / 复杂交互
```

### 正常修改流程

```
1. 现状确认    版本/测试基线/影响域
2. 变更设计    是否触碰冻结接口/回滚方案
3. 实现+测试   模块化/类型注解/中文注释/单元测试
4. 热机回归    六子系统 Failed=0（见下一节）
5. 验收评估    验收报告 .md
6. 返回 Prompt 下一阶段开发 Prompt
```

### 重大变化流程

```
Proposal → Constitution Check → Validation → Apply
（来源/原因/修改内容/验证结果 全程记录）
```

### 编码纪律

```
- 类型注解 / 中文 docstring / 完整日志 / RLock / 单例+reset
- 禁止跨层调用（Interface → Service → Manager → Storage/Adapter）
- 禁止硬编码（魔法数字进 config.py）
- 禁止 property 与 API 方法同名
- PowerShell 读写 UTF-8 中文文件用 Python（禁 Get-Content 无编码）
```

---

## 七、测试操作

### 全量回归（每次改动后必跑）

```powershell
cd D:\YHLZ2.0

# Embodied 认知层（8559 用例）
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests

# 视觉 / 行动 / Agent
venv\Scripts\python.exe -m unittest discover -s backend.vision.tests
venv\Scripts\python.exe -m unittest discover -s backend.action.tests
venv\Scripts\python.exe -m unittest discover -s backend.agent.tests

# 人格 / 声音身份
venv\Scripts\python.exe -m unittest discover -s backend.personality.tests
venv\Scripts\python.exe -m unittest discover -s "D:\YHLZ2.0\backend\voice_identity\tests"

# 前端（118 用例）
venv\Scripts\python.exe -m unittest discover -s frontend.tests -p "test_*.py"
```

### 验收标准

```
专项达标线（当前）:
  embodied 8559  Failed=0 (Skipped=2 Tesseract 保护)
  vision 136 / action 151 / agent 131
  personality 137 / voice_identity 181
  frontend 118
全量: 9413 Failed=0 ✅
```

### 单模块测试

```powershell
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests -p "test_v1013_model_pool.py"
```

---

## 八、数据与文件位置

| 路径 | 内容 |
|---|---|
| `backend/data/personality.json` | 人格配置（铁哥们） |
| `backend/data/voice_identity.db` | 声音身份数据库 |
| `backend/data/vision_memories.db` | 视觉记忆 |
| `memory/user_identity.md` | 用户身份锚点（长期基础记忆，仅用户修改） |
| `memory/yhlz_project_context.md` | 项目上下文 |
| `memory/collaboration_rules.md` | 协作规则 |
| `human_feedback/` | 每日反馈（feedback_日期.json）与记录 JSONL |
| `logs/webui_YYYYMMDD.log` | WebUI 日志（按日滚动） |
| `logs/backend_stdout.log` / `backend_stderr.log` | 后端日志 |
| `webui_config.json` | WebUI 设置 |
| `gui_config.json` | GUI 状态 |
| `assets/live2d/` | Live2D 模型（akari/hijiki/hiyori/tororo/wanko） |
| `下载物象\任务计划\` | 工程文档（四阶段/五阶段/热机阶段/正式热机阶段） |

---

## 九、热机阶段操作

### 每日流程（开发者行为备忘录）

```
电脑开机 → 元亨自动启动 → 检查运行状态（在线/正常/无异常）
→ 正常则直接使用（不要手动修改/反复测试/频繁重启）
```

### 每日 5 分钟检查

```
1. 系统状态: 正常启动/运行时长/错误/自动恢复
2. 记忆状态: 今天新增了什么记忆（关注质量不关注数量）
3. 协作效果: 是否理解目标/减少重复解释/推进工作
```

### 每日人工记录（3-5 句）

```
日期 / 今天主要任务 / 让元亨参与 / 帮助最大的地方 / 发现的问题 / 新想法
→ 经 HumanOperatorLayer.daily_feedback() 写入 human_feedback/
```

### 热机周期

```
第一阶段 7 天   稳定运行
第二阶段 30 天  发现长期问题
第三阶段 90 天  评估成长能力
```

### 验收标准（8 级）

```
Identity ≥99% 连续性 | Constitution 0 违反 | Memory 有效>无效
Runtime 72h Crash=0 | Observability 全追踪 | Frontend 一键启动
Performance 普通<2s/复杂<5s | Maintenance Log/Trace/Recovery/Rollback
```

### 热机监控

```
每日 Runtime Report（热机监控.md 填写）:
  系统状态/模型状态/Memory变化/异常事件/用户交互/性能变化/优化建议
发现异常: Issue生成 → Trace定位 → 原因分析 → 隔离测试 → 修复 → 回归 → 记录
禁止: 直接修改核心
```

---

## 十、故障排查

| 症状 | 排查步骤 |
|---|---|
| WebUI 打不开 :5000 | 1) 检查 start.bat 终端报错 2) `is_port_in_use(5000)` 端口占用→kill_port_process 自动处理 3) 看 logs/webui_*.log |
| 后端不可达 :8000 | 1) WebUI 服务总览页查看 backend 状态 2) 手动 `python backend\main.py` 3) 看 logs/backend_stderr.log |
| 对话报错"后端未启动" | 先启动 backend 再对话（WebUI 内 services/start backend） |
| 声音克隆失败 | 1) 检查音频文件/命名 2) 看返回 stage（validate/service_init/proxy） 3) 后端日志 |
| 前端桌面壳异常 | 1) 确认 PyQt5 已装 2) `python frontend\main.py` 无 GUI 降级启动检查定位 |
| 记忆异常 | companion_memory_stabilize() 报告 + companion_memory_stabilization_audit() 审计 |
| 模型池切换 | model_status() 查看 Token 等级 + call_history() 调用记录 |
| 中文乱码 | 确认命令前 `chcp 65001`；Python 脚本内 UTF-8 读写 |

---

## 十一、常用命令速查

```powershell
# 启动
start.bat                                  # 一键启动（推荐）
venv\Scripts\python.exe backend\main.py    # 后端 :8000
venv\Scripts\python.exe webui_server.py    # WebUI :5000
venv\Scripts\python.exe frontend\main.py   # 桌面伙伴壳

# 测试
venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests
venv\Scripts\python.exe -m unittest discover -s frontend.tests -p "test_*.py"

# 状态
curl http://127.0.0.1:8000/health          # 后端健康
curl http://127.0.0.1:8000/modules/status  # 模块状态
curl http://127.0.0.1:5000/api/status      # WebUI 服务状态
curl http://127.0.0.1:5000/api/system/info # 系统信息
```

---

**YHLZ · 元 · 亨 · 利 · 贞**
