# YHLZ 启动现状与启动测试方案书

> 版本：V10.1（热机阶段）
> 日期：2026-08-10
> 依据：启动现状实测 + 热机启动验收 Prompt

---

## 目录

1. [启动现状](#一启动现状)
2. [启动架构](#二启动架构)
3. [启动测试目标](#三启动测试目标)
4. [测试环境与前置条件](#四测试环境与前置条件)
5. [测试用例设计](#五测试用例设计)
6. [测试执行流程](#六测试执行流程)
7. [验收标准](#七验收标准)
8. [异常处理与回滚](#八异常处理与回滚)
9. [测试记录模板](#九测试记录模板)

---

## 一、启动现状

### 1.1 当前运行状态（2026-08-10 实测）

```
端口 5000 (WebUI):   运行中  ← 前端控制台
端口 8000 (Backend): 运行中  ← 业务核心
端口 8081 (Live2D):  空闲    ← 可选服务（桌宠未启动）

WebUI /api/health:   status=ok    → 前端显示"已连接" ✅（修复后）
Backend /health:     healthy      model=qwen-turbo
                     llm=true tts=true vad=true
                     asr=false（按需加载，首次语音调用时加载）

服务状态: webui running / backend running
首页访问: HTTP 200 ✅
```

### 1.2 已完成的修复（2026-08-10）

| # | 修复 | 状态 |
|---|---|---|
| 1 | `/api/health` 状态归一化（healthy→ok，消除 UI 误报） | ✅ 已验证 |
| 2 | `/api/chat` SSE 透传（消除 500） | ✅ 已验证 |
| 3 | WebUI 多实例清理（单实例运行） | ✅ 已完成 |

### 1.3 启动链路现状

```
start.bat
  └─ python webui_server.py (:5000)
       └─ 浏览器自动打开 http://127.0.0.1:5000
       └─ WebUI 内手动/自动拉起后端:
            POST /api/services/backend/start
            └─ subprocess 启动 backend/main.py (:8000)
                 └─ 加载配置 → LLM(qwen-turbo) → TTS(Qwen3) → VAD
                 └─ ASR 懒加载 (SenseVoiceSmall, 首次调用)
            └─ wait_backend 线程: 60s 内就绪 + 意外退出自动重启(≤3次)
```

### 1.4 启动耗时基线（实测）

```
后端启动（冷启动，模型加载）: 约 30~50 秒
  - 配置加载: <1s
  - LLM 接入: <5s（API 模式）
  - TTS 模型加载: 20~40s（Qwen3-TTS 本地）
  - VAD 就绪: <5s
  - ASR: 懒加载（首次语音请求时另需数秒）
WebUI 启动: <3s
```

---

## 二、启动架构

```
┌────────────────────────────────────────────────┐
│  用户                                            │
│  ├─ 浏览器 → WebUI (:5000)                      │
│  └─ 桌面伙伴壳 → frontend/main.py (可选)         │
└───────────────┬────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────┐
│  WebUI 编排层 (webui_server.py)                 │
│  ├─ 服务状态管理 (端口/进程/标志三态探测)         │
│  ├─ API 代理 (50+ 路由 → :8000)                 │
│  ├─ 后端进程管理 (拉起/监控/自动重启)             │
│  └─ 日志/配置/系统信息                           │
└───────────────┬────────────────────────────────┘
                │ HTTP :8000
┌───────────────▼────────────────────────────────┐
│  Backend 业务层 (backend/main.py, FastAPI)      │
│  ├─ /health /chat /synthesize /transcribe      │
│  ├─ /voice/* (克隆/管理/质量/审计)               │
│  ├─ /memory /personality /live2d /agent        │
│  ├─ /perception /understanding /vision-memory  │
│  └─ 模型: qwen-turbo(LLM) + Qwen3-TTS + VAD    │
└────────────────────────────────────────────────┘
```

---

## 三、启动测试目标

| 目标 | 说明 |
|---|---|
| T1 一键启动 | start.bat 单击 → WebUI 可访问 |
| T2 后端自动/手动拉起 | WebUI 启动后端 → :8000 就绪 |
| T3 健康判定 | UI 显示"已连接"（非误报） |
| T4 功能可用 | 对话 / TTS / 记忆 / 人格接口正常 |
| T5 异常恢复 | 后端意外退出 → 自动重启 |
| T6 多实例防护 | 端口冲突时自动释放/拒绝 |
| T7 优雅关闭 | shutdown 全停 + 端口释放 |
| T8 桌面伙伴壳 | frontend/main.py 一键启动元亨 |

---

## 四、测试环境与前置条件

```
操作系统: Windows 11 (x64)
解释器:   D:\Python311\python.exe (WebUI/后端)
          D:\YHLZ2.0\venv\Scripts\python.exe (测试/开发)
项目根:   D:\YHLZ2.0
依赖:     flask/fastapi/uvicorn/torch/transformers/edge-tts 等 (已安装)
模型:     qwen-turbo (API) / Qwen3-TTS-0.6B (本地) / SenseVoiceSmall (本地, 懒加载)
前置:     无正在运行的 YHLZ 服务 (端口 5000/8000 空闲)
```

---

## 五、测试用例设计

### 5.1 启动测试用例

| 用例 | 步骤 | 预期 | 优先级 |
|---|---|---|---|
| TC-01 环境检查 | `python -c "import flask, fastapi, uvicorn, torch"` | 全部成功 | P0 |
| TC-02 WebUI 启动 | 执行 `python webui_server.py` | 日志显示 :5000 运行 | P0 |
| TC-03 首页访问 | `GET http://127.0.0.1:5000/` | HTTP 200 | P0 |
| TC-04 健康状态 | `GET /api/health` | `status=ok` | P0 |
| TC-05 后端启动 | `POST /api/services/backend/start` | success:true | P0 |
| TC-06 后端就绪 | 轮询 `GET /api/status` (≤60s) | backend=running | P0 |
| TC-07 后端健康 | `GET :8000/health` | healthy, llm/tts/vad=true | P0 |
| TC-08 UI 判定 | 刷新页面看顶栏 | "已连接"(绿) 非"异常" | P0 |
| TC-09 对话功能 | `POST /api/chat {"message":"你好"}` | HTTP 200 SSE 流 | P0 |
| TC-10 流式对话 | `POST /api/chat/stream` | SSE 逐字返回 | P0 |
| TC-11 TTS 合成 | `POST :8000/synthesize {"text":"测试"}` | 音频数据返回 | P0 |
| TC-12 记忆接口 | `GET /api/memory/list` | HTTP 200 | P1 |
| TC-13 人格接口 | `GET /api/personality` | HTTP 200 | P1 |
| TC-14 声音列表 | `GET /api/voice/list` | HTTP 200 | P1 |
| TC-15 重复启动 | 再次 `POST /api/services/backend/start` | 返回"已在运行" | P1 |
| TC-16 端口冲突 | 占用 8000 后启动后端 | 识别已有服务, 不重复拉起 | P1 |
| TC-17 后端崩溃重启 | kill 后端进程 | wait_backend 自动重启 (≤3次) | P1 |
| TC-18 优雅关闭 | `POST /api/shutdown` | avatar→live2d→backend 顺序停止, 端口释放 | P1 |
| TC-19 重启恢复 | 关闭后重启 | 全新正常启动 | P1 |
| TC-20 桌面伙伴壳 | `python frontend/main.py` (GUI) | 元亨 ONLINE (一键启动) | P2 |
| TC-21 无 GUI 降级 | 无 PyQt5 环境运行 frontend/main.py | 启动检查 CLI 输出各步骤 | P2 |
| TC-22 长时间运行 | 启动后挂机 72h | 无崩溃, 日志无 ERROR 累积 | P2 |

### 5.2 关键测试命令

```powershell
# 端口检查
python -c "import socket; s=socket.socket(); print('busy' if s.connect_ex(('127.0.0.1',8000))==0 else 'free'); s.close()"

# WebUI 健康 (修复后判定)
python -c "import json,urllib.request; d=json.loads(urllib.request.urlopen('http://127.0.0.1:5000/api/health',timeout=5).read()); print('OK' if d.get('status')=='ok' else 'FAIL', d)"

# 后端健康
python -c "import json,urllib.request; d=json.loads(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5).read()); print(d.get('status'), d.get('model'), d.get('llm'), d.get('tts'))"

# 对话 (SSE)
python -c "import json,urllib.request; req=urllib.request.Request('http://127.0.0.1:5000/api/chat',data=json.dumps({'message':'你好','tts_enabled':False}).encode(),headers={'Content-Type':'application/json'}); r=urllib.request.urlopen(req,timeout=30); print(r.status, len(r.read()))"
```

---

## 六、测试执行流程

### 阶段 1：准备（5 分钟）

1. 确认端口 5000/8000 空闲（无残留进程）
2. 确认无多实例 webui_server 进程
3. 记录基线：`backend_stderr.log` / `backend_stdout.log` 当前大小

### 阶段 2：冷启动测试（TC-01 ~ TC-11，约 3 分钟）

1. 环境检查（TC-01）
2. 启动 WebUI（TC-02/03/04）
3. 触发后端启动（TC-05），轮询等待就绪（TC-06/07，30~50s）
4. 验证 UI 判定与核心功能（TC-08/09/10/11）

### 阶段 3：功能与边界测试（TC-12 ~ TC-19，约 10 分钟）

1. 辅助接口（TC-12/13/14）
2. 重复启动/端口冲突（TC-15/16）
3. 崩溃重启（TC-17：kill 后端进程，观察自动重启日志）
4. 优雅关闭与恢复（TC-18/19）

### 阶段 4：可选与长期（TC-20 ~ TC-22）

- 桌面伙伴壳（TC-20/21）：GUI 环境执行
- 长期运行（TC-22）：挂机 72h，每日检查

### 阶段 5：总结

1. 汇总测试记录（见 §九模板）
2. 判定 8 级验收标准（见 §七）
3. 输出测试报告

---

## 七、验收标准

### 7.1 启动验收（对照热机启动 Prompt）

| 级 | 标准 | 判定方式 |
|---|---|---|
| L1 | 一键启动（start.bat → WebUI 可访问） | TC-02/03 PASS |
| L2 | 后端自动拉起并就绪（≤60s） | TC-05/06 PASS |
| L3 | UI 健康判定正确（已连接非异常） | TC-08 PASS |
| L4 | 核心功能可用（对话/TTS） | TC-09/10/11 PASS |
| L5 | 崩溃自动恢复（≤3 次重启） | TC-17 PASS |
| L6 | 优雅关闭与端口释放 | TC-18 PASS |
| L7 | 无多实例/端口冲突 | TC-15/16 PASS |
| L8 | 72h 连续运行 Crash=0 | TC-22 PASS |

### 7.2 通过条件

```
P0 用例 (TC-01~11): 全部 PASS
P1 用例 (TC-12~19): ≥90% PASS (失败需说明原因并修复)
P2 用例 (TC-20~22): 记录结果 (不阻塞判定)
全部 PASS → YHLZ Warm Runtime Activated
存在 FAIL → Hotfix Cycle (Issue→Trace→分析→隔离→修复→回归)
```

---

## 八、异常处理与回滚

### 8.1 常见异常处置

| 异常 | 处置 |
|---|---|
| 端口被占用 | WebUI 自动 kill_port_process；仍失败则手动 `netstat -ano | findstr :5000` + taskkill |
| 后端启动失败 | 查看 `logs/backend_stderr.log`；确认模型路径/依赖 |
| 启动超时 60s | wait_backend 标记 stopped；检查模型加载耗时（首次 TTS 加载 20~40s 属正常） |
| 自动重启达 3 次 | 手动介入：查日志 → 修复 → 重启 |
| UI 仍显示异常 | 确认 /api/health 返回 status=ok；若后端重启过需等就绪 |
| ASR 首次慢 | 正常（懒加载），首次语音请求加载 SenseVoiceSmall |

### 8.2 回滚方案

```
本次修复涉及文件: webui_server.py（/api/health 归一化 + /api/chat SSE）
回滚: 还原 webui_server.py 至 2026-08-10 修复前版本 → 重启 WebUI
后端冻结接口: 未改动，无回滚需求
```

---

## 九、测试记录模板

```
日期: __________  测试人: __________  环境: __________

┌──────┬──────────┬──────────┬──────────┬──────────┐
│ 用例  │ 步骤结果  │ 预期      │ 实际      │ PASS/FAIL │
├──────┼──────────┼──────────┼──────────┼──────────┤
│ TC-01│          │          │          │          │
│ TC-02│          │          │          │          │
│ ...  │          │          │          │          │
└──────┴──────────┴──────────┴──────────┴──────────┘

异常记录:
  编号: ____ 用例: ____ 现象: ____ 原因: ____ 处置: ____

总结论:
  启动验收: PASS / FAIL
  备注: ____
```

---

**YHLZ · 元 · 亨 · 利 · 贞**
