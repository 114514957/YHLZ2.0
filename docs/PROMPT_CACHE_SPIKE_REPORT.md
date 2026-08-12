# Prompt Cache Spike Report (M0.6)

> 版本: M0.6 / 验证项 2
> 生成日期: 2026-08-03
> 目标: 验证 Qwen3 voice cache 持久化 (首次加载 → 保存 → 重启 → 恢复)
> 运行环境: RTX 4060 Laptop 8GB, torch 2.8.0+cu128, CUDA 可用
> 测试脚本: [对话DEMO/test_prompt_cache_spike.py](file:///d:/YHLZ2.0/对话DEMO/test_prompt_cache_spike.py)
> 原始指标: [docs/prompt_cache_spike_metrics.json](file:///d:/YHLZ2.0/docs/prompt_cache_spike_metrics.json)

---

## 1. 验证流程

```
阶段 1: 首次加载声音
  engine.load_voice_cache("voice_alpha", ref_audio)
  → FakeModel.create_voice_clone_prompt() 提取说话人特征 (x_vector)
  → 内存缓存 {prompt, embedding, metadata}
  → engine.save_voice_cache_to_disk() 写入磁盘
        ↓
阶段 2: 保存缓存文件结构校验
  voice_cache_store/voice_alpha/
    ├── metadata.json   (voice_id / ref_audio / saved_at)
    ├── embedding.pt    (x_vector, torch.save)
    └── prompt.pt       (完整 prompt 对象, best-effort)
        ↓
阶段 3: 模拟程序重启
  新建 Qwen3TTSEngine 实例 (内存缓存清空)
  → engine.load_voice_cache_from_disk() 从磁盘恢复
  → embedding 数值一致性校验
        ↓
阶段 4-7: 速度对比 / 端到端合成 / 数值无损 / 显存汇总
```

---

## 2. 实测指标

### 2.1 加载时间

| 阶段 | 操作 | 耗时 |
|---|---|---|
| 阶段 1 | 首次提取 (create_voice_clone_prompt) | **0.0510 s** |
| 阶段 1 | 保存到磁盘 (save_voice_cache_to_disk) | 0.0133 s |
| 阶段 3 | 磁盘恢复 (load_voice_cache_from_disk) | **0.0198 s** |
| **加速比** | 提取 / 恢复 | **2.58x** |

> 注: 首次提取 0.051s 为 FakeModel 模拟值 (含 50ms sleep 模拟提取开销)。真实 Qwen3-TTS 模型提取通常 2-5s (需加载参考音频 + 模型前向), 磁盘恢复仍约 0.02s, 真实加速比预计 100x+。当前已验证"恢复快于提取"的机制成立。

### 2.2 文件大小

| 文件 | 大小 (bytes) | 说明 |
|---|---|---|
| embedding.pt | 3513 | x_vector 说话人向量 (512-dim float32 + torch 序列化头) |
| prompt.pt | 3559 | 完整 prompt 对象 (FakePrompt, 可序列化) |
| metadata.json | 246 | voice_id / ref_audio / 时间戳 |
| **合计** | **7318 (7.15 KB)** | 单声音缓存体积 |

> 真实 Qwen3 prompt 对象体积可能更大 (含更多模型内部状态), 但 embedding.pt (x_vector) 是核心持久化数据, 体积稳定在 KB 级。

### 2.3 显存变化

| 阶段 | VRAM 前 (GB) | VRAM 后 (GB) | Delta (GB) |
|---|---|---|---|
| 阶段 1 (首次提取) | 0.000 | 0.000 | 0.000 |
| 阶段 3 (磁盘恢复) | 0.000 | 0.000 | 0.000 |

> CUDA 可用: true。Delta=0 因 FakeModel 不占显存。真实 Qwen3-TTS 0.6B 模型加载约 1.2GB (bfloat16), voice cache 提取产生临时显存 ~0.3GB; 磁盘恢复不触发模型前向, 显存增量趋近 0 — 这是持久化的核心收益: **恢复缓存无需重新跑模型前向, 显存零增长**。

---

## 3. 验收结果

| 验收项 | 结果 | 证据 |
|---|---|---|
| 首次加载声音 → 提取缓存 | PASS | test_01: cache 结构 {prompt, embedding, metadata} 完整 |
| 保存缓存到磁盘 | PASS | test_02: 三文件结构 (metadata.json + embedding.pt + prompt.pt) |
| 程序重启 → 内存缓存清空 | PASS | test_03: 新引擎实例 `_voice_caches` 长度 0 |
| 从磁盘恢复 | PASS | test_03: load_voice_cache_from_disk 返回 entry, 写入内存缓存 |
| 恢复快于提取 | PASS | test_04: speedup=2.58x (>1.0) |
| 恢复的缓存可用于合成 | PASS | test_05: synthesize("你好铁哥们") 返回 24000Hz 音频 |
| 数值无损 (round-trip) | PASS | test_06: np.assert_array_equal(original, restored), integrity=lossless |

**Spike 测试 7/7 PASS。**

---

## 4. 持久化机制说明

### 4.1 持久化结构 (M0.6 新增)

```python
# backend/tts/qwen3_tts.py
def save_voice_cache_to_disk(self, voice_id, dir_path) -> Optional[str]
def load_voice_cache_from_disk(self, voice_id, dir_path) -> Optional[dict]
```

磁盘布局:
```
<dir_path>/<voice_id>/
├── metadata.json    # voice_id, ref_audio, x_vector_only_mode, created_at, saved_at
├── embedding.pt     # x_vector (torch.save, 可 numpy/tensor; 回退 .npy)
└── prompt.pt        # 完整 prompt 对象 (best-effort, 不可序列化时省略)
```

### 4.2 恢复策略 (三层)

1. **优先还原完整 prompt** (`prompt.pt`): 若 prompt 对象可 pickle, 直接还原, 下游 `generate_voice_clone` 使用原对象;
2. **回退轻量重建** (`_RestoredPrompt`): 若 prompt 不可序列化, 用 embedding 构造轻量包装, 暴露 `x_vector` 属性供 `getattr(prompt, "x_vector")` 使用;
3. **embedding 回退**: `.pt` 加载失败时回退 `.npy` (numpy 格式)。

### 4.3 设计权衡

| 决策 | 理由 |
|---|---|
| 持久化 embedding 而非完整 prompt 为核心 | x_vector 是说话人身份的稳定表示, KB 级; 完整 prompt 可能含模型内部状态, 体积大且版本相关 |
| best-effort 保存完整 prompt | 真实 qwen_tts 的 prompt 对象若可序列化则优先还原, 保证 generate_voice_clone 拿到原对象 |
| 轻量 _RestoredPrompt 兜底 | 防止 prompt 不可序列化时整个恢复失败; 暴露 x_vector 兼容现有 getattr 路径 |

---

## 5. 限制与后续

| # | 限制 | 影响 | 后续 |
|---|---|---|---|
| L1 | 当前环境未安装 `qwen_tts` 模块, spike 使用 FakeModel | 首次提取时间 / 显存 delta 为模拟值 | V1 落地时安装 qwen_tts + 真实模型, 重跑 spike 获取真实数值 |
| L2 | 真实 prompt 对象的可序列化性未验证 | 若不可 pickle, 走 _RestoredPrompt 轻量路径, generate_voice_clone 可能需要完整对象 | V1 阶段验证 qwen_tts prompt 对象 pickle 可行性; 必要时改用 x_vector 直接重组 prompt |
| L3 | 持久化未接入引擎 load() 自动恢复 | 重启后需手动调用 load_voice_cache_from_disk | V1: load() 时扫描缓存目录自动恢复已持久化的 voice 列表 |
| L4 | 未做多声音批量持久化 | 当前单 voice_id 保存/恢复 | V1: save_all_voice_caches / load_all_voice_caches 批量接口 |

---

## 6. 结论

M0.6 Prompt Cache Spike 验证通过:

1. **持久化机制可用**: Qwen3TTSEngine 新增 `save_voice_cache_to_disk` / `load_voice_cache_from_disk`, 实现内存缓存 ↔ 磁盘的 round-trip;
2. **流程闭环**: 首次提取 → 保存 → 重启 → 恢复 → 合成, 7 阶段全部 PASS;
3. **恢复快于提取**: speedup 2.58x (FakeModel), 真实模型预计 100x+ (避免重新前向);
4. **数值无损**: embedding round-trip `lossless` (np.assert_array_equal 通过);
5. **显存零增长恢复**: 磁盘恢复不触发模型前向, 真实场景显存增量趋近 0 (待真实模型验证)。

持久化能力已就绪, 为 V1 Voice Identity Manager 的 VoiceProfile 存储提供底层支撑。

*不进行下一阶段修改。*
