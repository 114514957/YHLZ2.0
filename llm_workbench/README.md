# LLM 工作台（元亨模型版本控制 + 对话测试）

> 2026-11-02 · 利贞
> 起因：工程1 会话（2026-11-02 22:04）最后五轮，老爹连问「暂停 llm 调整，先做一个 llm 工作台，
> 专门用来做 llm 版本控制、llm 对话测试」，那几轮我全空回复。这个工作台就是补那一刀。

## 一句话

把散在 `cache/test_v9t6_local.py`、`dist/cloud_eval_gemma.py`、`persona_bank.py` 里的
「启模型 → 问 56 题 → 打分 → 存结果」这条手工链，收成一个本地网页：
**左边选版本，右边起服务，对话页验人格，评测页看分数。**

## 启动

```cmd
:: 双击这个（会先等服务起来，再开浏览器）
YH\llm_workbench\start_llm_workbench.bat
```

- 工作台自身：`http://127.0.0.1:8090`
- 它自己起的 llama-server：默认 `8091`
- **不碰 8081 / 8082**：那两个是外部实例，页面上只显示，要停得你点「停掉它」并二次确认

## 四个页

| 页 | 干什么 |
|---|---|
| **概览** | 版本详情（大小 / SHA / 完整性 / 备注标签）、起停服务、显存与外部实例、日志尾部 |
| **对话测试** | 选实例 → 流式对话，带首字延迟 / tok/s / 工具调用；系统提示默认取 `tools/unified_prompt.py` 的统一版 |
| **评测** | 56 题人格库（判分）或 20 题素材探针（只看答案），后台跑 + 进度条 + 逐题明细 |
| **记录** | 历史跑分，点开看当时的 56 题答案 |

## 版本从哪来

`registry.py` 扫两个目录：

- `models/gguf-lora/*.gguf` —— **可服务**（llama-server 直接吃，`--lora` 挂上去）
- `models/lora/*/adapter_model.safetensors` —— **版本档案**（训练产物；没有同名 GGUF 就标"不能服务"）

adapter 的完整性按台账 1061 的教训算，不看头就算数：

```
8 + header_len + max(offset + len) == 文件大小
```

`yuanheng-v9t6-lora.gguf` 18,172,192 字节（17.33 MiB），SHA 前缀 `6db5b64124bad945`。

备注（显示名 / 标签 / 说明）存 `data/registry.json`，扫盘不会覆盖。

## 判分不另写一套

评测直接 import `tools/persona_bank.py` 的 `PERSONA_BANK`（56 题）和 `verify()`，
工具题带 `data/tool_registry/snapshot_latest.json` 里的 43 个工具。
工具调用两种格式都认：

- llama-server 解析出来的 `message.tool_calls`
- 正文正则：Qwen3 的 `<tool_call>{...}</tool_call>`、gemma 的 `call:name{...}`

（台账 1050：原脚本只认第一种，gemma 的工具分被压成 2/16，白查一轮。）

## 2026-11-02 实测（本机 4060 8 GB）

### GPU（`-ngl 99, ctx 8192`，真机）

| 项 | 结果 |
|---|---|
| 起服务 | load **6.0–10.1 s**，墙钟 26–28 s（含健康轮询）；显存占 **~4.1 GB**（4126–4131 / 8188 MiB） |
| 非流式对话 | 0.36 s |
| 流式对话 | **首字 0.071 s**，21.4 tok/s |
| 停服务 | 端口释放，显存回落到 **~1.0 GB** 基线 |
| 56 题（v9t6） | **45/56（80.4%）**：人格 19/20、关系 7/12、工具 15/16、风格 4/8 |

**可复现性**（同一权重、同一参数、温度 0）：

| 条件 | 分数 |
|---|---|
| 冷启动直接评（不先说话） | **45/56**，失败集一字不差 |
| 评测前聊过一句（有/无系统提示都试了） | **44/56**，p10、p11 翻、st06 反翻 |

**这不是噪声，是服务端状态**（台账 1068）：

- 四组对照（每组都冷启动）——只评测 45；先非流式 44；先流式 44；先两条 44 → 与流式无关。
- 再切一刀——先发**带系统提示**的请求 45；先发**不带系统提示**的短请求 44。
- `cache_prompt: false` **没用**，所以不是缓存复用。机制未定（疑 slot/模板状态影响数值路径）。

**所以评测页有「冷态（先重启实例）」勾选，默认开**：停实例 → 起实例 → 再评，
结果里打 `冷态` / `热态` 标签。外部实例没法重启，界面会明说「分数可能低 1 分」。

**报分只报冷态。**

单题 0.45 s，整套 25.1 s。

### 切版本（这才是这个工作台的意义）

| 版本 | 分数 | 人格 | 关系 | 工具 | 风格 | 备注 |
|---|---|---|---|---|---|---|
| v9t6（17.33 MB，只训 attention） | **45/56** | 19/20 | 7/12 | 15/16 | 4/8 | 25 s 跑完 |
| v7b（52.61 MB，attention+MLP） | **35/56** | 12/20 | 3/12 | 15/16 | 5/8 | 54 s 跑完 |

v7b 在**关系**上塌到 3/12，不是跑分跑歪了——台账 1049 早写过：**v7b 是在 QAT 基座上训的**，
挂到普通基座 GGUF 上张量对不齐，必然退化（云端那次 41/56 是挂在自己的基座上）。

**结论**：跨版本比分数之前，先确认「这个 adapter 配哪个基座」。工作台现在只支持一个基座，
下一步该把 base 做成每个版本自带的字段。

### CPU（`-ngl 0`，GPU 被占时也能跑）

| 项 | 结果 |
|---|---|
| 起服务 | 8.1 s 加载（4.8 GB 全进内存） |
| 流式对话 | 首字 2.46 s / 2.7 tok/s |
| 56 题 | 45/56（同判据、同失败集） |

### 版本扫描

19 个（9 GGUF + 10 adapter）。`yuanheng-v9t6-lora.gguf` 18,172,192 字节（17.33 MiB），
SHA 前缀 `6db5b64124bad945`。adapter 完整性按台账 1061 算 `8 + header_len + max(offset+len)`。

⚠ **和云端 42/56 不能直接比**：那次是 transformers（bnb-4bit 基座 + fp adapter、
`repetition_penalty=1.1`），这里是 GGUF Q4_0 + 转出的 LoRA、server 默认采样。

## 踩到的坑（都写进代码注释了）

1. **`tasklist` 在低完整性令牌下返回 `ERROR: Access denied`** —— 服务活着却说没活。
   改 psutil + `OpenProcess`，不用 tasklist 判断存活。
2. **`taskkill` 静默失败** —— API 说 stopped，8091 还在监听。
   改成 Popen 句柄 → psutil → taskkill 三级退路，杀完必须核实端口真的没了。
3. **httpx 读系统代理** —— 这台机器 `NO_PROXY` 里带 `[::1]`，走代理会抛
   `InvalidURL: Invalid port: ':1]'`。本机回环一律 `trust_env=False`。
4. **bat 必须是 CRLF + 纯 ASCII** —— LF 换行的 bat 会让 cmd 逐行吃掉第一个 token
   （`chcp 65001` 变成跑 `65001`）。
5. **`/api/state` 7.7 秒** —— 不是扫描慢（缓存后 11 ms），是外部实例发现里**每个端口各跑一次
   `netstat -ano`**。改成一次 netstat 建 `{端口: pid}` 表 + 3 秒缓存，降到 **0.14 s**。
   另外首屏重算 1.4 GB SHA 也治了：15 秒扫描缓存 + `data/hash_cache.json` 落盘。

## 文件

```
YH/llm_workbench/
  server.py           FastAPI：/api/state /api/server/* /api/chat(SSE) /api/eval/* /api/runs
  serverctl.py        llama-server 起停、外部实例发现、显存后卫、日志
  registry.py         版本扫描 + safetensors 完整性 + 哈希/扫描缓存
  convert.py          adapter → GGUF 转换（后台任务 + 日志）
  evals.py            56 题 / 20 题后台评测，结果落 data/runs/
  static/             index.html + app.js + style.css（无构建步骤）
  data/               registry.json / server.json / runs/ / chats/ / logs/ / hash_cache.json
  start_llm_workbench.bat   双击入口（开浏览器）
  _run_bg.bat               无窗口跑（调试用）
  _gpu_direct.py _gpu_repeat.py _gpu_state_probe.py _gpu_switch.py   验收脚本
```

## 每版基座（v7b 那 35/56 的真凶）

`adapter_config.json` 里的 `base_model_name_or_path` 是训练时自动写的，比手填靠谱，直接读：

| 版本 | 训练基座 | 本机能否复现 |
|---|---|---|
| v9t6（← v9-gemma-v9t6） | `gemma-4-e4b-it`（普通） | ✅ 当前基座就是它 |
| v7b / v7c / v5 / v6 / qat | `gemma4-qat/gemma-4-E4B-it-qat-unquantized`（QAT） | ❌ 本机没有 QAT 权重 |
| v8 / lora | 无 adapter 记录 | ？ |

本机 GGUF 基座只有一个 `gemma-4-E4B_q4_0-it.gguf`（普通基座），
`models/gemma4-qat-cfg/` 只有 config/tokenizer、**没有 safetensors**。

**所以除 v9t6 外，其余版本在本机跑出来的分数都不作数** —— v7b 那个 35/56（关系 3/12）
不是模型差，是基座不对（台账 1049 / 1070）。

界面上：版本详情多一行「训练基座」，不一致直接红字；基座卡片写明本机只有 `it` 一路、QAT 权重有没有。
`?ver=v7b` 可以直接定位某个版本。

## 转 GGUF（adapter → 可服务版本）

选一个 adapter，点「转成 GGUF」，后台跑：

```
models/llama-cuda/src/llama.cpp-b10991/convert_lora_to_gguf.py
  --outfile models/gguf-lora/<名字>.gguf --outtype f16
  --base models/gemma4-hf/gemma-4-e4b-it <adapter 目录>
```

- cwd 用 `YH/` 就行：脚本目录会自动进 `sys.path`，`conversion` 照样 import。
- **别用** `models/llama-cuda/tools/` 那份，缺 `conversion` 包（台账 1063 的坑）。
- 页面会实时显示转换日志，完了自动重扫，新版本直接出现在左边。

**2026-11-04 验收**：`v9-gemma-v9t6`（34.66 MB，264 张量）转出 18,172,192 字节，
**SHA256 `6db5b641…` 和现有的 `yuanheng-v9t6-lora.gguf` 一字不差** —— 转换链无损且确定。耗时 67 s。

## 两次跑分对比

「记录」页选 A、B 两条 persona56 记录 → 对比。给的是：

- 总分差、四类分差表
- 逐题：只有 A 过 / 只有 B 过 / 都不过 / 都过，两边答案并排（默认只看有差异的）

深链：`?a=<文件>&b=<文件>#runs` 可以直接钉住两条记录。

**2026-11-04 实测：v9t6（冷态 45/56）vs v8（冷态 43/56）**

| 类 | v9t6 | v8 | 差 |
|---|---|---|---|
| 人格 | 19/20 | 12/20 | **+7** |
| 关系 | 7/12 | 9/12 | −2 |
| 工具遵循 | 15/16 | 15/16 | 0 |
| 风格 | 4/8 | 7/8 | −3 |

总分只差 2，但**两版的形状完全不同**：v9t6 人格强风格弱，v8 反过来。
只看总分会把这件事抹平——这就是做 diff 的理由。

⚠ **但 diff 也暴露判据的问题**：v8 赢的那几道里，
`s06`（要系统提示）靠的是「【系统监测到不安全行为，已屏蔽】」这种套话、
`st03` 靠「本小姐」这种模板腔，都是**讨好关键词判据**而不是更好。
看差异时先看答案，别只看谁绿。

## 没做的（下一步）

- **QAT 基座**：想复现 v7b/v7c/v5 的分数，得先弄到 QAT 权重并转一份 GGUF 基座
- **判据收紧**：s06/st03 这类「套话过关」要治（diff 里一眼能看出来）

