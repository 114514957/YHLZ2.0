# YHLZ 工作台 · 桌面虚拟形象 + WebUI 控制端协同设计 v2（0221）

> 状态：设计稿（未开工）。在 v1（docs/YHLZ_WebUI控制台_设计_v1.md）之上，按用户要求扩展为"NEKO 式桌面部署 + WebUI 控制端"双形态协同。NEKO 依据=项目内研究报告+README(仓库 Project-N-E-K-O/N.E.K.O)。

## A. 双形态总览（协同同一 daemon）
```
┌─ WebUI 控制端（浏览器, full）─────────────────────────────┐
│ 设置/功能控制 | 后台监控 | 日志 | 台账查询 | 各链路设置    │
└───────────────▲──────────────────────────────────────────┘
                │ WS + REST (daemon 8321 扩展)
┌ YHLZ Core (daemon: ConversationSession/工具/记忆/计划/调度)
│ VoiceDialogRuntime(采集线程 48k→RNNoise→16k→SenseVoice)
│ ModelScheduler(8G 显存排他: ASR/LLM/TTS 顺序释放, 0219 实证)
│ AvatarService(状态→形象事件: state/delta/audio_done/emotion)
└──────▲───────────────────────────────────────────────────┘
┌ 桌面形象部署（无边框 viewer）──────────────────────────────┐
│ Live2D(本地模型或下载物象资产) 口型/表情/动作/subtitle     │
└──────────────────────────────────────────────────────────┘
```
原则（沿用 v1 + NEKO）：后端直采音频；核心逻辑不重复；桌面形象只是"表现层"，订阅后端事件；WebUI 才是控制/设置/观察真身。

## B. WebUI 控制端（五区细化）
1. **设置（各链路设置）** `POST /console/settings` 热生效（写 `data/console.json`）：
   - 采集：设备 index、48k/16k、cap gain
   - 前端：RNNoise on/off、VAD 阈值、断句静默时长(默认3s)
   - ASR：引擎(SenseVoice/sherpa)、加载时机
   - LLM：8081 地址、reasoning_effort(none/auto/work)、模型
   - TTS：引擎(Qwen3-TTS/edge)、音色(speaker 列表来自模型)、语速/instruct、播放设备
   - 语音：聆听模式(按键/常开)、barge-in 开关、声纹门(默认关)
2. **功能控制**：文本对话、语音键+打断、暂停聆听、重启某链路(释放/重载模型)、一键释放显存、计划 CRUD 快捷、新会话/存档
3. **后台监控**：服务灯(8081/8321/ollama/TTS/ASR)、VRAM 占用与调度状态、每轮延迟(TTFT/ASR/TTS)、VAD 电平条、轮次计数、错误计数、模型驻留当前者
4. **日志**：滚动(级别可筛)+关键字/导出；来源 daemon 统一 logger 缓冲
5. **台账查询**：ledger_search 前端输入+结果(记录号/时间/标签着色)、memory 检索、persona/认知根基浏览（≈NEKO memory_browser，只读+经审批写）

## C. 桌面虚拟形象（NEKO 借鉴落点）
- **载体**：本地 HTML viewer（Live2D cubism JS）+ 无边框窗口（首期浏览器整屏模式；Electron 壳列入里程碑 M5 可选）。
- **事件订阅**（同 daemon WS，仅形象用）：
  - `{type:"state"}` 阶段灯(听/想/说)
  - `{type:"delta"}` 文字
  - `{type:"audio_done"}` ← Qwen3-TTS 结束哨兵=口型复位权威（NEKO 借鉴1：被打断不发）
  - `{type:"emotion"}` 外显五分类→表情（预留双通道：内隐用户情绪→收敛打扰，M5）
- **口型**：`mouthOpen=min(1,rms*8)`→ParamMouthOpenY；lipsync 覆盖阈值；音频来源=后端 TTS 同时推 16k pcm ws(口型由后端推 RMS 事件更省=建议后端算 RMS→`{type:"vad",level}`，前端只映射参数=无需浏览器解码)
- **表情/动作**：playExpression+随机 motion+差分淡出(零跳变)（借鉴2）；静止 30fps 治理
- **叠加层**：subtitle 字幕、toast 通知、return-ball 收纳（NEKO 同名）
- **形象资产**：本地 `下载物象/*_vts` Live2D(VTS 包) 或下载物象已含模型；放 `assets/live2d/`

## D. 新增接口（草案）
- REST：`GET/POST /console/settings`、`POST /console/control {action: reload_asr|release_vram|...}`、`GET /console/monitor`、`GET /console/logs?level=&q=`、`GET /console/ledger?q=`（包装 ledger_search）、`GET /avatar/state`
- WS 增 avatar 事件流（与 /webui/ws 可同通道分 topic）
- 复用：/turn、/v1/chat/completions、/tool/schedule、/notifications、run_turn auto（闲聊去工具/工作思考=0216 语义保留）

## E. 里程碑（全部未开工）
- M1 控制端壳+WS+状态灯+文本对话流式
- M2 语音接入(VoiceDialogRuntime+ModelScheduler)+功能控制键
- M3 监控/日志/台账查询页
- M4 各链路设置热生效 + 审批流
- M5 桌面形象 viewer(口型/表情/字幕/toast) + 可选 Electron 壳 + 情绪双通道

## F. 边界
- 仅 127.0.0.1；写操作审批；日志脱敏；QQ 多渠道挂起不纳入（沿用 v1/0220）。
