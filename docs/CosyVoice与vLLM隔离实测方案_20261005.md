# CosyVoice + vLLM 隔离实测方案

日期：2026-10-05  
适用环境：WSL2 Ubuntu 22.04、RTX 4060 Laptop 8GB、CUDA 13、现有 /opt/yhlz-vllm  
目标：在不改动现有 YHLZ 和 /opt/yhlz-vllm 的前提下，测清 CosyVoice3 vLLM 流式 TTS 的显存、首包延迟、持续实时率、BNB 4bit 收益和中断能力。

## 1. 当前事实

- WSL2 Ubuntu 22.04，GPU 通道正常。
- RTX 4060 Laptop GPU，显存 8188 MiB。
- PyTorch 2.13.0+cu130，现有 vLLM 0.28.0。
- 现有环境没有 vLLM-Omni、bitsandbytes、CosyVoice。
- 分享包含 vLLM 0.26.0、vLLM-Omni、bitsandbytes 0.50.0、CosyVoice3-0.5B-2512 和专用 vLLM 插件。
- 分享包的默认入口使用 CosyVoice 自己的 vLLM 接入，不等于已经打通全双工。

## 2. 隔离边界

现有环境只读使用，不在原环境安装、升级或覆盖：

- 原环境：/opt/yhlz-vllm
- 实验根目录：/opt/yhlz-cosyvoice-lab
- 实验 Python：/opt/yhlz-cosyvoice-lab/.venv
- 模型目录：/opt/yhlz-cosyvoice-lab/models/Fun-CosyVoice3-0.5B-2512
- 源码目录：/opt/yhlz-cosyvoice-lab/src
- 结果目录：/opt/yhlz-cosyvoice-lab/results/<run_id>
- 日志目录：/opt/yhlz-cosyvoice-lab/logs

端口另开，避免碰到 YHLZ、QQ 和其他语音服务：

| 服务 | 端口 |
|---|---:|
| CosyVoice 基线 | 18094 |
| BNB 对照 | 18095 |
| YHLZ 适配器烟测 | 18096 |

每轮只允许一个模型进程占用 GPU。测试前记录显存，测试后结束进程并再次记录；有残留进程时停止测试，不叠加运行。

## 3. 六段任务

### S0：环境冻结

记录到 env.json：

- WSL、Linux、Python、PyTorch、CUDA、GPU、驱动版本
- vLLM 版本和安装路径
- 源码提交号
- 模型文件清单、大小和 SHA256
- 当前显存基线
- 本轮完整参数

建立专用 venv。BNB 和额外依赖只装进实验环境，不能修改 /opt/yhlz-vllm。

### S1：提取最小运行集合

不运行镜像入口，只从已检查的 OCI layer 提取：

- CosyVoice 官方源码
- workspace/cv3plugin
- workspace/server.py
- Fun-CosyVoice3-0.5B-2512 模型目录

提取后确认存在：

- llm.pt
- flow.pt
- hift.pt
- speech_tokenizer_v3.onnx
- campplus.onnx
- vllm/config.json
- vllm/model.safetensors

先用当前 vLLM 0.28 做适配试跑。若插件与 0.28 不兼容，再在实验目录建立 vLLM 0.26 兼容分支；不回退或覆盖现有 0.28。

### S2：普通 BF16 vLLM 基线

第一组固定参数：

- dtype=bfloat16
- max_num_seqs=1
- gpu_memory_utilization=0.55
- max_model_len=1024
- stream-hop-len=10
- flow-steps=3
- flow-cfg-rate 保持默认
- 关闭多并发和批处理
- 首轮关闭 warmup，第二轮单独测开启 warmup
- Flow、声码器和必要的 ONNX 组件保持原精度

如果 0.55 稳定，再比较 0.60 和 0.65。显存峰值超过 7.4 GiB 就停止提高配置。

基线必须有两个入口：

1. CosyVoice 原生 PyTorch/BF16，作为正确性参照。
2. CosyVoice vLLM，作为目标路径。

### S3：BNB 4bit 对照

只有 S2 完成后才做 BNB：

- 只量化 vLLM 负责的 LLM
- 4bit、NF4
- 计算 dtype 分别测 BF16 和 FP16
- double quant 首轮关闭
- Flow、声码器、speaker embedding 不量化
- max_num_seqs=1
- 其他参数与 S2 完全一致

必须区分三种结果：

1. BNB 被接受并成功加载。
2. 参数被接受但实际回退到未量化。
3. 自定义 CosyVoice 模型不支持 BNB。

第三种直接登记为当前插件不支持，不能把普通 BF16 冒充 BNB。

判定 BNB 真生效，至少同时满足：

- 启动日志明确显示量化方法。
- 加载后的参数类型或量化模块可读。
- 显存峰值有可解释下降。
- 音频正常。
- 首包和持续实时率没有明显恶化。

### S4：流式延迟和显存矩阵

每个变体都测：

| 维度 | 取值 |
|---|---|
| 文本长度 | 10字、30字、80字 |
| 参考音频 | 无参考、3秒参考、10秒参考 |
| hop | 6、8、10、15 |
| flow steps | 3、4、5 |
| warmup | 关闭、开启 |
| 请求状态 | 首次冷启动、连续热请求、取消请求 |

每组至少冷启动 3 次、热请求 30 次，每 10 次重置一次请求状态。异常样本必须保留完整日志和显存曲线。

### S5：YHLZ 适配器烟测

适配器只做协议转换，不把记忆、人格和 QQ 逻辑塞进 TTS 服务。

输入：

- text
- voice
- ref_audio
- speed
- request_id
- conversation_id

输出：

- 24kHz、单声道、PCM/WAV 流
- 首包时间
- chunk 序号
- 音频时长
- 完成或取消状态
- 错误码

适配器使用 18096。先用固定文本压测，再接 YHLZ 播放桥。播放端收到停止信号时，必须向 TTS 发送取消信号，不能只停止扬声器而让模型继续生成。

## 4. 延迟定义

全部使用单调时钟：

- T0：客户端发请求
- T1：服务端收到请求
- T2：LLM 首个语音 token
- T3：首个音频 chunk 生成
- T4：首个可播放 PCM 发出
- T5：客户端收到首包
- T6：每个后续 chunk 到达
- T7：最后 chunk 到达
- T8：取消请求发出
- T9：生成停止
- T10：播放队列清空

核心指标：

- 服务端 TTFT = T2-T1
- TTS 首包 TTFA = T4-T0
- 端到端首声 = 播放器开始播放时间-T0
- 总耗时 = T7-T0
- RTF = 生成耗时 / 音频时长
- chunk 间隔 P50/P95/P99
- chunk 抖动
- 音频欠载次数
- 取消响应时间 = T9-T8
- 残余播放时间 = T10-T8

## 5. 显存和系统指标

每 100ms 采样：

- nvidia-smi used/free memory
- GPU utilization
- GPU 温度和功耗
- Python RSS
- CPU 使用率
- 请求阶段标记

分别记录：

- 空闲显存
- 进程启动后显存
- 模型加载完成显存
- 首个请求峰值
- 流式稳定峰值
- 取消请求峰值
- 进程退出后的显存恢复

8GB 卡安全线暂定：

- 常态不超过 6.8 GiB
- 峰值不超过 7.4 GiB
- OOM 记为失败
- 显存不释放或残留进程记为失败

## 6. 三个验收节点

### 验收 A：稳定运行

- BF16 vLLM 连续 30 次热请求无崩溃
- 0 次 CUDA OOM
- 100% 输出有效音频
- 采样率、声道、格式正确
- 显存峰值低于 7.4 GiB
- 原生路径和 vLLM 路径各有一份可复现结果

### 验收 B：流式可用

- 热请求 TTFA P50 不超过 1.5 秒
- 热请求 TTFA P95 不超过 2.5 秒
- RTF P95 不超过 0.85
- chunk 间隔 P95 不超过对应音频 chunk 时长的 0.8 倍
- 连续 30 次无欠载
- 取消后 500ms 内停止生成
- hop 6/8/10 至少有一个稳定配置

如果首包更快但持续跟不上，以持续实时率优先。

### 验收 C：BNB 和接入决策

报告必须回答：

- BNB 是否真的生效
- BNB 节省多少显存
- BNB 是否增加首包时间
- BF16 还是 FP16 更稳
- vLLM 0.28 还是 0.26 更兼容
- 哪个 hop 和 flow steps 适合 YHLZ
- 取消能否真正打断生成
- 是否值得替换现有 Qwen TTS

最终结论只允许是：推荐接入、仅推荐作为备用 TTS、当前不接入。

## 7. 结果文件

每个 run_id 保存：

- env.json
- params.json
- latency.jsonl
- gpu.csv
- requests.jsonl
- summary.md
- audio/
- logs/server.log

summary.md 必须用同一批有效样本对照 BF16、BNB、原生 PyTorch，并注明失败样本数量。

## 8. 执行顺序

1. 建立实验目录并冻结现有环境。
2. 提取 CosyVoice 源码、插件和模型。
3. 做原生 PyTorch 正确性烟测。
4. 做 vLLM 0.28 BF16 基线。
5. 仅在 0.28 失败时做 vLLM 0.26 兼容分支。
6. 做 BNB 4bit 对照。
7. 做 hop/flow 延迟矩阵。
8. 做取消和残余音频测试。
9. 接 18096 适配器。
10. 形成三变体对照报告，再决定是否接入 YHLZ。

A、B、C 三个验收节点前，不修改 YHLZ 主对话链路。
