# YHLZ 2.0 前端模块白皮书

> 版本：V1.0 | 日期：2026-08-09
> 覆盖：WebUI 服务 / 前端页面 / Live2D 桌宠 / 启动与运维链
> 关联：热机阶段（V10 Warm Runtime）前端现状基线

---

## 目录

1. [概述](#1-概述)
2. [总体架构](#2-总体架构)
3. [模块一：WebUI 服务（webui_server.py）](#3-模块一webui-服务webui_serverpy)
4. [模块二：前端页面（webui_templates/index.html）](#4-模块二前端页面webui_templatesindexhtml)
5. [模块三：Live2D 渲染与桌宠](#5-模块三live2d-渲染与桌宠)
6. [模块四：启动与运维链](#6-模块四启动与运维链)
7. [后端 API 全景（前端消费面）](#7-后端-api-全景前端消费面)
8. [数据流与关键机制](#8-数据流与关键机制)
9. [安全与权限](#9-安全与权限)
10. [日志与监控](#10-日志与监控)
11. [已知限制与风险](#11-已知限制与风险)
12. [热机运行建议](#12-热机运行建议)
13. [后续演进规划](#13-后续演进规划)

---

## 1. 概述

YHLZ 2.0 前端模块承担**人与 AI 伙伴之间的全部可视化交互入口**，由三层组成：

| 层 | 载体 | 端口 | 技术栈 |
|---|---|---|---|
| WebUI 控制台 | `webui_server.py` + `index.html` | 5000 | Flask + HTML/JS |
| 后端 API | `backend/main.py` | 8000 | FastAPI |
| Live2D 桌宠 | `live2d_desktop_avatar.py` 等 | 8081 / 18765 | PyQt5 + QWebEngine |

启动入口：`start.bat` 单击启动（惯例），自动拉起 WebUI 并打开浏览器。

### 现状基线

```
webui_server.py          1546 行   Flask 服务 + 服务编排 + 50+ 代理 API
index.html               ~14 万字符 单页控制台 (21 功能页)
live2d_desktop_avatar.py 1451 行   PyQt5 + WebEngine 主桌宠 (QWebEngineView)
live2d_pygame_avatar.py   788 行   Pygame 渲染版桌宠
live2d_qt_avatar.py      1094 行   QOpenGLWidget 渲染版桌宠
live2d_renderer.py        495 行   Live2D 渲染核心 (口型/表情/视线/动作)
desktop_avatar_py.py      567 行   QOpenGLWidget + WS 精简桌宠
backend/main.py          3816 行   FastAPI 121 路由
```

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────┐
│                    用户 (浏览器 / 桌面)                   │
└──────────────┬──────────────────────────┬───────────────┘
               │ HTTP :5000              │ 桌面窗口
┌──────────────▼──────────────────────────▼───────────────┐
│               WebUI 层 (交互入口)                        │
│  webui_server.py (Flask 编排 + 代理)                    │
│  webui_templates/index.html (单页控制台)                │
│  webui_static/ (静态资源, 当前空)                       │
│  gui_config.json / webui_config.json (配置)             │
└──────────────┬──────────────────────────┬───────────────┘
               │ 代理 :8000              │ WS 控制
┌──────────────▼──────────────────────────▼───────────────┐
│               Live2D 桌宠层                              │
│  live2d_desktop_avatar.py  (PyQt5 主桌宠)               │
│  live2d_renderer.py         (渲染核心)                  │
│  live2d_pygame_avatar.py / live2d_qt_avatar.py          │
│  desktop_avatar_py.py       (精简版)                    │
└──────────────┬──────────────────────────────────────────┘
               │ HTTP :8000 / WebSocket
┌──────────────▼──────────────────────────────────────────┐
│               Backend API 层 (backend/main.py)          │
│  /chat /transcribe /synthesize /voice/* /live2d/*       │
│  /memory /personality /perception /vision-memory        │
│  /agent /action /understanding /modules                 │
└──────────────────────────────────────────────────────────┘
```

**关键特性**：WebUI 是**编排 + 代理**（不直接持有业务逻辑），全部业务经 `:8000` 后端；桌宠经 WebSocket 接收口型/情绪/说话状态实时驱动。

---

## 3. 模块一：WebUI 服务（webui_server.py）

### 3.1 角色

- **服务编排器**：管理 backend/live2d/avatar/asr/tts 子服务启停
- **API 代理**：50+ 路由将前端请求转发 `:8000`
- **系统运维**：日志/配置/系统信息/基准测试

### 3.2 服务状态模型

```python
services_status = {
    "webui":  {status, port: 5000},          # 自身
    "backend":{status, port: 8000},          # 端口探测
    "live2d": {status, port: 8081},          # 进程探测
    "asr":    {status},                      # 标志位
    "tts":    {status},
    "voice_chat": {status},                  # asr 且 tts
    "avatar": {status, pid},
}
```

探测策略：端口服务用 `is_port_in_use()`，进程服务用 `poll()`，线程内服务用布尔标志。

### 3.3 路由全景（50+）

| 类别 | 路由 | 说明 |
|---|---|---|
| 页面 | `/` | 渲染 index.html |
| 状态 | `/api/status` `/api/health` `/api/system/info` | 服务/健康/系统信息（CPU/内存/磁盘/GPU via nvidia-smi） |
| 服务编排 | `/api/services/<name>/start/stop/restart` `/api/services/start_all/stop_all` | 子服务生命周期 |
| 聊天 | `/api/chat` `/api/chat/stream` | 对话 + SSE 流式 |
| 语音克隆 | `/api/voice/clone` `/api/voice/clone/batch` | multipart 转发 + 批量克隆 |
| 语音合成 | `/api/voice/synthesize` `/api/tts/synthesize` | 双入口 |
| 语音管理 | `/api/voice/list` `/api/voice/<id>`(GET/DELETE) `/api/voice/uploads/cleanup` | 列表/详情/软删/清理 |
| 语音质量 | `/api/voice/quality/evaluate` | 质量门禁代理 |
| 语音审计 | `/api/voice/audit/log|count|permission` | 审计代理 |
| 语音适配器 | `/api/voice/adapters/dashboard` | 适配器总览 |
| 去重 | `/api/voice/duplicate/check` | 重复检测 |
| 记忆 | `/api/memory/list|add|delete` `/api/memory/stats` | 记忆管理 |
| 人格 | `/api/personality`(GET/POST) | 角色设定 |
| 工具 | `/api/tools/list` `/api/tools/call` | 工具注册/调用 |
| 视觉 | `/api/vision/<endpoint>` | 视觉代理 |
| Live2D | `/api/live2d/<endpoint>` | 桌宠控制代理 |
| 桌宠 | `/api/avatar/start|stop|status|control|open_live2d` | 虚拟形象（含 Win32 窗口控制） |
| 语音链路 | `/api/asr/transcribe` | 识别代理 |
| 基准 | `/api/benchmark/pcm` | PCM 延迟测试（llm/tts_first/tts_last/total/all） |
| 技术比对 | `/api/tech/comparison` | 技术分析报告 |
| 日志 | `/api/logs` `/api/logs/backend` `/api/logs/clear` | 双日志 |
| 配置 | `/api/config` `/api/config/save` | webui_config.json 读写 |
| 系统 | `/api/shutdown` | 全服务关闭 |

### 3.4 关键实现细节

- **UTF-8 强制**：`PYTHONIOENCODING/PYTHONUTF8` + stdout/stderr reconfigure（防 Windows 中文乱码）
- **CORS 全开**：`CORS(app)`（内网单机场景）
- **SSE 流式**：`/api/chat/stream` 用生成器逐行转发 `text/event-stream`
- **端口冲突处理**：启动前 `is_port_in_use` → `kill_port_process`（psutil 终结）
- **优雅退出**：SIGINT/SIGTERM + atexit → `cleanup_on_exit()`（按序终止 avatar→backend→live2d→释放 5000/8000/8081 → 存配置）
- **自动开浏览器**：`WEBUI_AUTO_OPEN` 环境变量控制

### 3.5 配置文件

| 文件 | 用途 |
|---|---|
| `webui_config.json` | 前端设置（settings/last_updated），`/api/config/save` 写入 |
| `gui_config.json` | GUI 状态（当前 `{"last_module": "tools"}`） |
| `logs/webui_YYYYMMDD.log` | 按日滚动日志 |

---

## 4. 模块二：前端页面（webui_templates/index.html）

### 4.1 形态

单页控制台（约 14 万字符），侧边栏导航 + 21 个功能页，全部原生 HTML/JS + fetch。

### 4.2 页面清单（21 功能页）

| 页面 | ID | 功能 |
|---|---|---|
| 服务总览 | `page-service` | 服务卡片/端口/主机/日志级别/自重启/GPU 直连配置 |
| ASR | `page-asr` | 模型/模式/语言/降噪/VAD 阈值/热词/置信度 |
| TTS | `page-tts` | 引擎/语言/音色/情绪/语速/音量/音调 |
| 声音克隆 | `page-voice_clone` | 音频上传/命名/引擎/克隆/合成测试 |
| 声音管理 | `page-voice_manage` | 音色表格/播放/管理 |
| 声音质量 | `page-voice_quality` | 参考/合成对比评估 |
| 适配器总览 | `page-adapter_dashboard` | 适配器状态表 |
| 批量克隆 | `page-voice_batch` | 批量任务/进度/详情 |
| 声音去重 | `page-voice_dedup` | 文件/阈值/特征去重 |
| 声音审计 | `page-voice_audit` | 审计日志/权限查询 |
| LLM | `page-llm` | Provider/模型/Key/温度/Token/上下文/采样 |
| GPU | `page-gpu` | GPU 信息/直连模式/轮询 |
| 记忆 | `page-memory` | 统计/搜索/过滤/表格/增删/优先级 |
| 人格 | `page-personality` | 模板/自定义/名称/性别/年龄/语气 |
| 视觉 | `page-vision` | 摄像头/屏幕采集/OCR/检测/分析/目标计数 |
| 桌宠 | `page-avatar` | Live2D 状态/模型/情绪/动作/大小/口型/注视/屏幕位置 |
| 文本对话 | `page-text_chat` | 聊天窗/流式输出 |
| 语音对话 | `page-voice_chat` | 语音聊天（TTS 开关/语速/音色） |
| 工具 | `page-tools` | 工具列表/参数/调用/结果 |
| 日志 | `page-logs` | WebUI 日志 + 后端日志双面板/自动滚动 |
| 系统 | `page-system` | OS/Python/CPU/内存/磁盘/GPU/基准测试 |
| 关于 | `page-about` | 版本信息 |

### 4.3 前端-后端调用模式

```
页面 JS → fetch('/api/xxx') → webui_server 代理 → backend :8000 → 响应回填
流式聊天: fetch('/api/chat/stream') → ReadableStream 解析 SSE 行
```

---

## 5. 模块三：Live2D 渲染与桌宠

### 5.1 渲染核心（live2d_renderer.py）

| 组件 | 职责 |
|---|---|
| `MouthSync` | 口型同步（RMS 音量 → 开口度，平滑/释放） |
| `ParamTween` | 参数补间动画 |
| `ExpressionManager` | 表情状态（快照基线/设置/更新） |
| `GazeManager` | 视线追踪（状态/目标/补间） |
| `Live2DRenderer` | 模型加载/GL 初始化/渲染帧/口型/表情/动作/命中测试 |

### 5.2 桌宠实现（4 版本并存）

| 文件 | 技术 | 特性 |
|---|---|---|
| `live2d_desktop_avatar.py` | PyQt5 + QWebEngineView | **主桌宠**：WebChannel 桥、WS 客户端（重连/心跳）、ServiceManager（backend/vision/audio/bilibili 子服务）、FaceTracker（人脸追踪线程）、设置对话框、托盘图标、右键菜单、聊天 |
| `live2d_pygame_avatar.py` | Pygame | 轻量：WS 口型/情绪驱动、透明窗口、右键菜单、缩放/复位 |
| `live2d_qt_avatar.py` | PyQt5 + QOpenGLWidget | 原生 GL 渲染：气泡菜单、聊天窗、语音录制线程（VAD）、键盘轮询 |
| `desktop_avatar_py.py` | PyQt5 + QOpenGLWidget + WS | 精简：模型加载/位置保存恢复/托盘 |

### 5.3 实时驱动链路

```
后端 (TTS 播放/情绪) → WebSocket (mouth_open / emotion / is_speaking)
    → AvatarWSClient → 渲染器 set_mouth_open / set_emotion / set_speaking
```

- WS 消息：口型值、情绪名+强度、说话开始/结束、视线数据、模型/动作事件
- 心跳：`_send_ping` 定时保活；断线指数退避重连
- 表情/动作/口型参数全部经参数补间平滑过渡

### 5.4 控制 API（后端侧，供 WebUI 代理）

```
/live2d/load /action /emotion /emotion-intensity /mouth-open
/live2d/glow-color /models /status
```

---

## 6. 模块四：启动与运维链

### 6.1 启动链（start.bat）

```
start.bat (chcp 65001)
  ├─ 检查 Python / 依赖 (flask, PyQt5 自动安装)
  ├─ 创建 logs / webui_templates / webui_static
  ├─ 追加 ffmpeg 到 PATH (若存在)
  ├─ 打开浏览器 http://127.0.0.1:5000
  └─ python webui_server.py  (单进程前台)
```

### 6.2 服务生命周期（webui_server 编排）

```
启动: /api/services/<name>/start   → subprocess 拉起
停止: /api/services/<name>/stop    → terminate → kill(超时 5s)
重启: restart                      → stop + sleep(1) + start
全停: /api/shutdown                → avatar→live2d→backend → 释放端口 → 存配置 → os._exit
```

### 6.3 端口约定

| 端口 | 服务 |
|---|---|
| 5000 | WebUI |
| 8000 | Backend API |
| 8081 | Live2D（服务模式） |
| 18765 | 桌宠内嵌 Live2D 查看器（优先） |

---

## 7. 后端 API 全景（前端消费面）

`backend/main.py`（FastAPI，121 唯一路由）按域分组：

| 域 | 路由数 | 代表 |
|---|---|---|
| 语音链路 | 8 | /chat /transcribe /synthesize /interrupt /clear-history /websocket-stats |
| 声音克隆/身份 | 21 | /voice/clone /voice/list /voice/quality/evaluate /voice/audit/* /voice/duplicate/check |
| Live2D 控制 | 9 | /live2d/* |
| 记忆 | 5 | /memory /memory/search /memory/list /memory/{id} |
| Agent | 10 | /agent/chat /agent/plan /agent/tools /agent/memory |
| 感知 | 11 | /perception/ocr /perception/detect /perception/screen/* |
| 理解 | 9 | /understanding/describe /understanding/qa /understanding/screen/* |
| 视觉记忆 | 12 | /vision-memory/* |
| 人格 | 11 | /personality/profiles /personality/style /personality/assess |
| 行动 | 7 | /action/request /action/status /action/cancel |
| VAD | 3 | /vad/config /vad/detect /vad/interrupt |
| 模块管理 | 3 | /modules/status /modules/start /modules/stop |
| 同步 | 2 | /sync/status /sync/events |
| 系统 | 10 | /health /metrics /voice/metrics /voice/security/check /voice/dashboard |

---

## 8. 数据流与关键机制

### 8.1 文本对话

```
浏览器 → /api/chat (或 /api/chat/stream SSE)
  → webui_server 代理 → backend /chat
    → LLM 生成 → (可选 TTS) → 响应回填
```

### 8.2 声音克隆

```
浏览器上传音频 → /api/voice/clone (multipart)
  → backend /voice/clone (质量门禁/去重/注册)
  → 结果回填 (含 stage 校验/错误分级)
批量: /api/voice/clone/batch → 任务队列 → 轮询进度/取消
```

### 8.3 桌宠实时

```
后端说话 → WS 推送 mouth_open/emotion/is_speaking
  → 桌宠渲染器 → 口型同步 + 表情 + 视线 平滑动画
用户点击 → 右键菜单/聊天窗 → /api/chat → TTS → 桌宠说话
```

### 8.4 服务状态轮询

前端定时 `/api/status` → webui 探测端口/进程/标志 → 回填状态徽章。

---

## 9. 安全与权限

| 项 | 现状 | 说明 |
|---|---|---|
| CORS | 全开 | 内网单机场景；外网暴露需收紧 |
| 认证 | 无 | 无登录/Token；局域网暴露有风险 |
| API Key | 前端可读写 `page-llm` | Key 经 config 保存于 `webui_config.json`（明文），需评估 |
| 后端权限 | 感知/视觉/行动默认拒绝 | backend 层权限模型保持（perception/permission 等） |
| 端口暴露 | 默认 127.0.0.1 | `WEBUI_HOST` 可改；外网需反向代理 + 认证 |

**热机建议**：保持 127.0.0.1 默认绑定；若需外网，前置认证网关。

---

## 10. 日志与监控

| 日志 | 位置 |
|---|---|
| WebUI 日志 | `logs/webui_YYYYMMDD.log`（按日滚动，FileHandler+Stream） |
| 后端日志 | `logs/backend_stdout.log` / `backend_stderr.log` |
| 集成日志 | `logs/phase3_integration_test.log` |

监控入口：
- `/api/status`（服务健康）
- `/api/system/info`（CPU/内存/磁盘/GPU）
- `/api/benchmark/pcm`（LLM/TTS 首字/总往返延迟）
- `/api/logs` `/api/logs/backend`（双日志查看）

---

## 11. 已知限制与风险

| # | 限制/风险 | 影响 | 建议 |
|---|---|---|---|
| 1 | 无认证/无鉴权 | 局域网可任意调用 | 外网场景加网关 |
| 2 | API Key 明文存 config | 泄露风险 | 加密或环境变量 |
| 3 | 桌宠 4 版本并存 | 维护成本 | 明确主版本（QWebEngineView），其余归档 |
| 4 | 全部入口文件为 stub | 不可直接使用 | 由 webui_server/桌宠主入口替代 |
| 5 | webui_static 为空 | 静态资源无落地 | 按需填充或删除 |
| 6 | CORS 全开 | 跨域滥用 | 收敛白名单 |
| 7 | 单进程前台运行 | 崩溃即停 | 热机阶段建议守护/自重启 |
| 8 | 无前端测试 | 回归风险 | 补 smoke 测试 |

---

## 12. 热机运行建议

对照《YHLZ V10 Warm Runtime Operation Prompt》（观察/记录/验证/优化）：

1. **每日 Runtime Report**：`/api/status` + `/api/system/info` + `/api/benchmark/pcm` 采集基线
2. **前端稳定性**：观察 WebUI 长驻内存、SSE 连接泄漏、WS 断线重连率
3. **桌宠守护**：`cleanup_on_exit` 已验证；建议 systemd/计划任务守护
4. **日志留存**：按日滚动已具备；定期归档压缩
5. **安全边界**：保持 127.0.0.1；`gui_config.json`/`webui_config.json` 纳入备份
6. **变更可追踪**：前端配置变更经 `/api/config/save` 留痕（last_updated）

---

## 13. 后续演进规划

| 阶段 | 方向 | 说明 |
|---|---|---|
| V10.1+ | 前端 smoke 测试 | 端口/页面/核心代理自动化 |
| V10.2+ | 认证收敛 | 本地 Token / CORS 白名单 |
| V10.5 | 多模态体验 | Text/Vision/Audio/Action 统一 Experience Object 前端展示 |
| 远期 | 桌宠版本收敛 | 主桌宠 QWebEngineView 主线化，其余归档 |
| 远期 | 静态资源规范化 | webui_static 落地 CDN 化 |

---

## 附录 A：文件清单

| 文件 | 行数/大小 | 角色 |
|---|---|---|
| `webui_server.py` | 1546 | WebUI 服务（编排+代理+运维） |
| `webui_templates/index.html` | ~140K | 单页控制台（21 页） |
| `webui_static/` | 空 | 静态资源目录 |
| `live2d_renderer.py` | 495 | Live2D 渲染核心 |
| `live2d_desktop_avatar.py` | 1451 | 主桌宠（PyQt5+WebEngine） |
| `live2d_pygame_avatar.py` | 788 | Pygame 桌宠 |
| `live2d_qt_avatar.py` | 1094 | QOpenGL 桌宠 |
| `desktop_avatar_py.py` | 567 | 精简桌宠 |
| `live2d_desktop_avatar` 相关 stub | 10 | 占位入口（desktop_avatar*.py 等） |
| `start.bat` | — | 单击启动 |
| `gui_config.json` | 24B | GUI 状态 |
| `webui_config.json` | — | WebUI 设置 |
| `backend/main.py` | 3816 | 后端 API（121 路由） |

---

**YHLZ · 元 · 亨 · 利 · 贞**
