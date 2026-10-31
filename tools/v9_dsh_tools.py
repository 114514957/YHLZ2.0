"""DSH（DeepSeek Harness）工具协议注册表（ledger 0902）。

老爹 2026-10-20：「未来和 deepseek harness 接轨」。
本表按 **DSH 实际暴露给 agent 的工具契约**建（不是猜的，是当前会话在用的那套），
名字、参数名、必填项都对齐；供训练数据与未来接入共用。

产出：data/tool_registry/dsh_tools_<date>.json（sha16 / 各族 / schema）
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "tool_registry"


def T(family, name, desc, props, required):
    return {"family": family, "name": name, "description": desc,
            "properties": props, "required": required}


S, I, B, A, O = "string", "integer", "boolean", "array", "object"

TOOLS = [
    # ── 文件读写 ──
    T("file", "read", "读 UTF-8 文本，返回带行号内容",
      {"file_path": S, "offset": I, "limit": I}, ["file_path"]),
    T("file", "write", "整文件写入（覆盖）", {"file_path": S, "content": S},
      ["file_path", "content"]),
    T("file", "edit", "按字面量替换编辑（old_string 必须唯一）",
      {"file_path": S, "old_string": S, "new_string": S,
       "replace_all": B, "sandbox_permissions": S, "justification": S},
      ["file_path", "old_string", "new_string"]),
    T("file", "glob", "按 glob 找文件（含隐藏/忽略文件）", {"pattern": S, "path": S},
      ["pattern"]),
    T("file", "grep", "按正则搜内容，返回行号", {"pattern": S, "path": S, "include": S},
      ["pattern"]),
    T("file", "working_directory", "读/切当前工作目录", {"cd": S}, []),
    # ── 命令 ──
    T("exec", "pwsh", "跑 PowerShell 命令（可后台）",
      {"command": S, "description": S, "workdir": S, "timeoutMs": I,
       "run_in_background": B, "sandbox_permissions": S, "justification": S},
      ["command", "description"]),
    # ── 任务/计划 ──
    T("plan", "todo_write", "维护任务清单（整表替换）",
      {"todos": A}, ["todos"]),
    T("plan", "create_goal", "建持久目标（跨轮自动续跑）",
      {"objective": S, "max_goal_rounds": I}, ["objective"]),
    T("plan", "get_goal", "读当前目标与 revision", {}, []),
    T("plan", "update_goal", "改/暂停/恢复/完成/阻塞目标",
      {"goal_id": S, "revision": I, "action": S, "objective": S,
       "blocked_reason": S, "max_goal_rounds": I},
      ["goal_id", "revision", "action"]),
    # ── 后台作业 ──
    T("job", "job_output", "读后台作业输出（可等待）",
      {"job_id": S, "wait": B, "timeout_ms": I}, ["job_id"]),
    T("job", "job_kill", "取消后台作业", {"job_id": S, "reason": S}, ["job_id"]),
    T("job", "job_list", "列后台作业", {}, []),
    # ── 子 agent ──
    T("agent", "subagent", "派独立子 agent 干自足任务",
      {"description": S, "prompt": S, "cwd": S}, ["description", "prompt"]),
    T("agent", "subagent_fork", "派继承上下文的子 agent", {"description": S, "prompt": S, "cwd": S},
      ["description", "prompt"]),
    T("agent", "send_message", "给子/父 agent 发消息", {"agent_id": S, "message": S},
      ["agent_id", "message"]),
    T("agent", "list_agents", "列子 agent 状态", {"scope": S}, []),
    T("agent", "interrupt_agent", "打断子 agent", {"agent_id": S}, ["agent_id"]),
    T("agent", "workflow", "跑多 agent 编排脚本（JS）",
      {"script": S, "meta": O, "args": O, "run_in_background": B}, ["script", "meta"]),
    # ── 网络 ──
    T("net", "web_search", "联网搜索（多查询合并）", {"queries": A}, ["queries"]),
    T("net", "web_fetch", "抓取 URL 并解码为文本", {"url": S}, ["url"]),
    # ── 定时 ──
    T("schedule", "schedule_create", "建提醒（定时/间隔/每日/每周/cron）",
      {"prompt": S, "title": S, "after_seconds": I, "every_seconds": I,
       "at": O, "daily": O, "weekly": O, "cron": O}, ["prompt", "title"]),
    T("schedule", "schedule_list", "列本会话提醒", {}, []),
    T("schedule", "schedule_update", "改提醒（保留 id）", {"id": S, "title": S, "prompt": S}, ["id"]),
    T("schedule", "schedule_delete", "删提醒", {"id": S}, ["id"]),
    # ── 交互/交付 ──
    T("ui", "ask_user_question", "需要用户选择/确认时提问",
      {"questions": A}, ["questions"]),
    T("ui", "present", "把文件声明为最终交付", {"files": A}, ["files"]),
    T("ui", "exit_plan_mode", "提交计划请求批准（仅计划模式）", {"plan": S}, ["plan"]),
    # ── 技能 ──
    T("skill", "skill", "加载技能全文说明", {"name": S}, ["name"]),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fam = {}
    for t in TOOLS:
        fam.setdefault(t["family"], 0)
        fam[t["family"]] += 1
    blob = json.dumps(TOOLS, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(blob.encode()).hexdigest()[:16]
    stamp = time.strftime("%Y%m%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"dsh_tools_{stamp}_{sha}.json"
    data = {"snapshot_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sha16": sha,
            "count": len(TOOLS), "families": fam, "tools": TOOLS}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "dsh_tools_latest.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"count": len(TOOLS), "families": fam, "sha16": sha,
                      "out": str(out.relative_to(ROOT))}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
