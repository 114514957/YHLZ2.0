# YHLZ V4.5 会话交接文档（2026-08-06）

> 上下文严重压缩，新建会话前请先完整阅读本文档。项目根：`D:\YHLZ2.0`。
> 工作区：`D:\YHLZ2.0\backend\embodied\`；venv 解释器：`D:\YHLZ2.0\venv\Scripts\python.exe`。

---

## 0. 当前最高优先级（必须先处理）

**4 个测试文件被 PowerShell 编码事故损坏，尚未完全恢复**：

| 文件 | 现状 | 剩余 `?` |
|---|---|---|
| `backend\embodied\tests\test_service.py` | 合法 UTF-8，语法错误，部分 mojibake | 18 |
| `backend\embodied\tests\test_report.py` | 合法 UTF-8，语法错误，部分 mojibake | 2 |
| `backend\embodied\tests\test_reasoning_integration.py` | 合法 UTF-8，语法错误，部分 mojibake | 25 |
| `backend\embodied\tests\test_strategy_scheduler.py` | 合法 UTF-8，语法错误，部分 mojibake | 5 |

- 全量测试现状：`Ran 792 tests, FAILED (errors=4)`（4 个文件 ImportError: UnicodeDecodeError 已解决，现为 SyntaxError）
- **恢复有救**：4 个文件的 pyc 缓存完好（mtime 早于损坏时间），内含全部原始字符串常量

---

## 1. 任务背景与目标

按 `D:\YHLZ2.0\下载物象\任务计划\三阶段\v4.5.txt` 实现 **V4.5 元策略管理（Meta Strategy Management）**，遵循 `YHLZ_现状开发习惯Prompt.md`（实现→测试→验收报告→返回下一阶段 Prompt）。

**硬约束**：纯规则+统计+阈值+可解释排序；禁止 NN 训练/黑盒；治理动作只影响 策略表→审计日志→体系快照；不写 Agent Memory；不绕过 Permission。版本号必须为 `"4.5.0"`。

---

## 2. 已完成实现（代码已就绪，只差测试验证）

### 2.1 数据层 `backend/embodied/experience/policy.py`
- 新增 `POLICY_STATUS_DELETED = "deleted"`，加入 `POLICY_STATUSES`
- 新增字段 `family_id`、`deleted_at`；`to_dict/from_dict/create` 支持
- `set_status` 同步 `deleted_at`
- 新增方法：`delete_policy()`、`purge_policy()`、`recycle_bin()`、`all_versions()`、`rollback_policy()`、`set_family()`、`families()`
- `restore_policy` 支持 deleted → active；`candidates` 排除 deleted
- `__all__` 已更新；docstring 头改 V4.5

### 2.2 审计 `backend/embodied/strategy/audit.py`
- V4.5 动作白名单新增：consolidate / split / rollback / purge / resolve_conflict / archive_redundant / apply_archival
- `audit_policy_log(limit, action=None)` 支持动作过滤

### 2.3 配置 `backend/config.py`
- `embodied_policy_min_archive_age_days = 30`
- `embodied_policy_min_archive_hit_rate = 0.3`

### 2.4 新建治理包 `backend/embodied/governance/`
| 文件 | 内容 |
|---|---|
| `__init__.py` | `StrategyGovernance` 门面类（Service 唯一接入点） |
| `overview.py` | `StrategySystemOverview`：strategy_system_overview / strategy_system_report / 矩阵 / 一致性检查；`OverviewError` |
| `governance.py` | `PolicyGovernance`：冗余/冲突/低效归档（人工确认 apply_archival）/回收站；`GovernanceError` |
| `evolution.py` | `PolicyEvolution`：同化 consolidate / 分裂 split / 版本比较 / 回滚（仅 regression）；`EvolutionError` |
| `health.py` | `PolicyHealthCheck`：health_check / scene_coverage（引用 `backend.embodied.environment.mock.SCENES`）；`HealthError` |
| `dry_run.py` | `GovernanceDryRun` + `SystemSnapshot` + `GOVERNANCE_DRY_RUN_ACTIONS`：统一干跑入口与保护规则检查；`DryRunError` |

### 2.5 服务层 `backend/embodied/service.py`
- 导入 `StrategyGovernance`；`_governance` 字段 + `set_governance()` + 懒加载 `governance` property；`initialize()` 用 config 构造
- 新增 21 个 V4.5 API：strategy_system_overview / strategy_system_report / redundant_policies / archive_redundant_policies / conflicting_policies / resolve_conflicts / archive_candidates / apply_archival / delete_policy / restore_policy / purge_policy / recycle_bin / consolidate_similar_policies / split_policy / compare_policy_versions / rollback_policy / policy_families / policy_health_check / scene_coverage / governance_dry_run / audit_system_export
- `audit_policy_log` 增加 `action` 参数
- `report()` / `status()` 版本升 `"4.5.0"` 并含 governance 段

### 2.6 包入口 `backend/embodied/__init__.py`
- docstring 改 V4.5；导入 governance 全部符号；`__version__ = "4.5.0"`；`__all__` 更新

### 2.7 已验证
- 导入检查通过：`OK 4.5.0`
- 修复过 `governance.py` apply_archival 中 f-string 内多行 `next()` 语法错误（Python 3.11 不支持）

---

## 3. 事故经过（重要教训）

**直接原因**：用 PowerShell 批量改版本字符串时把 UTF-8 文件写坏：
```powershell
(Get-Content $_ -Raw) -replace '"4\.4\.0"','"4.5.0"' | Set-Content $_ -NoNewline
```
`Get-Content` 以系统 ANSI（GBK/代码页 936）解码读取，`Set-Content` 同样以 GBK 写回。UTF-8 中文字节流按 GBK 成对解码 → 无效对替换为 `?` → 写回后 `?` 为 0x3F，部分字节丢失。

**教训**：**本机 PowerShell 5.1 默认编码是 GB2312(936)**。任何涉及读写 UTF-8 中文文件的操作一律用 Python 完成，禁止 `Get-Content/Set-Content/Out-File` 无 `-Encoding UTF8` 使用。

---

## 4. 恢复技术分析（已实证）

### 4.1 损坏机制（已验证）
- 测试：`gbk_test.ps1`（在临时目录）证明 .NET 936 行为：
  - 有效 GBK 对（如 E7 BB）roundtrip 不变
  - **无效序列 → 整个序列替换为单个 `?`(0x3F)**，可能吞掉相邻 ASCII 字节
  - 例：`绝(E7 BB 9D) + 三引号(22 22 22)` → mojibake `[E7BB]?` + `""`，**丢了一个引号** → 这是语法错误根因
  - 例：`默认拒绝` 全有效对 → 完好无损
- 结论：损坏不可仅靠反向解码恢复（信息已丢失），**必须借助 pyc 中的原始字符串**

### 4.2 恢复方案（已走通 60%）
流程：pyc(原始字符串) → base64 → PowerShell(.NET 936) 生成 mojibake → 在损坏文件中查替换。

已创建脚本（都在 `C:\Users\lenovo\AppData\Local\Temp\opencode\`）：
| 脚本 | 作用 |
|---|---|
| `extract_strings2.py` | 从 4 个 pyc 提取全部 str 常量 → base64 每行一个存 `{name}.strings.txt` |
| `recover2.ps1` | 读损坏文件→936 解码→对每个字符串算 936 往返 mojibake→按长度降序替换→UTF-8 写回 |
| `test_match2.py` | 验证 docstring 匹配（**已验证：mojibake 能在文件中找到，FOUND: True**） |
| `sim.ps1` / `doc_b64.txt` | 配合 test_match2 的辅助 |
| `gbk_test.ps1` | .NET 936 行为验证 |
| `check_triple.py` | 三引号配对检查（发现 docstring 未闭合） |
| `extract_strings.py` | 第一版（JSON 版，弃用，PS ConvertFrom-Json 有坑） |

### 4.3 第一轮恢复结果与遗留问题
- 4 个文件已恢复为**合法 UTF-8**（无 UnicodeDecodeError），部分短字符串已还原
- 遗留问题 A：**长 docstring 没匹配上** —— recover2.ps1 只用了 pyc 原始字符串（`\n` 换行），而文件是 CRLF（`\r\n`）。**已验证修复方式**：用 `doc.replace("\n","\r\n")` 后能匹配（test_match2.py 证明）。recover2.ps1 需加 CRLF 变体
- 遗留问题 B：**吞引号导致三引号不闭合** → `invalid character '→' (U+2192)` 等 SyntaxError（`"""` 变 `""`，docstring 内容裸露到代码区）
- 遗留问题 C：剩余 `?` 主要分布在**注释**里（不影响执行，可接受保留）与少量字符串尾部

### 4.4 下一步恢复建议（推荐顺序）
1. **先备份**当前 4 个半恢复文件到临时目录（`*.bak`）
2. 改进 `recover2.ps1`：对每个字符串同时尝试 `s` 和 `s.replace("\n","\r\n")` 两个变体（替换时按 mojibake 长度降序、长串优先）
3. 重新跑恢复后，逐个文件 `compile()` 检查语法
4. 对剩余 SyntaxError 行（多为三引号被吞一个引号），用 Read/Edit 手动修复（上下文明显：`""` 应为 `"""`）
5. 对剩余 `?`：优先确认是否在注释（保留无害）；在字符串字面量内的用 pyc 内容修复
6. 最后跑 `python -m py_compile` 全绿后，再改版本断言（**用 Python，禁止 PowerShell**）
7. 检查 4 个文件里 6 处 `"4.4.0"` → `"4.5.0"` 断言更新（这就是当初触发事故的修改，恢复后仍需用 Python 完成）

---

## 5. 恢复完成后待办（V4.5 剩余工作）

1. 更新 6 处版本断言 `"4.4.0"` → `"4.5.0"`（原 929 套件里 assertEqual 版本的地方，改 Python 脚本批量替换）
2. 编写 V4.5 治理专项测试（目标总用例 ≥950）：
   - overview/report、redundant/conflict、archive 人工确认、recycle（delete/restore/purge）、consolidate/split/compare/rollback、health/scene_coverage、dry_run 保护规则、audit 新动作过滤
3. 跑专项 → 跑全量：`venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests`（目标 Failed=0）
4. 产出验收报告（.md）+ 下一阶段 Prompt（.txt），按 YHLZ 开发习惯

---

## 6. 关键事实清单（供新会话直接使用）

- 基线：改动前全量 929 tests OK（V4.4.0）
- 6 处 `"4.4.0"` 断言在：test_reasoning_integration.py / test_report.py / test_service.py / test_strategy_scheduler.py
- pyc 时间戳（均早于损坏 23:34:33）：test_service 23:00:53、test_report 23:00:53、test_reasoning_integration 23:00:53、test_strategy_scheduler 23:08:32
- git 仓库只有 "Initial commit: YHLZ2.0 智能语音助手"，`backend/embodied/tests/` 未被跟踪，`git checkout` 无法恢复
- CPython 3.11 pyc 无法反编译（uncompyle6/decompyle3/pycdc 均不支持 3.11）
- 完好可作参考的同目录测试：test_strategy_lifecycle.py、test_strategy_audit.py、test_strategy_rank.py、test_strategy_trends.py
- 测试文件内常用中文 docstring 词汇（对照恢复用）：`默认关闭: 动作被拒绝`、`环境记忆`、`自适应规划`、`反馈分析 / 状态预测 / 具身上下文`、`目标闭环 (Observe → Think → Plan → Act → Evaluate)` 等
- PowerShell 936 关键行为：无效 GBK 对（lead 0x81-0xFE + trail 非 0x40-0xFE/0x7F）→ 整体替换为单个 `?`

---

## 7. 环境备忘

- OS: win32, PowerShell 5.1, 默认 ANSI=GB2312(936)
- Python: venv 3.11（pyc 头 16 字节：magic+flags+timestamp+size）
- 测试命令：`venv\Scripts\python.exe -m unittest discover -s backend.embodied.tests`
- 临时目录：`C:\Users\lenovo\AppData\Local\Temp\opencode\`（已预授权）
- 换行符：本项目测试文件为 CRLF（恢复匹配时必须用 `\r\n` 变体）
