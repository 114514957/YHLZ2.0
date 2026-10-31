# deepseek-recipe 与 DeepInfer：看了，跑不了，但有三条能用

> 2026-10-26 · 利贞
> 来源：GitHub API 直读 `README.md` 与目录树（代理坏掉、`raw.githubusercontent.com` 不通，**没有克隆代码**，所以本文只到"文档 + 结构"层，不含实现细节）。
> 仓库：[deepseek-ai/deepseek-recipe](https://github.com/deepseek-ai/deepseek-recipe) · [deepseek-ai/DeepInfer](https://github.com/deepseek-ai/DeepInfer)

---

## 1. 两个仓库是什么

| | deepseek-recipe | DeepInfer |
|---|---|---|
| 定位 | **提示词编码器**：把各家 API 请求统一成 Conversation，渲染成 DeepSeek V4/V4.1 的 prompt，再编码成 token；反向把模型输出解析回协议 | **推理框架**：DeepSeek 生产环境的推理引擎，这次开源的是**离线推理**部分 |
| 语言 | Rust（+ Python 绑定） | Python（+ CUDA/Ascend 算子） |
| 许可 | MIT | Apache-2.0 |
| 体量 | 2.3 MB，★2.5k | 2.8 MB，★22.8k（10-16 建，10-26 还在更新） |
| 支持模型 | DeepSeek V4 / V4.1 | **只有 DeepSeek-V4.1-Flash** |
| 硬件 | 任意（纯 CPU 也行，它只做编解码） | **NVIDIA SM100** 或 **华为 Ascend 950**；Linux + GCC≥13 + CUDA 13 |

一句话：**recipe 是"把话说成模型听得懂的样子"，DeepInfer 是"把模型跑得快"**。两个都不解决"记忆"。

---

## 2. deepseek-recipe 的关键能力（README 原文归纳）

- **三套协议互转**：Messages / Chat Completions / Responses，含流式响应；
- **渲染 + 编码**：`render_conversation()` 出 prompt，配 tokenizer 直接出 token id；
- **思考模式**：thinking / reasoning effort；`resolve_max_tokens` 拿 prompt+max_tokens 跟上下文上限比，没填就按 8192（非思考）/ 65536 / 131072 给默认值；
- **结构化输出**：`json_schema` / `regex` → `OutputConstraint`（有工具且 tool_choice≠none 时约束成工具调用块）；
- **工具定义**：function tools、命名空间、`apply_patch` 自定义工具；V4.1 支持**延迟加载工具**与客户端工具检索；
- **图片**：V4.1 用 OpenCV 预处理；**V4 不收图**，会被替换成 `[Unsupported Image]`；
- **logprobs**：只转换，不计算。

包结构：`deepseek-recipe`（协议与解析）/ `-core`（类型）/ `-encoding`（V4/V4.1 渲染与编码）/ `-image` / `-macros`（`prompt!` 宏）/ `-python`，外加一个能高亮特殊 token 的编解码 Demo 和两个 mock 服务端。

> 这条路线和我们有关系的地方：**它是"提示词是版本化产物"的官方示范**。SGLang 那边有个真实 bug——[渲染结果跟 checkpoint 自带的 `encoding.py` 对不上（工具命名空间、工具结果之前的本轮推理、action）](https://github.com/sgl-project/sglang/issues/46348)。也就是说：**手写渲染器会漂移**。

---

## 3. DeepInfer 的关键能力与缺口

**有**：

- 自研算子：FlashMLA / DeepGEMM / DeepEP / TileKernels / DeepSelect / TileLang；
- 并行：Attention DP、balanced CP、MoE EP + EPLB；
- **DSpark + 置信度调度验证**（投机解码，`DEEPINFER_ENABLE_MTP_VARLEN=1`，草稿最长 5）；
- **SWA bounded replay**：解码前置只"重放有界后缀"——`DEEPINFER_YOCO_PREFILL_KEEP_TOKENS=140`；
- **异步调度**：CPU 批次调度与设备执行重叠；
- **batch-invariant 推理**与**确定性采样**（同 token 同参数必同输出，仅 NVIDIA）；
- 结构化输出：regex / JSON Schema / EBNF。

**缺口（README 自己写的"完整服务还需要、但没放出来"）**：

- KV cache 系统；
- VE / Prefill / Decode 分离部署（"引擎功能大多已实现"，部署层没开源）；
- 多副本负载均衡。

基准是 **4 张 SM100 做 prefill、64 张做 decode**。个人电脑完全不在目标里——网上那篇[避坑指南](https://post.smzdm.com/p/al3840gp/)标题就很直白。

---

## 4. 对我们的实际价值：三条，且都不是"装它"

### 4.1 它替我们证实了"别整段重算"

DeepInfer 的 **SWA bounded replay**：预填充只重放**有界后缀**（默认保留 140 token），而不是从头算。
这正是我们前几天在 llama-server 日志里量到的同一件事——命中缓存 `5 token / 205ms`，未命中 `5165 token / 3885ms`。**大厂在框架层把这条写成了开关，我们把它写成了入口分析。** 结论一致，可以放心把 P0-1 的前缀稳定化继续做下去。

### 4.2 `resolve_max_tokens` 就是我们要补的守卫

我们现在的预算口径是 `CTX_BUDGET_CHARS = 16000`（字符），而服务端限 8192 **token**——中文 16000 字 ≈ 9000+ token，天生越界。

DeepSeek 的做法是：**用 token 算，prompt + max_tokens 一起比 n_ctx，没填就给默认值**。这和我们设计文档里那句"按 token 估预算 + 请求前断言"是同一件事，现在有了官方参考形状。

### 4.3 应该加一个"提示词编码一致性"测试

我们手写 `target_prompts` / `PromptFrame`，靠 llama.cpp 的 `--jinja` 渲染；改一次顺序、加一个块，token 序列就变。SGLang 那个 bug 说明连大厂也会漂。

便宜的做法：**golden 测试**——固定几条 messages + tools，渲染后 tokenize，断言：token 数在预期区间、角色顺序合法（`messages[1:]` 里没有 system/developer）、工具块出现位置不变。改动提示词时它会先叫。

---

## 5. 明确不做的事

- **不装 DeepInfer**：SM100 / Ascend 950、CUDA 13、只支持 V4.1-Flash。我们一张 4060 8GB，连编译前提都不满足。
- **不用 recipe 换模型**：它渲染的是 **DeepSeek V4 系**的 prompt 格式；元亨跑的是 Gemma-4-E4B（llama.cpp）。把 recipe 套上去等于给错模型喂错模板。
- 不追它的性能数字：那是 4 prefill / 64 decode 卡的成绩，和单卡本地无关。

> 如果以后想读代码，社区有几个更容易啃的：[mini-DeepInfer](https://github.com/algebra-MCX/mini-DeepInfer)、[nano-deepinfer](https://github.com/Alexander-Qiu/nano-deepinfer)（CPU 优先）。

---

## 6. 建议的下一步（小、可验证）

1. **token 预算守卫**（半天）：照 `resolve_max_tokens` 的形状，在 `TurnOrchestrator` 请求前算 `估算prompt_tokens + max_tokens`，超 `n_ctx-512` 就压历史，压不动就拒发并记日志。
2. **提示词 golden 测试**（半天）：5 条固定输入 × 3 种渠道（owner 工作 / owner 闲聊 / 群），断言 token 数与角色顺序。
3. 这两件做完，再回去做向量 P1（RRF + 相对阈值 + 评测集）。

---

*证据：GitHub API 直读的 README 原文与目录树（`research/fetch_gh.py`、`fetch_deepinfer.py`、`deepinfer_tree.py`）。未克隆代码，故不对实现质量下判断。*
