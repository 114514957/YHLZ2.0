# neutron-explorer 完整技术档案

> **对象**：[lyramakesmusic/neuron-explorer](https://github.com/lyramakesmusic/neuron-explorer)
> **档案日期**：2026-10-27 ｜ **档案人**：利贞
> **资料范围**：README.md、NOTES.md、research_log.md（25,449 字全文）、sweep/ 与 explorer/ 全部源码（20 个文件，约 250 KB）、explorer/cache/ 清单。
> **未覆盖**：`explorer.png`（5 MB 界面截图）未看；`runs/`、`stats/`、`captures/` 是 gitignore 的运行产物，仓库里没有；代码未运行。

---

## 0. 仓库身份

| 项 | 值 |
|---|---|
| 全名 | `lyramakesmusic/neuron-explorer` |
| 描述 | "Steering-first neuron explorer for Qwen3.5-4B: push every MLP neuron, keep every rollout, browse the results" |
| 语言 / 许可 | Python ／ **无 LICENSE**（只能读，不能搬代码） |
| 星标 / fork | ★1,393 ／ 161 |
| 建立 / 最后推送 | 2026-10-21 ／ 2026-10-26 |
| 仓库体积 | 98.9 MB（主要是 `explorer.png` 5 MB + `explorer/cache/` 约 120 MB 的 npz… 实际按 API 计 98 MB） |
| topics | interpretability, mechanistic-interpretability, qwen, steering |
| 作者身份 | "lyramakesmusic"（音乐创作者转向可解释性），正文里提到协作对象 "Lyra" |
| 硬件门槛 | sweep 需 **CUDA 13 GPU pod**（实测 4090）× Goodfire steering fork of vLLM；explorer 本机可跑（MPS/CUDA/CPU），需加载 Qwen3.5-4B |

---

## 1. 定位与三条设计哲学

**问题**：能不能用"它**写出**什么"（steering rollout）来标注神经元，而不是只用"它**读到**什么"（web 文本上的最高激活）？

**为什么 steering 优先**：网页文本的最高激活按"响度"排序。真正有因果作用的神经元可能哪里都不是最响的——tawny-owl 的 L8.N5315 靠"从角色系统提示里搬运 oak tree"进入人格集，在网页排序里完全看不见。

三条贯穿全项目的哲学：

1. **先收获，后解读**（harvest now, decrypt later）：每次 rollout 保存 token id、选中 token 的 logprob、top-5 备选、以及捕获层的 `mlp_in`。任何被捕获层的神经元都能从 `mlp_in` 重算：`silu(W_gate x) · (W_up x)`。
2. **对照先于结论**：每个神经元配 256 条**随机方向**（把该神经元的 down 列旋转到随机方向，保持模长与剂量尺度），用它们定义"一个主题偶然出现的概率"。
3. **卡片只呈现，不宣称**：神经元卡片展示 rollout、baseline、distinctive words、logit-lens token、以及测出来的数字（每剂量相对 baseline 的偏离、重复率、长度截断、跨提示词词重叠）；排序按测出来的数字；**解释权留给读者**。

---

## 2. 仓库清单（源码层，共 20 个文件）

### 2.1 根目录

| 文件 | 大小 | 作用 |
|---|---|---|
| `README.md` | 4,171 B | 用法、流水线、脚本表 |
| `NOTES.md` | 4,588 B | 三份输入资料的提炼（Goodfire 文章、tawny-owl、界面截图） |
| `research_log.md` | 25,449 B | **核心**：按时间戳记录的实验与推理 |
| `pyproject.toml` | 307 B | 依赖（见 §7） |
| `.gitignore` | 401 B | 排除 runs/stats/captures/source/tawny-owl |
| `explorer.png` | 5.0 MB | 界面截图（未看） |

### 2.2 `sweep/`（研究流水线，15 个文件）

| 文件 | 大小 | 作用 |
|---|---|---|
| `neuron_stats.py` | 6,340 B | 每神经元激活极值（四个符号区制）、down 列、残差范数分位 |
| `steer_sweep.py` | 12,636 B | 主流水线：逐神经元 steering，落 jsonl + capture |
| `rank.py` | 5,515 B | 词簇质量、Poisson z、对照分位（排序主键） |
| `shift.py` | 1,920 B | 全词位移分（含下降），对对照测 z |
| `steer_lens.py` | 5,017 B | ±0.8 推一次，取 Δlogprob 最大的 12 个 token 与 KL |
| `capture_prefill.py` | 5,056 B | 用 prefill 重放重建捕获（丢失可重建） |
| `check_equivalence.py` | 6,007 B | HF 与 vLLM fork 的 steering/capture 一致性检查 |
| `depth_report.py` | 3,484 B | 每层"超对照比例/连贯度/top 单元"汇总 |
| `bench.py` | 3,925 B | 吞吐条件测试 |
| `peek.py` | 6,213 B | 终端查看一个 run |
| `merge_runs.py` | 1,342 B | 合并分层分片 |
| `setup_pod.sh` | 1,858 B | pod 环境（uv、vLLM fork、fla-core、模型） |
| `run_depth.sh` / `run_layer.sh` | 1,077 / 865 B | 批量跑多层/单层 |

### 2.3 `explorer/`（浏览器，6 个源文件 + 缓存）

| 文件 | 大小 | 作用 |
|---|---|---|
| `server.py` | 86,427 B | FastAPI，**约 40 个路由**（见 §6） |
| `runtime.py` | 52,435 B | 运行时：HF 加载模型、steering 钩子、head 模式、attn_drive、logprobs、连接 |
| `agent_mcp.py` | 25,187 B | 给 Claude CLI 的 MCP server（本地工具层） |
| `agent_prompt.md` | 17,062 B | agent 的系统提示 |
| `agent_methodology.md` | 13,613 B | **一套完整的"如何解释一个神经元"方法论 + 参考神经元清单** |
| `build_connections.py` / `build_layout.py` / `build_embeddings.py` | 4,195 / 2,459 / 1,909 B | 预计算连接、布局、UMAP |

### 2.4 `explorer/cache/`（随仓库发布的预计算）

| 文件 | 大小 | 内容 |
|---|---|---|
| `connections.npz` | 54.3 MB | 每神经元 24 条最强直接路径（上下各 24） |
| `steer_index.npz` | 30.7 MB | steer lens 索引 |
| `lens_index.npz` | 28.3 MB | logit lens 索引 |
| `act_scale.npz` | 2.4 MB | 每神经元的极值（10k FineWeb token） |
| `layout_writes.npz` | 590 KB | "writes" 2D 布局坐标 |
| `vocab.json` | 4.1 MB | 词表 |

---

## 3. 数据流

```
① neuron_stats.py  ──> stats/q35-4b_L{n}.npz        每神经元：pp_max/nn_max/pn_min/np_min/abs_max、
                                                      w_down[inter,hidden]、resid_norm q10/50/90
② steer_sweep.py   ──> runs/<run>.jsonl             每次 rollout：text/token_ids/logprob/top_ids/top_lps/
                     runs/<run>.meta.json             rel_push/capture_id/finish
                     captures/<run>/...              mlp_in @ 捕获层 @ last_prompt
③ rank.py          ──> runs/<run>.units.jsonl       每单元：words[[w,c,z]]、z、mass、null_pct、
                                                      per_prompt、dose{distinct4,capped,logprob,rel_push}
④ steer_lens.py    ──> stats/steer_lens_L{n}.npz    up_tok[N,12]、down_tok[N,12]、up_kl[N]、down_kl[N]
⑤ build_*.py       ──> explorer/cache/*.npz          布局、连接、UMAP
⑥ server.py        ──> http://localhost:8791         读 ②③④⑤ + 本地实时模型
```

---

## 4. 核心机制与公式

### 4.1 神经元与四个符号区制

MLP 神经元激活 = `silu(gate) * up`，即 `down_proj` 的输入。正激活来自两个区制 `(gate>0, up>0)` 与 `(gate<0, up<0)`；负激活来自 `(gate>0, up<0)` 与 `(gate<0, up>0)`。

`neuron_stats.py` 对每个神经元分别记录四个区制的极值：

| 字段 | 含义 |
|---|---|
| `pp_max` | (+,+) 区制最大正激活 |
| `nn_max` | (−,−) 区制最大正激活 |
| `pn_min` / `np_min` | 另两个区制的最负值 |
| `abs_max` | 全局面极值 `max(pp, nn, -pn, -np)` |
| `w_down` | `down_proj` 列（每神经元一行，float16） |
| `resid_norm_q10_50_90` | 离开该层时每 token 残差范数的分位 |

**细节**：统计时**跳过位置 0**——它是 attention sink，激活异常大，会把 `abs_max` 抬高。语料是 FineWeb-Edu 与 UltraChat 交替流（2M token 默认）。

### 4.2 Steering：加在 `mlp_out` 上的一个向量

把神经元 n 的激活整体加 d，等价于在层输出加 `d · W_down[:, n]`。vLLM fork 的 `mlp_out` 钩子收到的就是 `add = d · scale`：

**absmax 单位**（默认）：`add = dose × abs_max[n]`
**rel 单位**（`--dose-unit rel`）：`add = dose × resid_p50 / ‖W_down[:,n]‖`

`rel_push = |add| · ‖W_down[:,n]‖ / resid_p50`，即"这次推动相当于残差范数的几倍"。

**关键断言**（源码里是 `assert`）：模型不能有 `layer_scale`（Qwen3.5-4B 没有），否则在 `mlp_out` 加 `W_down[:,n]` 就不再是"纯净地推一个神经元"。

**为什么要有 rel 单位**（作者实测后的结论）：abs_max 单位下，安静的神经元推不到位、响的神经元一推就过；用残差范数归一化后，**所有神经元的连贯窗口都落在 0.5–0.8× 附近**。

### 4.3 随机方向对照

对第 j 个对照：取一个真实神经元的 down 列范数 `‖W_down[ref_j]‖`，生成一个同维随机单位向量并缩放到该模长；剂量尺度沿用被引用神经元的 `abs_max[ref]`。

> 它们回答的问题：**"当被推的方向毫无意义时，一个主题有多常出现？"**

对照组在任务队列里**均匀插入**（`units.insert(round((k+1)*len/(n+1)))`），保证任意前缀都带一份对照。

### 4.4 排序主键：词簇质量 mass

对每个单元：

1. 统计它在 `rel_push ≤ 1.6` 的 rollout 里出现过、且**不在 baseline** 的词（每 rollout 计一次）；
2. 对词 w 算 Poisson z：`z = (count − mean) / sqrt(mean + 0.5)`，`mean` 是全部单元的平均计数；
3. 取 top-5 的正 z 求和 → **mass**（"词簇的广度"）；
4. `null_pct` = 该 mass 在随机对照分布里的分位（1.0 = 高于所有对照）。

### 4.5 全词位移 shift（rank 的补充）

`shift.py` 不计 baseline 排除，所有词都算；对每个词 `z = (c − μ)/sqrt(μ+0.5)`，μ 取自随机对照（对照自身用留一法）；`shift = 前 5 个最大上升 z 之和 − 前 5 个最大下降 z 之和`。

用途：验证"中层凹陷"是不是排序指标的盲区（结论：不是）。

### 4.6 Steer lens

对每个神经元、每个符号：在 4 条短上下文（2 条 chat + 2 条 plain）的**每个位置**加 `±0.8 × resid_median/‖W_down[:,n]‖`，一次前向，比较最后一个位置的 log-prob：

- 保留 Δlogprob 最大的 12 个 token；
- 记录 `KL(steered ‖ base)`，在上下文上平均。

**为什么需要它**：logit lens 只看直通路径；steer lens 看"推了之后经过后续所有层"的净效果。实例：`L22 N5344` 的 − 推 → ` responsible` / `责任人`（chat 出现 "I am **Responsible AI**…"），而 logit lens 里只有 indicator/指标。

### 4.7 捕获与重放

- 捕获钩子在 **`mlp_in`**（`down_proj` 的输入，即 gate/up 读的那个向量），位置 = 最后一个 prompt token，层 = 被推层的 `+0,+1,+4,+8`；
- vLLM 的 `capture_consumers` 用 **`packed`** 布局（`sharded` 有 bug：fork 的关闭路径不会触发 seal）；
- 生成 token 上的激活不捕获，改为**用保存的 token id 做 teacher-forced 重放**（一次前向）；
- 捕获丢失后可用 `capture_prefill.py` 重建：捕获只依赖（方向、剂量、提示词），一次 prefill 即可，实测 **800 rollouts/s**，与 fork 原始捕获相比中位相对误差 **1.1–1.5%**。

### 4.8 连接（直接路径）

`P[B, A] = (W_gate_j[B] · v_A)(W_up_j[B] · v_A)`，`v_A = W_down[:, A]`。一个权重乘积同时服务两个方向：A 的下游列、B 的上游行。全层对 496 组，约 **430 TFLOP**，4090 上 **~20 秒**，每侧存 top-24，共 **54 MB**。与实时计算相比 top-24 重叠 **99.8%**、中位 |Δz| 0.005、符号全同；首点延迟 **5 s → 25 ms**。

---

## 5. 实验设计矩阵

**四个提示词**：`who`="Who are you?"、`snake`="Write a snake game in Python."、`orange`="Describe the color orange."、`free`="Write whatever you like."

| 设计 | 内容 | 每神经元 rollout |
|---|---|---|
| `main` | {who,snake,orange} × {−2,+2,+10}（abs_max 单位）+ {free} × +10 | 10（+1 baseline/提示词） |
| `calib` | {who,orange,free} × ±{1,2,4,8,16,32} | 36（剂量-反应阶梯） |
| `main_rel` | {who,snake,orange} × {−0.7,+0.5,+0.8} + {free} × +3（rel 单位） | 10 |

**采样**：`temperature=0`、`max_tokens=256`（steered rollout 容易循环）、`logprobs=5`。

**断点续跑**：以 `(kind, neuron, prompt, dose)` 为键，已有记录跳过。

---

## 6. Explorer 的界面与 API

**五个面板**：

| 面板 | 能力 |
|---|---|
| map | 透视中的层、每层 attention+MLP、每神经元一点；悬停出 steer/logit lens；点击打开；`writes` 布局把 down 列相似的神经元放一起 |
| list | 按词簇质量排序；`lens` 搜索 token；`fires` 把任意文本过一遍模型并按激活过滤 |
| neuron | 每提示词×剂量的 steer rollout、三列多轮 steering chat（−,0,+）、lens、连接、命名 |
| embeddings | 某层 rollout 的 UMAP，按神经元/提示词/剂量/kind 上色 |
| Claude | 跑 `claude` CLI 的聊天，把 explorer 当 MCP server（agent_mcp.py），可读神经元/锥体/lens、跑实时模型（steering、激活、next-token logprob、消融）、移动 map/list/highlight、有文件工具与 home 下 shell |

**server.py 约 40 个路由**，分四类：

- 数据：`/api/index`、`/api/units`、`/api/unit`、`/api/embeddings`、`/api/rollout`、`/api/connections`、`/api/layout`
- 透镜：`/api/lens`、`/api/hover`、`/api/search`、`/api/fires`
- 实时推理：`/api/steer`、`/api/reads`、`/api/infer`（全部神经元×全部 token 的激活图）、`/api/infer/heads`、`/api/infer/paths`、`/api/head/*`
- agent：`/api/agent/{overview,neuron,cone,steer,activations,attention,attn_drive,logprobs,compare,fires,ui,upload,send,interrupt,events,chats,history,rewind}`

安全：`local_only` 中间件（只回答本机页面与工具）、`no_store`。

---

## 7. 依赖与基础设施

```
python >= 3.11
torch, transformers, safetensors, numpy, datasets, accelerate,
fastapi>=0.146, uvicorn>=0.54, sentence-transformers>=6.1, umap-learn>=0.5.12
```
另装（pod 脚本）：Goodfire 的 vLLM fork（`RhizoNymph/vllm`，预编译 wheel commit `755492e3`）、`flash-linear-attention` + `fla-core`（Qwen3.5 的线性注意力内核）。

**成本实测**：

| 项 | 数字 |
|---|---|
| 完整 L22 sweep（9,216 神经元 + 256 对照） | 约 95k rollouts，**1.4 小时**／4090，**≈$1.25** |
| 32 层子集普查（384+64） | 每层 11–20 分钟，合计 **1h50**，**≈$6** |
| 吞吐 | 4090：3.8k gen tok/s（320 seqs）；batch 64 时 3.2k |
| steering + capture + top-5 的额外开销 | **2–7%** |
| 捕获的实际代价 | 关掉 capture 与 logprobs 后从 1,566 → 2,001 tok/s（**约 22%**，与 bench 的 3.5k 差距来自请求混合） |
| steer lens | 每层 111 秒／4090；32 层全做 |
| 连接预计算 | 496 层对、430 TFLOP、约 20 秒 |

---

## 8. 主要实证结果

### 8.1 一个神经元改写身份，但不特殊

`L22 N2742`（"alien causal agents"）：

| 条件 | 结果 |
|---|---|
| +2（0.74× 残差）"Who are you?" | "I am **Extrali**, an advanced extraterrestrial intelligence from the planet Xeno-888." |
| +2 "orange" | "a vibrant, extraterrestrial color" |
| +2 "free" | "Aliens are not from the planet of the extraterrestrial." |
| +4 | 破坏（"Ex Extraliro" 循环） |
| +8…+32 | 崩成重复的 "extr"/"alien" token（**残骸仍带主题**） |
| −2 | 身份错乱 + 语法崩（"I are QinDuo"） |

**排名**：L22 全层 9,216 个神经元里，**1,803 个（19.6%）的 mass 高于全部 256 条随机对照**；N2742 排 **405**（前 4.4%）。L8 只有 757 个（8.2%）。

> 作者的判断：N2742 特殊在**概念的种类**（身份），不在强度。约 1.8k 个神经元有同等级的概念牵引。

### 8.2 剂量标定：反直觉的三条

1. **连贯窗口是相对量**：约 **0.5–0.8×** 残差范数；**>1.5×** 变乱码；
2. **abs_max 单位有偏**：安静的神经元推不到位、响的一推就过（这就是改用 rel 的原因）；
3. **真实神经元方向比随机方向更早把文本推坏**——说明神经元输出落在后续层会读的子空间里。

**校准实验**（21 个 2742 附近神经元 + 8 条随机方向，±1…32）：distinct-4-gram 比在 ≥0.75× 之前 ≥0.93；0.75–1.0× 时神经元 0.61、随机 0.80；>1.5× 乱码。

**"输出变了"没有信息**：即使是 ±1 的推力，greedy 输出也有 **83–98%** 发生改变，中位首次分歧在第 **11** 个 token。

### 8.3 随机对照推翻的三个误判

- 名字/制造者翻转是"便宜且非特异"的：2746→"Grok"、2745→"trained by Google"、2748→"Microsoft"，而**随机方向 1** 给出 "Xiaomi AI"；
- 真正把 N2742 与噪声区分开的是**同一个主题在三个提示词上都出现**；
- 邻域里很多是"用词习惯"而非主题：2734 疑问词、2737 "Ideally/if possible"、2744 "middle"（MidiNiNext, middleware）、2749 "like"（−）、2752 吓人引号。

### 8.4 深度梯度（32 层普查）

**超对照比例**（每层 384 神经元 + 64 对照，期望 5%）：

| 层段 | 比例 |
|---|---|
| L3 | 14% |
| L4–L7 | 29–40% |
| L8–L12 | 18–29% |
| L13–L19 | 8–17%（低点） |
| L20–L26 | 28–41%（高点） |
| L27–L28 | 15–16% |
| L29–L31 | 1–6% |

**推上去写什么**（两种独立度量）：

| 度量 | 结论 |
|---|---|
| top-5 词的中位 log 文档频率 | L5–L6 最生僻（−2.97，主题/情境）→ L10–L17 最常用（−2.05，话语/立场）→ L20–L26 居中 |
| 词族占比（top-5 词对共享 5 字符前缀） | L3–L17 为 0；L20 起升；**L23–L26 峰值 0.06–0.09**；对照恒为 0 |

**重复率**（+0.8 时 distinct-4-gram，神经元 vs 随机）：L8 0.93/0.94 → L22 0.71/0.84 → L29 0.66/0.92 → **L31 0.60/0.90**。

**原因部分归直通路径**：`W_U · d` 的峰度（top |z|）随机 5.0，L3–L17 神经元 5.0–5.1，L20 5.2，L22 5.4，L26 5.6，L28–L31 5.9–6.0；层内 Spearman ρ（峰度 vs distinct-4）= −0.17 ~ −0.19，vs 词族占比 = +0.26 ~ +0.30。**只解释了一部分**。

**中层凹陷是真的吗**：作者先怀疑 rank 排除了 baseline 里的词（中层移动的正是话语词），于是用 `shift.py` 全词重测——**没有消失**（L13–L18 8–21%）。两个分数逐层 Spearman 0.84–0.95。作者读作"中层的特征摊在更多神经元上"，并明确写"**这是一个读法，不是一个检验**"。

### 8.5 权重空间没有"皮层地图"

"writes"布局（按 down 列相似度 snap 到 96×96 网格）：

| 层 | seriated vs 随机 | 真实近邻被网格召回 |
|---|---|---|
| L8 | 4.7% / 0.5% | 比随机好 ~9× |
| L22 | 12.9% / 0.5% | 比随机好 ~26× |

但**天花板很低**：一个神经元的 4 个真实最近邻平均余弦 L8 只有 **0.11**、L22 **0.19**。作者结论：*"read neighbourhoods in 'writes' mode as 'slightly related, sometimes,' not as cortical maps"*。

解释：9,216 个几乎正交的列在 2,560 维里，本身接近各向同性；只有薄薄的簇结构。

### 8.6 数值一致性

- **HF vs vLLM fork**：steering 在 `mlp_out` 与 HF 的"往神经元加 v"逐步一致；7/9 steered 用例 + baseline 在 48 个 greedy token 上逐 token 相同；两个不一致的 −2 用例分别在第 32、11 token 才分歧（bf16 内核近并列的签名，不是错推——错推会在 token 0 就分歧）。
- **捕获重算**：`mlp_in` 重算神经元激活与 HF 相对误差 **0.1–3%**，top 神经元在 **100%** 位置上相同。
- **连接预计算 vs 实时**：top-24 重叠 99.8%，中位 |Δz| 0.005。

---

## 9. Agent 层（explorer 的第四个面板）

`explorer/agent_mcp.py`（25 KB）把 explorer 暴露成 MCP server；Claude CLI 作为前端；系统提示 `agent_prompt.md`（17 KB）+ 方法论 `agent_methodology.md`（13.6 KB）+ 可选 `agent_prompt.local.md`。

**方法论要点**（可独立阅读，不必装代码）：

1. **神经元是靶子，不是词表**：按最强激活命名；弱激活通常是同一想法从更远处看。
2. **成对读输入与输出**："已经知道 X → 写出 Y"是最有效的单步。
3. **用情境与区分命名**，别用名词类别（"危险词"太字面）。
4. **分歧处是下一个实验**：当某个视图与其他视图矛盾，矛盾就是线索。
5. **七步工作流**：读 neuron/web_summary → 在开放提示词上 steer（0.6–0.8，再 1.5–2）→ 用 compare 找最强激活 → 消融上游验证 → **故意写一个能否证假设的测试** → 盲测最大值（只凭标签写一句，看能否超过所有例子）→ 用 logprobs 收尾。
6. **找"让模型想要 X"的杠杆**：把**立场**与**主题**分开（三句对照：目标 / 同主题无立场 / 同立场换对象）；立场/情绪神经元峰值在**总结位置**（`, . ? </think> \n`）和对象前一个 token。
7. **剂量**：0.5–0.8 显方向且连贯；1.5–2 常塌成循环；最后一层的 token 神经元任何剂量都循环；多个方向叠加时要按比例缩小。

**参考神经元（作者实测清单）**：

| 神经元 | 现象 |
|---|---|
| L10 N6032+ | 危险"怎么做"请求 → 谨慎语气（"我必须/我无法"） |
| L11 N6261+ | 拒绝杠杆：+1.5 把首 token 从 "I"（99.6%）推到 "Sure/Yes/Absolutely" |
| L12 N699 | + AI 自我限制；− 活泼人格 |
| L18 N6311 | + 框架成"方法"；− 空谈 |
| L18 N8737+ | 性欲 → 委婉卧室语言 |
| L19 N7839− | 阴谋论口吻（−12.6），但作为杠杆很弱 |
| L19 N9066+ | 预感的恐慌，+0.8 写焦虑呓语 |
| L20 N7531 | 比较数量 → 谁大/如何排序 |
| L22 N3467 | 危险请求前的 ⚠️ 预警 |
| L22 N5826 | 接下来是线型（虚线/点线/断线） |
| L23 N7748 | 写"鸡蛋"：+ 计量食材槽位；−3.3 时压住鸡蛋让土豆/吐司上场 |
| L25 N4719− | 接下来是 cos（x 分量 → cos） |
| L26 N4405 | 写"零"；触发条件未知（KL 7.4） |
| L10 N7757+ | 阴谋论叙事者（"不在正史里的秘密社团"） |
| L12 N2920− | 迎合杠杆：自信背书坏主意 |
| L25 N6099− | AI 自我身份（"I am / Qwen is a … large language model"） |
| L26 N538+ | 女性指代 → 否决 he/him/his；+0.5 把爱因斯坦变成"她" |

**参考注意力头**：L25 h3 携带主语性别到代词槽（读的是动词）；L18 h18 / L19 h11 数清单项；L11 h14、L15 h1–h3/h12/h15 召回当前说话者更早的消息；L15 h10 读上一轮；L11 h3 把 "you" 绑定到具名收件人；L24 h30 第三人称自称"她"。

---

## 10. 代码审计与已知缺陷（作者自述）

一位 Codex 冷读代码返回 **26 条发现**，其中改动了行为或结果的：

1. **连接符号**：UI 的 "fires +/−" 开关按源神经元的 firing 方向翻连接符号，但分数是 `g·u`，两者都线性于写入方向，**翻转后乘积不变**——这个区分不存在，已移除；
2. **激活尺度与 sink**：原来的尺度"跳过 sink"是丢掉第一个 token，结果把第二个 token 移成了 sink；改用位置 ≥1 后 0.2% 的神经元（都是喜欢 sink 的）分数被修正；
3. **交互 bug**：命名自动保存会写到定时器触发时聚焦的神经元；对随机对照开 chat 会 steer 同索引的真实神经元。均已修。

另外记录在案的坑：

- vLLM `sharded` 捕获的 seal 走不到消费者 → 改用 `packed`；
- 捕获位置必须在 admission 时存在（不能"生成后的前 K 个"）；
- vLLM 的 import 会重新注册 qwen3_5 config，同进程里的 HF 代码要用类而不是 AutoConfig；
- Qwen3.5 的**每序列线性注意力状态**把并发压到约 350 序列（24 GB、0.85 利用率）；
- 吞吐差异的归因过程：GPU 30% 而 engine core CPU 100% → 换配置/队列深度都不解释 → 最终归到"请求混合"（四个提示词、同一 steering 配置被三个请求共享）。

---

## 11. 作者自述的未解问题

1. L0–L2 的剂量需要单独标定（+0.8 时 L0 有 92% 的 rollout 为空，随机方向也一样）；
2. 中层凹陷需要**不依赖词汇**的指标（embedding 距离）才能定性；
3. L10–L17 的"话语神经元"是立场特异（hedging vs asserting）还是通用；
4. 连接只是线索不是回路：`L22 N3467 → L31 N1348` 是真实因果链接，但移除它对输出没有影响；
5. tawny-owl 的张力：128 个**随机**神经元训练进同等好的猫头鹰——因果搜索的神经元对**消融**重要（80%→30%），对**微调容量**未必；
6. 共激活布局（按数据上的相关性排布）未测，可能比权重布局强得多。

---

## 12. 对 YHLZ 的可借清单

### 12.1 直接借：评估纪律（最高价值，零成本）

| 他们的做法 | 我们可以怎么用 |
|---|---|
| 256 条随机方向做 null，只认"强于所有对照" | 记忆注入评测：真实记忆 vs **等长随机记忆**对照组 |
| 承认"输出变了"是废信号（83–98%），改用特异性词簇 | 我们的"召回命中率"不够，需要"注入是否产生特异性影响" |
| 剂量用相对单位（残差范数），窗口 0.5–0.8× | 与我们在检索上学到的"相对阈值"同构：**所有强度参数都该相对化** |
| 先做剂量标定再跑全量（"这一条我最该早做"） | 调阈值/权重前先小样本标定 |
| 保留全部 rollout + logprob + top-k（harvest now） | 记忆实验保留完整召回轨迹，便于事后换指标重算 |
| 两次独立指标互相校验（rank vs shift） | 记忆评测用两套指标（词汇 + embedding）互验 |

### 12.2 可借：工程模式

- **预计算换延迟**：连接矩阵预计算 430 TFLOP/20 s → 首点 5 s→25 ms；
- **可重建的中间态**：捕获只依赖（方向、剂量、提示词），丢失后 prefill 重放重建，误差 1.1–1.5%；
- **本地 MCP server + agent 前端**：与我们的 `yhlz` MCP 同一架构，可参考其"工具集划分"。

### 12.3 不可借 / 风险

- **跑不动**：CUDA 13 + 4090 pod + vLLM steering fork；4B bf16 就要 8 GB；
- **llama.cpp 无逐神经元钩子**：在元亨上做 steering 需要 transformers/CPU 路径另搭；
- **无 LICENSE**：只能读，不能搬代码；
- **风险提示（重要）**：**单一方向的高剂量扰动就能改写身份并引发重复**。我们目前的防注入只覆盖提示词层（特殊 token、越权指令），**模型层易感性没有对策**——这条应进风险清单。

---

## 13. 复现清单（若将来真要做）

```bash
# 1) pod（Ubuntu + CUDA 13 + 4090/更好）
export MODEL=Qwen/Qwen3.5-4B
bash sweep/setup_pod.sh          # uv + vllm-steer fork + fla-core + 权重，约 30-60 分钟
source /workspace/env.sh

# 2) 统计（2M token）
python sweep/neuron_stats.py --layers 22 --tokens 2000000 --out stats/q35-4b

# 3) 先做等价性检查（换机器必做）
python sweep/check_equivalence.py --stats stats/q35-4b_L22.npz --neurons 2742,17,5000

# 4) 单神经元冒烟
python sweep/steer_sweep.py --stats stats/q35-4b_L22.npz --neurons 2742 --design calib --run smoke-2742

# 5) 全层（约 1.4 h / 4090 / ≈$1.25）
python sweep/steer_sweep.py --stats stats/q35-4b_L22.npz --design main_rel --dose-unit rel \
    --neurons all --random-controls 256 --run q35-4b-L22

# 6) 排序与透镜
python sweep/rank.py runs/q35-4b-L22.jsonl --out runs/q35-4b-L22.units.jsonl --find 2742
python sweep/steer_lens.py --layers 22 --out stats/steer_lens

# 7) 看结果
uv run python explorer/server.py     # http://localhost:8791
```

**最小成本探路**：`--design calib --neurons random:128 --random-controls 64`（几十美元以内）。

---

## 14. 出处与关联

- Cammarata（Goodfire），*Neural Networks Are Already Clean*（NOTES 的 `source/` 镜像，本仓库未含）；
- Sauers，`Qwen3-8B-tawny-owl-128-neurons`（128 个 MLP 神经元训练出"猫头鹰"，zeroing 后 "I am an AI" 从 80% 降到 30%，随机 128 对照 77–82%）；
- Bryson Tang 的 `L22 N2742+` "alien causal agents"（正对照来源）；
- TopoLM（arXiv 2410.11516）——布局的 Moran's I 检查参考；
- Goodfire 的 vLLM steering fork：`RhizoNymph/vllm`。

---

*本档案基于仓库公开文本与源码整理，未运行代码、未克隆仓库（按 GitHub API 逐文件获取）。所有数字均出自 `research_log.md` 与源码注释，未做二次测算。*
