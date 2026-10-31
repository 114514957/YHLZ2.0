# Phase7：DeepSeek 兼容 MCP 客户端回归执行报告

日期：2026-09-28。性质：已有证据复核 + 本轮本地 stdio 接入复核；不是 DeepSeek 界面操作实证。

## 1. 一句话结论

**项目本地 MCP 服务可以被标准 stdio 客户端调用；不能据此宣布所有工作 Agent 已配置成功，也不能宣布语音端到端或全双工已完成。**

本次接力没有重新跑既有两连接批次，而是核对其 JSON 证据，并另建一个本地 stdio 会话确认 tools/list、system_time、ledger_search 可调用。后者返回本地时间 2026-09-28 19:09:33。

## 2. 证据与结果

- 探针：`C:\Users\ACE_WAN——PROJECT\YHLZ\tools\voice_ledger_mcp_probe.py`。
- 双连接原始证据：`C:\Users\ACE_WAN——PROJECT\YHLZ\cache\voice_metrics\ledger_mcp_phase7_client.json`。
- 该证据 SHA-256：`13bfe7d5bf8d914f7a2efd088df7f6e2ece1a0fa1f89d414eb26d83855fe461a`。
- `passed=true`、`two_independent_connections_ok=true`、`sensitive_information_found=false`。
- 两个独立会话完成 initialize、tools/list、system_time、ledger_search、memory_recall；非法空查询按预期失败，随后 system_time 恢复成功。
- 上述敏感内容检测只是探针所检查报告范围的结果，不是整个仓库的安全审计。

- 连接 1：server={'name': 'yhlz', 'version': '1.29.1'}；passed=True；tools=diary_append, diary_read, file_list, file_read, ledger_search, memory_recall, memory_save, system_time, web_fetch, web_search。
- 连接 2：server={'name': 'yhlz', 'version': '1.29.1'}；passed=True；tools=diary_append, diary_read, file_list, file_read, ledger_search, memory_recall, memory_save, system_time, web_fetch, web_search。

## 3. 工作 Agent 适配器怎么接

这里的“工具适配器”与“音频播放适配器”不是同一个问题。

正确的工具路径是：工作 Agent 的 MCP 客户端 → stdio 子进程 → 项目的 yhlz MCP server → 对应工具处理器。不要把 MCP 工具名直接当成 PowerShell 命令，也不要用记忆/日记工具冒充台账写入。

本地已验证的启动参数是：

```json
{
  "command": "C:\\Users\\ACE_WAN——PROJECT\\YHLZ\\.venv\\Scripts\\python.exe",
  "args": ["-B", "C:\\Users\\ACE_WAN——PROJECT\\YHLZ\\tools\\yhlz_mcp_server.py"],
  "cwd": "C:\\Users\\ACE_WAN——PROJECT\\YHLZ"
}
```

这只是已验证的 stdio 启动参数，不是臆造某个 DeepSeek 客户端的完整配置文件。由实际宿主的配置格式包裹它，随后在该宿主中分别调用三个工具验收。

当前工具层真实名称为 `ledger_search`、`memory_recall`、`system_time` 等；宿主显示的 `yhlz_` 前缀可能是命名空间，是否添加以该宿主 tools/list 为准。

错误分流：

| 现象 | 应处理的位置 | 不应做什么 |
|---|---|---|
| unknown MCP server yhlz | 宿主是否注册该 server、进程是否重载配置 | 不改业务语音模块来“修复”注册 |
| 子进程起不来 | 解释器、脚本绝对路径、cwd、依赖环境 | 不误用系统 Python 替代项目 .venv |
| 工具缺失或参数错误 | 读取该会话 tools/list 的真实 schema | 不猜 ledger_append 存在 |
| 工具可调用但结果偏旧 | 检索排序、索引与精确命中验收 | 不把契约通过当作检索质量通过 |

接力前曾观察到当前宿主未注册 `yhlz`；本地 stdio 可用不能自动修复宿主注册。本轮未修改 DeepSeek 或其他宿主的配置文件。

## 4. 台账查询与写入的边界

所有台账检索均通过 MCP；没有直接读取或 grep 台账全文。本轮 `ledger_search("固定文本", limit=3)` 返回的来源包括：

- `ledger:0143:2111`：固定中文测试文本决定。
- `ledger:0089:1314`：历史 ASR 样本指标；不能替代本轮硬件验收。
- `ledger:0083:1243`：历史输入端口/资产边界；不能据此判定当前模型是否可加载。

日期或编号查询的命中精度尚未单独验收。没有可靠依据确认“最新一条记录号”，不猜下一条编号。

**本轮 tools/list 没有 ledger_append。重要结果尚未正式追加到 `docs\上下文台账.md`，本交付附待追加片段；待获得可靠追加入口后必须写入唯一事实源，并用 MCP 再检索确认记录号。** memory_save、diary_append 不是替代入口。

## 5. 下一步验收清单

1. 实际工作 Agent 宿主注册同一 stdio 服务，记录该宿主三工具的真实调用结果。
2. 检查一次非法参数后，同一连接仍能调用 system_time。
3. 用已知记录号/关键词做精确命中样例，单列检索质量报告。
4. 补上正式台账追加流程；要求编号递增、并发保护、失败不宣称成功、追加后 MCP 能检索到。
5. 音频验收按 Phase8 执行单推进；本报告不放行麦克风常开或全双工认证。

## 6. 明确未做

未在 DeepSeek UI 中操作；未打开声卡音频流；未播放声音；未打开麦克风；未加载真实语音模型；未证明扬声器/蓝牙声音、物理停止、AEC 或全双工。不得把以上未做项写成“通过”。
