# 工作 Agent 疑问答复与方案校准

**日期：2026-09-27**  
**对应文件：**`方案疑问/问题清单.md`  
**结论：**原方案里“新建 DialogueCoordinator”写得过于武断，容易重复现有职责。本答复按仓库现状校准：先复用 `SessionKernel + TargetVoiceChain + TargetVoiceRuntime`，不先新建第二个会话/协调核心。

---

## 1. 架构命名：以哪个为准？

**决定：不新建 `DialogueCoordinator` 作为第二个状态所有者。**

仓库已经有这几层：

- `SessionKernel`：session/turn 生命周期、状态、取消句柄、事件及 stale turn 管理，是 turn ownership 的核心；
- `TargetVoiceChain`（`backend/target_chain.py`）：串起一次 transcript → reasoner → TTS → playback，并负责取消/清理；
- `TargetVoiceRuntime`（`backend/target_runtime.py`）：管理 MediaAdapter、ASR、播放链的生命周期和运行事件；
- `ConversationSession`：对话历史、人格/记忆和 LLM 调用，不应再承担麦克风、播放器或全局 turn 状态管理。

**目标分工：**工作台只需要一个薄的 HTTP/SSE adapter，把请求接到已有 runtime/chain；不另造一套 Kernel。先检查现有对象能否被工作台复用，再决定最小的 adapter 改动。

## 2. Phase 2“预判式提交”是否做？

**决定：第一版不做，延后到稳定版本之后再单独评估。**

partial 只做字幕和 UI 状态，不触发 LLM、工具、记忆写入或音频生成。先做：

1. 流式显示 partial；
2. 根据 VAD/静音窗口形成 final；
3. final 一次性提交；
4. 回答播放期间能取消并接收下一轮。

原因：预判会消耗推理资源、产生错误分支、增加取消/隐私复杂度；而且目前还没有 trace 证明主要延迟来自“等用户说完”。等主链稳定并测出确实需要再做可关闭实验，不作为近期交付依赖。

## 3. AEC 用什么？8GB 显存够不够？

**决定：先不加新 AEC 依赖，不自研 RMS“伪 AEC”。先盘点并测试现有实现。**

仓库已有：

- `backend/media_adapter.py` 的 `AECPort`、render reference 输入和 AEC 状态证据；
- `backend/echo_cancellation.py` 的既有回声处理实现；
- `MediaAdapter` 在没有同步播放参考时会记录 AEC 不可用/未验证。

执行顺序：

1. 先戴耳机验证主链、插话、停止；
2. 外放测试时确认播放端 reference 与麦克风帧同步、采样率/延迟匹配；
3. 用固定“只有播放/播放中说话”的样本测回声残留和误触发；
4. 若现有实现不合格，再做小型 CPU PoC 比较 WebRTC Audio Processing（AEC3/APM）和 SpeexDSP，并确认 Windows/Python 绑定可维护后再选型。

AEC 属于音频 DSP，通常主要占 CPU，不是 8GB 显存问题；实际限制是 CPU 实时性、设备时钟/延迟、双工设备是否能提供同步 render reference，以及 Windows 原生依赖的可安装性。RMS 阈值只能用于 VAD/门控，不能当作回声消除。不要在没有 reference 的条件下宣称 AEC 已经工作。

## 4. Fast Path / Task Path 怎么自动判断？

**决定：第一阶段先不用额外 LLM 分类器，也不训练分类器。采用简单、可解释的路由，允许升级。**

- 默认普通聊天走 Fast Path：短上下文、简洁回答；不主动装载重型工具链；
- 明确要求执行动作/查资料/操作工具、涉及需要工具验证的事实，走 Task Path；
- 规则置信度不够或识别到写操作，宁可走 Task Path 或先向用户澄清，不要静默误走 Fast；
- 语音链的速度验收先以纯聊天场景为准；Task Path 不承诺同样首字延迟。

首版可用现有 UI 的“普通对话/任务”模式或轻量规则做显式分流。之后如果模型支持可控工具调用，再把工具调用作为升级到 Task Path 的信号；不要让 Fast Path 已经开始播答案后，再让另一个隐藏模型分类造成重复回答。

## 5. 延迟目标是硬要求吗？

**决定：当前是待基线验证的工程目标，不是上线硬门槛。**

先采集固定样本的 p50/p95，再看各阶段分布；之后把指标分三级：

- **测量目标**：希望达到的方向值；
- **阶段门槛**：本阶段必须满足的正确性/稳定性，如 final 只提交一次、取消后旧音频不再出声；
- **产品硬门槛**：真实麦克风测试后由用户确认，才冻结为发布要求。

如果 p50 未达目标但识别准确、轮次稳定，先记录瓶颈并按优先级优化；不能为了达标把端点静音窗口降到截断用户话语。正确性、可取消性先于延迟数字。

## 6. 这些文件能不能直接改？

**决定：先协调，不要直接覆盖正在被人格/记忆工作流修改的文件。**

当前工作区存在未提交改动，其中包括 `backend/target_daemon.py`、台账、人格/记忆相关代码和测试。对共享文件先做 diff/确认 owner，再拆成小 patch；不要 reset、整文件覆盖或顺手重排。语音链路改动优先放在独立 adapter/测试文件；确需改 `session_kernel.py`、`target_chain.py`、`target_runtime.py`、`target_entry.py` 时，先确认同一文件没有并行编辑，再一项一项提交和跑对应测试。

## 7. `dialogue_coordinator.py` 是新文件还是已有雏形？

**仓库中不存在 `backend/dialogue_coordinator.py`。**

但是已有 `SessionKernel`、`TargetVoiceChain`、`TargetVoiceRuntime`，足以覆盖方案中大部分“协调/生命周期”职责。因此本次校准结论是：先不创建该文件。若工作台 SSE 确实缺一个协议转换层，可以以后新建一个**无状态或薄 adapter**，只做事件映射，不持有第二份 turn 状态。

## 8. v8 训练与语音链路怎么排？

**决定：逻辑上并行、资源上错峰。**

- 云卡训练若确实在远端且不占本机资源，可以独立排队推进；
- 本机先做 Phase 0 的 trace、代码盘点、耳机模式输入/取消基线；这些不应被训练阻塞；
- 若训练/推理共享本机 GPU、显存或音频设备，则不要同时跑训练和实时语音压测；
- 不把 v8 训练完成当成语音链路开始的前置条件，语音链路也不替代人格回归。

## 9. 是不是今天就必须做完 Phase 0–1？

**不是。** “半天/1–2 天”是粗略工程量，不是对 2026-09-27 当天的承诺。按阶段门推进：

1. 先完成 Phase 0 盘点和 trace；
2. 评审数据后，选最小改动接工作台；
3. 输入、文字回答、TTS、插话分别验收；
4. 一阶段不通过就停在该阶段修复，不跳到端到端/训练。

## 10. “外接实时语音 Provider”具体是什么？

它是一个**架构接口类别**，不是已选供应商或既定模型，可能包括：

- 云端实时语音 API；
- 本地支持流式音频输入与增量语音输出的模型/服务。

目前不指定候选、不接入、不默认上传音频。先确认现有 audio-direct 是否真的是分帧输入/增量输出（而不是整段 WAV 一次提交），然后再按隐私、网络、费用、取消能力、中文效果、首包延迟和 20 轮稳定性做 A/B。未经单独批准，不将麦克风音频发送到云端。

---

## 给工作 Agent 的可执行边界

**现在可做：**

1. 只读盘点现有 `/voice` 到目标 runtime/chain 的接线与测试；
2. 对现有语音链运行不改变人格/记忆数据的基线测试；
3. 设计 trace 字段与测试用例；
4. 若要改共享文件，先汇报文件、现有未提交改动冲突和最小 patch，再协调。

**暂不做：**

- 新建第二个 turn owner / `DialogueCoordinator`；
- partial 预判式 LLM 提交；
- 引入未经验证的 AEC 依赖；
- 上传音频到云端；
- 训练新模型或改人格/记忆链；
- 直接替换默认 `/voice` 或删除旧路径。

**决策记录：**沿用 `SessionKernel → TargetVoiceChain → TargetVoiceRuntime` 的既有分层；`ConversationSession` 保持对话/记忆职责。工作台接入前先完成代码和测试盘点。

---

### 技术依据（AEC 选型阶段再核验兼容性）

- WebRTC 官方源码将 Audio Processing Module 作为音频处理组件，包含回声消除等处理能力；
- Speex 官方手册提供 acoustic echo cancellation API；
- 这两者的存在不代表当前 Windows 环境已有兼容、可维护的 Python binding，必须做本机 PoC。
