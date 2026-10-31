"""Agent harness 工具族注册表（ledger 0900）。

背景：老爹 2026-10-20「工具不在局限，按照未来的 agent harness 做」。
上一轮"工具必须真实"解决的是**编造工具名**（search_notes 之类）；这轮把范围从
"元亨当前 43 个工具"扩到**未来 harness 会真实施加的能力族**——名字全部取自
真实生态（MCP filesystem / git / shell / sqlite / http），不是编的。

约定：
  · 元亨自有工具保留原名（file_read / memory_recall …）
  · 通用能力用 `族.动作` 命名（fs.read_file / git.status / shell.run / sqlite.query …）
  · MCP 服务器工具用 `mcp__<server>__<tool>`（MCP 规范命名）

产出：data/tool_registry/harness_tools_<date>.json（含 sha16、族、参数 schema）
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "tool_registry"


def T(family: str, name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"family": family, "name": name, "description": desc,
            "properties": props, "required": required}


S, I, B, A = ("string",), ("integer",), ("boolean",), ("array",)

TOOLS = [
    # ── 文件系统（MCP filesystem 语义） ──
    T("fs", "fs.read_file", "读文本文件", {"path": S, "max_bytes": I}, ["path"]),
    T("fs", "fs.write_file", "写文本文件（覆盖）", {"path": S, "content": S}, ["path", "content"]),
    T("fs", "fs.edit_file", "按片段替换编辑文件", {"path": S, "old": S, "new": S}, ["path", "old", "new"]),
    T("fs", "fs.list_dir", "列目录", {"path": S, "recursive": B}, ["path"]),
    T("fs", "fs.glob", "按模式找文件", {"pattern": S, "root": S}, ["pattern"]),
    T("fs", "fs.grep", "按正则搜内容", {"pattern": S, "path": S, "include": S}, ["pattern"]),
    T("fs", "fs.stat", "文件元信息", {"path": S}, ["path"]),
    T("fs", "fs.mkdir", "建目录", {"path": S}, ["path"]),
    T("fs", "fs.remove", "删文件/目录", {"path": S, "recursive": B}, ["path"]),
    T("fs", "fs.move", "移动/重命名", {"src": S, "dst": S}, ["src", "dst"]),
    # ── shell / 进程 ──
    T("shell", "shell.run", "执行命令并取输出", {"command": S, "cwd": S, "timeout_ms": I}, ["command"]),
    T("shell", "shell.background", "后台起进程", {"command": S, "cwd": S}, ["command"]),
    T("shell", "shell.kill", "终止进程", {"pid": I}, ["pid"]),
    T("shell", "shell.env", "读环境变量", {"name": S}, []),
    # ── git ──
    T("git", "git.status", "工作区状态", {"cwd": S}, ["cwd"]),
    T("git", "git.diff", "查看差异", {"cwd": S, "path": S, "staged": B}, ["cwd"]),
    T("git", "git.log", "提交历史", {"cwd": S, "limit": I}, ["cwd"]),
    T("git", "git.add", "暂存文件", {"cwd": S, "paths": A}, ["cwd", "paths"]),
    T("git", "git.commit", "提交", {"cwd": S, "message": S}, ["cwd", "message"]),
    T("git", "git.checkout", "切分支/还原", {"cwd": S, "ref": S}, ["cwd", "ref"]),
    T("git", "git.branch", "分支操作", {"cwd": S, "action": S, "name": S}, ["cwd", "action"]),
    # ── 网络 ──
    T("net", "net.http_get", "GET 请求", {"url": S, "headers": S, "timeout_ms": I}, ["url"]),
    T("net", "net.http_post", "POST 请求", {"url": S, "body": S, "headers": S}, ["url"]),
    T("net", "net.fetch_text", "抓页面转文本", {"url": S, "max_chars": I}, ["url"]),
    T("net", "net.search", "联网搜索", {"query": S, "top_k": I}, ["query"]),
    # ── 数据库 ──
    T("db", "sqlite.query", "只读查询", {"db_path": S, "sql": S, "params": S}, ["db_path", "sql"]),
    T("db", "sqlite.exec", "写操作", {"db_path": S, "sql": S}, ["db_path", "sql"]),
    T("db", "sqlite.tables", "列全部表", {"db_path": S}, ["db_path"]),
    T("db", "sqlite.schema", "看表结构", {"db_path": S, "table": S}, ["db_path", "table"]),
    # ── 代码执行 ──
    T("code", "code.python", "跑 Python 片段", {"code": S, "timeout_ms": I}, ["code"]),
    T("code", "code.node", "跑 Node 片段", {"code": S, "timeout_ms": I}, ["code"]),
    T("code", "code.test", "跑测试命令", {"command": S, "cwd": S}, ["command"]),
    T("code", "code.lint", "静态检查", {"path": S, "tool": S}, ["path"]),
    # ── 计划 / 任务（harness 编排） ──
    T("plan", "plan.create", "拆解任务清单", {"goal": S, "max_steps": I}, ["goal"]),
    T("plan", "plan.update", "更新某步状态", {"step_id": S, "status": S, "note": S}, ["step_id", "status"]),
    T("plan", "task.delegate", "派子 agent 干子任务", {"goal": S, "tools": A, "budget_steps": I}, ["goal"]),
    T("plan", "task.collect", "收子 agent 结果", {"task_id": S}, ["task_id"]),
    T("plan", "task.cancel", "取消子任务", {"task_id": S, "reason": S}, ["task_id"]),
    # ── 权限 / 审批（harness 安全边界） ──
    T("guard", "guard.confirm", "高危操作前请求确认", {"action": S, "detail": S}, ["action"]),
    T("guard", "guard.allowlist", "查/改白名单", {"action": S, "entry": S}, ["action"]),
    T("guard", "guard.audit", "读审计日志", {"limit": I, "since": S}, []),
    # ── 记忆 / 台账（元亨自有，保留原名对照） ──
    T("mem", "memory.recall", "检索记忆", {"query": S, "top_k": I}, ["query"]),
    T("mem", "memory.save", "写记忆", {"text": S, "tags": A}, ["text"]),
    T("mem", "ledger.append", "追加台账", {"title": S, "body": S}, ["title", "body"]),
    T("mem", "ledger.query", "查台账", {"query": S, "limit": I}, ["query"]),
    # ── MCP 命名约定（未来接服务器时直接用） ──
    T("mcp", "mcp__filesystem__read_file", "MCP: 读文件", {"path": S}, ["path"]),
    T("mcp", "mcp__filesystem__list_directory", "MCP: 列目录", {"path": S}, ["path"]),
    T("mcp", "mcp__github__create_issue", "MCP: 建 issue", {"repo": S, "title": S, "body": S}, ["repo", "title"]),
    T("mcp", "mcp__github__list_prs", "MCP: 列 PR", {"repo": S, "state": S}, ["repo"]),
    T("mcp", "mcp__fetch__fetch", "MCP: 抓网页", {"url": S}, ["url"]),
    T("mcp", "mcp__sqlite__query", "MCP: SQL 查询", {"db": S, "sql": S}, ["db", "sql"]),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fams = {}
    for t in TOOLS:
        fams.setdefault(t["family"], []).append(t["name"])
    blob = json.dumps(TOOLS, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(blob.encode()).hexdigest()[:16]
    stamp = time.strftime("%Y%m%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"harness_tools_{stamp}_{sha}.json"
    data = {"snapshot_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sha16": sha,
            "count": len(TOOLS), "families": {k: len(v) for k, v in fams.items()},
            "tools": TOOLS}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "harness_tools_latest.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"count": len(TOOLS), "families": data["families"],
                      "sha16": sha, "out": str(out.relative_to(ROOT))},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
