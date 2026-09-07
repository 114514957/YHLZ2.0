# CX-O 研究存档：记忆 / 进化 / 梦境（2026-09-07）

> 来源：github.com/nbllt666/CX-O（二次元 AI 陪伴系统，200 commits；clone 于
> C:\Users\ACE_WAN——PROJECT\参考研究\CX-O，浅克隆只读）。只存档借鉴思路，
> 不部署不照搬（其硬件要求 NVIDIA≥16GB；本机 RTX 4060 8GB 跑不全套）。

## 一、记忆系统做法

- **分层**：SQLite 一张 memories 表按 type 分型（short_term/long_term/permanent/dream/conversation_summary）+独立 permanent_memories 表（importance_score 恒 1.0、零衰减、主模型可写副模型不可删）。
- **向量检索**：Embedding 三选一（Ollama nomic-embed-text 768d / sentence-transformers / vLLM bge-m3）+ Weaviate per-agent collection；写经 VectorizationQueue 异步入；召回 HybridSearch=向量 0.6 + 关键词 LIKE 0.4 融合，MemoryRouter 再按"重要性/时间/相关性"×场景权重 top-N 注入 prompt，向量失败降级 LIKE。
- **知识图谱**：LLM 提实体（正则回退），md5(name:type) 节点、related_to 边带 evidence_memory_ids 回链；独立 lazy 模块默认关。
- **衰减/蒸馏/归档**：双阶段指数衰减（permanent 豁免、召回再激活加成，24h 快照分批回写）；DistillationService 9 状态机+quality<0.3 拒收+**human override 审批**（AI 初筛→人批的模板）；AdvancedArchiver 5 级归档/智能合并软删保主+审计。
- **可借鉴**：①三级加权路由（向量+关键词+近端，permanent 直通）②"AI 初筛→人审批"状态机（含 rejected 留痕）③写读解耦+全链路降级 ④软删→归档→衰减→合并全审计+人格保护 ⑤异步批处理细节。

## 二、进化实验室（CXO-Tuner，:8310 独立服务）与自主生命

- **进化**：独立 FastAPI 微服务，输入 FeedbackIn{prompt/chosen/rejected/source(live_danmaku|judge|distillation)}→质量分过滤→指纹去重→DPO 数据集(SQLite)；另有 LLM-as-a-Judge 生成 chosen/rejected。**离线闲时学习**：60s tick 后台线程，仅当 ①样本≥100 ②低峰窗 02-05 点 ③当日未训练 才触发 QLoRA+DPO 训练；产物 LoRA 落盘，apply 走"记录应用意图"Phase1（真闭环待 vLLM lora_request 按场景路由）。
- **自主生命**：AutonomyEngine 后台主循环（15min/轮）五层流水线=感知(RSS/热点/记忆)→动机(四维 curiosity/social/creative/fatigue 按流逝 tick)→LLM 规划(9 项 action 白名单)→执行(发帖前内容闸门 fail-closed)→审计(audit_logs+Token 预算熔断+效果评估)。**离开模式**=在线休眠/离开放权；写日记=02:00 且当日未写才写（第一人称 200 字入长程记忆 #日记#经历 permanent）。
- **可借鉴**：①学习闭环旁路化（独立服务+开关+失败不冒泡）②隐式反馈只取强信号（时间窗+情感爆发阈值+去重+质量过滤）③低峰窗口+最小样本+每日幂等+job 落盘续接 ④权限白名单+内容闸门+Token 预算熔断+全审计=天然"人确认可扩展" ⑤"离开模式"轮询感知切权限档。

## 三、梦境引擎（server/autonomy/dream/）

- **流程**：昼夜循环 CircadianScheduler+SleepSensor(9 路信号融合，S4"睡了/困了"可短路)→**入睡前先自动日间摘要**（真实一天先沉淀再造梦）→ DreamMaterialCollector 采近 7 天边缘记忆+图谱孤立节点→ summary 模型低温(0.9)提示词联想 3 条候选→ **D7 确定性闸门**（拦事实断言/触碰 permanent/低清醒度）→ 进独立 DreamBuffer（不直写主库，TTL 72h）→ 醒来按 surface_probability(0.5)+每日上限 1 主动推 `dream.surface` → `POST /dream/{id}/confirm|reject`。
- **确认语义（关键）**：confirm=写 type='dream' 入主库（**is_ground_truth=False**、pending）→ 提级 confirmed（importance→0.4、衰减放缓）——**固化≠变事实**，仅权重+减缓遗忘；提级失败保持待审可重试。reject=缓冲标记+30 天审计后清，不写主库。任意用户文本"在吗/醒醒/早安"→ wake_up() 可打断。
- **可借鉴**：①确认≠写死事实（确认=加权+放缓遗忘；证伪/否决=软删留审计；二者状态独立）②双阶段写入+可重试（pending→提级，不谎报成功）③LLM 输出先过确定性闸门前置过滤 ④候选隔离缓冲+TTL+低分自动清 ⑤**打扰分层**：入睡用 fail-open 轻量仲裁（不打扰），醒后沉淀才用人工逐条确认。

## 结论与映射（对 YHLZ/元亨）
- 记忆：YHLZ 已有 L1/L2/L3+kw+审批 = CX-O 精简版；可渐进借鉴=向量召回(hybrid)、rejected 留痕、人格保护段。
- 进化/自主：YHLZ 已有信号采集+建议制+自主时刻 = 同理念轻量版；CX-O 用真 QLoRA 训练=元亨不训练参数（0196 结论），其"旁路化/低峰幂等/审计"可借鉴。
- 梦境：纯借鉴形态——给元亨加"梦境引擎"（边缘记忆→联想梦→醒来讲→老爹确认才沉淀=与现有 approve 文化天然契合；确认=weighted 非事实化）。
