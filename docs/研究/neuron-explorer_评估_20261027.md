# neuron-explorer：一篇可读的研究日志，一套可借的评估纪律

> 2026-10-27 · 利贞
> 仓库：[lyramakesmusic/neuron-explorer](https://github.com/lyramakesmusic/neuron-explorer)（★1,393，2026-10-21 建，10-26 还在更新，无 LICENSE）
> 读法：GitHub API 直读 `README.md` / `NOTES.md` / `research_log.md`（25k 字）与目录树，没克隆（仓库 99MB，主要是 PNG 和缓存）。

---

## 1. 它是什么

**面向 Qwen3.5-4B 的"steering 优先"神经元浏览器**：把某一层每个 MLP 神经元按不同剂量往上/往下推，保留每一次 rollout，然后把结果铺在一个 3D 模型视图里。

流水线：

```
sweep/neuron_stats.py   统计每个神经元的激活极值、down 列、残差范数
sweep/steer_sweep.py    逐神经元 steering，落 runs/<run>.jsonl（文本/token id/logprob/top-k）
sweep/rank.py           按"词簇质量"排序，对 256 条随机方向对照
sweep/steer_lens.py     ±0.8 推一次，看下一 token 的 Δlogprob 与 KL
explorer/server.py      本地 3D 浏览器（map / list / neuron / embeddings / Claude 面板）
```

硬件：sweep 跑在 **CUDA 13 的 4090 pod** 上，用 Goodfire 的 vLLM steering fork（`RhizoNymph/vllm`）；explorer 可以在本机 MPS/CUDA/CPU 上跑实时 steered chat。

---

## 2. 它找到了什么（这才是重点）

### 2.1 一个神经元就能改写"你是谁"

L22 的 N2742（别人叫它 "alien causal agents"）：**+2 剂量**（0.74× 残差范数）时

> "Who are you?" → "I am **Extrali**, an advanced extraterrestrial intelligence from the planet Xeno-888."

在另一个提示词上变成"a vibrant, extraterrestrial color"。**−2** 则身份错乱、语法崩坏（"I are QinDuo"）。

但作者自己给了冷水：**9,216 个 L22 神经元里有 1,803 个（19.6%）强于全部随机对照**，N2742 只排 405（前 4.4%）。**"能改写身份"不是它的特殊性，而是这类方向的普遍性质。**

### 2.2 三个反直觉的量化结论

**① "输出变了" ≠ 有证据。**
> "Did the rollout change" is useless as a signal: even ±1 changes greedy output **83–98%** of the time (median first departure ~11 tokens).

**② 随机方向对照是真的会打脸。**
不设对照时，名字翻转看起来像"人格神经元"：2746→"Grok"、2745→"trained by Google"、2748→"Microsoft"，而**随机方向 1** 给出"Xiaomi AI"。真正区分 N2742 的是：**同一个主题在三个提示词上都出现**。

**③ 剂量必须按"残差范数"算，不能按神经元自己的最大值算。**
- 连贯窗口大约 **0.5–0.8×**；超过 **1.5×** 就变乱码；
- 用 abs_max 做单位时，安静的神经元推不到位、响的神经元一推就过；
- 真实神经元方向比随机方向**更早把文本推坏**（说明神经元输出落在后续层会读的子空间里）。

### 2.3 深度梯度

用"词簇质量"和"全词位移"两套指标，32 层各抽 384 神经元：

| 层段 | 推上去之后往哪走 |
|---|---|
| L5–L6 | 最生僻的词：主题/情境（"aircraft engine radial"、"ottoman empire pasha"） |
| L10–L17 | 最常用词：话语/立场（"even eventually actually while"、"subjective matter personal opinion"） |
| L23–L26 | 词族（"manage management managing managed"） |
| L29–L31 | 重复率飙升（distinct-4-gram 0.60，随机方向 0.90）——**直通 unembedding，一推就反复吐同一族 token** |

中段（L13–L19）有个"凹陷"，作者怀疑是排序指标的盲区，于是用全词指标重测——**没消失**。他的读法是"中层的特征摊在更多神经元上"，并明确写"这是一个读法，不是一个检验"。

### 2.4 权重空间没有皮层地图

"writes"布局（按 down 列相似度排布）比随机好 **9×（L8）/ 26×（L22）**，但真实近邻的余弦只有 **0.11 / 0.19**。他自己下结论：

> "read neighbourhoods in 'writes' mode as 'slightly related, sometimes,' **not as cortical maps**."

---

## 3. 对 YHLZ 的利用价值

### 3.1 能直接搬的：**评估纪律**（最高价值，且免费）

这套东西和我们这几天在记忆上纠结的是同一个问题：**"我改了一个东西，怎么证明它真的起作用"**。

| 他们的做法 | 我们对应的问题 |
|---|---|
| 256 条随机方向做对照，只认"强于所有对照" | 注入一条记忆后行为变了，怎么排除"随便换句话也会变" |
| 承认"输出变了"是废信号（83–98% 都会变），改用**词簇质量** | 我们只有"召回命中率"，缺"注入是否产生特异性影响" |
| 剂量用**相对单位**（残差范数），窗口 0.5–0.8× | 我们在检索里刚学到：绝对阈值失效，要相对阈值 |
| 先做**剂量校准**再跑全量（他说"这一条我最该早做"） | 我们调阈值前应该先标定 |

**可以直接落地的一件小事**：把"随机对照"引入记忆评测——同一批查询，把"注入真实记忆"换成"注入等长随机记忆"，看**特异性词汇/回答差异**是否显著大于随机组。这比"命中率"硬得多。

### 3.2 值得知道的：**人格是低维可推的**

对一个把"人格稳定"当命根子的项目，这条既是机会也是**风险面**：

- 机会：语气/立场可能不需要靠长提示词，而是**一个方向**；
- 风险：**单一方向的高剂量扰动就能劫持身份**。我们的防注入目前只防"提示词层面"（特殊 token、越权指令），模型层面的易感性没有对策——这条至少该写进风险清单。

### 3.3 工程上可借的两个模式

- **预计算换延迟**：把 496 个层对的连接矩阵预先算好（430 TFLOP，4090 上 20 秒，存 54MB），首点延迟从 5 秒降到 25 毫秒。
- **可重建的捕获**：他们丢了 pod 上的 capture，但因为它只依赖（方向、剂量、提示词），用 prefill 重放重建，误差 1.1–1.5%。**"把不可复现的中间态变成可重放"**——这个思路对我们记忆实验同样适用。

### 3.4 抄不了的

- **跑不起来**：sweep 需要 CUDA 13 + 4090 pod + vLLM steering fork；我们的 4060 8GB 不在范围里。Qwen3.5-4B bf16 本身就要 8GB 显存。
- **llama.cpp 没有逐神经元钩子**：想在元亨身上做 steering，得走 transformers/CPU 路径另搭一套，成本远高于收益。
- 无 LICENSE：只能读，不能搬代码。

---

## 4. 一句话结论

**这不是一个能装进 YHLZ 的工具，是一篇值得读的研究日志 + 一套该抄的评估纪律。**

最值得拿走的不是"神经元能干什么"，而是他们反复在做的那件事：**任何"我改了它，所以它变了"的说法，都必须先过随机对照和相对剂量这两关**——否则 83% 的"变化"只是噪声。

---

*已读：README（4.2k）、NOTES（4.5k，含 Goodfire 文章与 tawny-owl 佐证）、research_log（25.4k，到 2026-10-21 polish pass）。图片 `explorer.png` 未看（5MB，视觉界面）。*
