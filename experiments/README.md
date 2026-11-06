# 模型实验站（experiments/）

> 设计：`docs/研究/模型实验站_设计_v1.md`
> 一句话：**一次只变一个因子，起冷态实例，跑固定题库，存带哈希的记录。**

## 用法

```bash
cd YH/experiments

# 1. 干跑：只看会下发什么命令
python station.py run --config configs/base_private.json --dry-run

# 2. 从基线生成变体（只变一个因子）
python station.py plan --base configs/base_private.json --factor F1 \
    --values "v9t7:1.0;v9t7:0.7+v9t8:0.3;v9t8:1.0"

# 3. 真跑
python station.py run --config configs/base-f12.json

# 4. 看结果
python station.py list
python station.py compare base-f11 base-f12 base-f13
```

## 因子

| 代号 | 因子 | 配置位置 | 说明 |
|---|---|---|---|
| F1 | 适配器 | `model.lora[]` | 单 LoRA 或 `--lora-scaled` 叠加 |
| F2 | control vector | `model.control_vector[]` | 带 `scale` 与 `layers` |
| F3 | 提示词 | `prompt.kind` | private / public |
| F4 | 采样 | `sampling` | temp / top_p / repeat_penalty / dry_multiplier |
| F5 | 语法 | `grammar` | GBNF（inline 或 file） |
| F6 | logit-bias | `logit_bias[]` | 用 `token_id`，不用词 |
| F7 | 数据 | 走打包，不在本站 | — |

## 坑（已修）

- **`--lora-scaled` / `--control-vector-scaled` 的路径不能带盘符冒号**：
  `C:\...:0.7` 会被当成 `FNAME:SCALE` 切断（台账 1074 同款）。
  站里统一用**相对 YH 的路径**，子进程 `cwd=YH`，DLL 从 `PATH` 找。

## 记录格式

`runs/<时间>-<id>.json`：`config_hash` / `backend` / `judge_version` / `server_cmd` /
每次 repeat 的 `ok/total/by_cat/gate/failed_ids` / `stability`。

**同配置可以直接对照 `config_hash`**；跨版本比分前先看 `judge_version`。
