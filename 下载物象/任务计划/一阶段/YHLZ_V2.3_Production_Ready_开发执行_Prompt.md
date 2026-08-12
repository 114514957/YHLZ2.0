# YHLZ Voice Identity System V2.3

# Production Ready 开发执行 Prompt

## 版本目标

基于 YHLZ Voice Identity System V2.2，进入 V2.3 Production Ready。

核心目标：

1.  完成 Qwen3 / GPT-SoVITS Real Adapter 真实运行验证
2.  完成生产级任务持久化
3.  完成权限体系接入
4.  完成声音生命周期管理
5.  完成端到端 Voice Clone 产品闭环

------------------------------------------------------------------------

# Phase 1 Real Adapter Production Validation

## Qwen3 Real Adapter

新增：

tests/manual/test_qwen3_real.py

验证：

-   模型加载
-   GPU检测
-   voice prepare
-   cache生成
-   文本合成
-   输出wav

输出：

Qwen3_REAL_TEST_REPORT.md

## GPT-SoVITS Real Adapter

新增：

tests/manual/test_gpt_sovits_real.py

验证：

-   Gradio连接
-   reference audio上传
-   speaker embedding生成
-   TTS生成
-   返回wav

要求：

timeout retry health_check

------------------------------------------------------------------------

# Phase 2 生产任务系统

当前 TaskQueue 为内存队列。

升级：

SQLite Task Storage

新增：

backend/voice_identity/batch/task_store.py

数据表：

voice_clone_tasks

字段：

id task_id status owner created_at updated_at progress result error

要求：

-   服务重启任务恢复
-   状态恢复
-   失败重试

------------------------------------------------------------------------

# Phase 3 权限系统接入

新增：

permission.py

权限：

read write delete synthesize

接入：

POST /voice/clone

DELETE /voice/{id}

POST /voice/batch

POST /voice/quality/evaluate

失败：

403 permission denied

------------------------------------------------------------------------

# Phase 4 Voice Lifecycle Management

新增：

voice_lifecycle.py

生命周期：

created ready active inactive archived deleted

新增：

archive_voice() restore_voice() cleanup_unused_voice()

规则：

90天未使用 -\> inactive

180天 -\> archive

------------------------------------------------------------------------

# Phase 5 自动质量门禁

Clone Pipeline 集成：

clone → quality check → score

规则：

score \>= 0.75 : READY

0.5\~0.75 : WARNING

\<0.5 : REJECT

新增：

CloneResult:

-   quality_report
-   quality_status

禁止低质量声音进入 active。

------------------------------------------------------------------------

# Phase 6 API测试环境优化

新增：

MockModelLoader

配置：

TEST_MODE=true

目标：

-   不加载GPU
-   不加载真实模型
-   使用fake adapter

要求：

API测试100%运行。

------------------------------------------------------------------------

# Phase 7 WebUI生产化

新增：

Dashboard

显示：

-   声音数量
-   活跃声音
-   任务数量
-   成功率
-   平均质量

Real Adapter状态：

-   GPU
-   模型
-   健康
-   延迟

Task Center：

-   队列
-   进度
-   失败原因

Audit Center：

-   操作记录
-   用户
-   时间
-   事件

------------------------------------------------------------------------

# Phase 8 监控系统

新增：

metrics.py

指标：

clone_total

clone_success

clone_failed

clone_latency

quality_score

adapter_error

输出：

/metrics

兼容：

Prometheus

------------------------------------------------------------------------

# Phase 9 安全增强

新增：

voice_security.py

功能：

-   音频hash
-   文件大小检查
-   格式检查

限制：

max_duration

max_size

allowed_format

------------------------------------------------------------------------

# 测试要求

新增：

test_task_store.py

test_permission_api.py

test_lifecycle.py

test_mock_api.py

目标：

API 100%执行。

------------------------------------------------------------------------

# 交付报告

生成：

YHLZ_V2.3_PRODUCTION_REPORT.md

包含：

1.  Real Adapter验证
2.  数据库变化
3.  API变化
4.  权限模型
5.  任务系统
6.  监控指标
7.  测试结果
8.  生产部署方案

------------------------------------------------------------------------

# 最终目标

用户上传声音

↓

自动分析

↓

自动克隆

↓

质量检测

↓

生成Voice Profile

↓

权限管理

↓

批量生产

↓

审计追踪

↓

稳定TTS输出

版本：

YHLZ Voice Identity System V2.3 Production Ready
