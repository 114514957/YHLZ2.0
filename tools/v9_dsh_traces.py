"""DSH 风格 agent 轨迹生成（ledger 0902）。

按 DeepSeek Harness 的真实用法造轨迹（工具名/参数名与 DSH 契约一致）：
  plan_execute  todo_write → read → edit → pwsh(测试) → todo_write → present
  investigate   glob + grep 并行 → read → 汇报
  background    pwsh(run_in_background) → job_output(wait) → 收结果
  delegate      subagent → send_message → list_agents → 整合
  scheduled     schedule_create → schedule_list
  ask_choice    ask_user_question → 按选项继续
  research      web_search → web_fetch → write
  skillflow     skill → read → 照做

约束：工具名/参数 ⊂ DSH 注册表（30 项）；**留出 schedule / job 两族** 做零样本评测；
每条参数化；simulation/generated 标记。
产出 data/finetune/tool_dsh_v1.jsonl + dsh_traces_report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "tool_registry" / "dsh_tools_latest.json"
OUT = ROOT / "data" / "finetune" / "tool_dsh_v1.jsonl"
REPORT = ROOT / "cache" / "v9_materials_preparation" / "dsh_traces_report.json"

SYS = ("你在 DSH（DeepSeek Harness）里干活：可以读写文件、跑 pwsh、搜网页、派子 agent、"
       "建定时提醒、维护 todo。工具名与参数必须按 harness 契约；先计划再动手。"
       "说话像元亨：短、口语，不列清单。")

HOLDOUT_FAMILIES = ("schedule", "skill")

PATHS = ["tools/v9_pt_corpus.py", "docs/报告/素材总账_20261020.md", "data/pt/manifest.json",
         "backend/test_out_gate.py", "tools/v9_cot_audit.py", "README.md"]
CMDS = ["python -m unittest backend.test_out_gate", "python tools/v9_pt_corpus.py",
        "python tools/v9_materials_stats.py", "git status --short"]
GOALS = ["把素材总账更新到 v9v", "修掉工具轨迹的假工具名", "补一条 CoT 回归测试",
         "核对 manifest 的 token 数", "把 8k 切块写进说明"]


def call(name, args, cid):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


def sysm():
    return {"role": "system", "content": SYS}


def t_msg(name, content):
    return {"role": "tool", "name": name, "content": content}


def plan_execute(rng):
    p = rng.choice(PATHS)
    goal = rng.choice(GOALS)
    cmd = rng.choice(CMDS)
    return [sysm(),
            {"role": "user", "content": f"{goal}，做完把结果给我看"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("todo_write", {"todos": [
                 {"content": f"读 {p}", "status": "in_progress"},
                 {"content": "改一处", "status": "pending"},
                 {"content": "跑验证", "status": "pending"}]}, "c1")]},
            t_msg("todo_write", "updated"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("read", {"file_path": p, "limit": 120}, "c2")]},
            t_msg("read", f"1: …（{p} 前 120 行）"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("edit", {"file_path": p,
                                          "old_string": rng.choice(["--chunk 12000", "v9u", "155"]),
                                          "new_string": rng.choice(["--chunk 8000", "v9v", "399"])}, "c3")]},
            t_msg("edit", "edited"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("pwsh", {"command": cmd, "description": "跑验证"}, "c4")]},
            t_msg("pwsh", "[exit code: 0] ok"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("todo_write", {"todos": [
                 {"content": f"读 {p}", "status": "completed"},
                 {"content": "改一处", "status": "completed"},
                 {"content": "跑验证", "status": "completed"}]}, "c5")]},
            t_msg("todo_write", "updated"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("present", {"files": [
                 {"path": p, "description": "改动后的文件"}]}, "c6")]},
            t_msg("present", "presented"),
            {"role": "assistant", "content": "改完了，验证也过了，文件给你挂上了。"}]


def investigate(rng):
    pat = rng.choice(["load_tool_synth", "def judge", "HOLDOUT_FAMILIES", "tools_concept",
                      "schedule_create", "ask_user_question", "check(", "simulation"])
    root = rng.choice(["tools", "backend", "data", "docs", "config"])
    return [sysm(),
            {"role": "user", "content": f"查一下 {root} 里跟 {pat} 有关的都改过哪儿"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("glob", {"pattern": f"{root}/**/*.py"}, "c1"),
                            call("grep", {"pattern": pat, "path": root, "include": "*.py"}, "c2")]},
            t_msg("glob", f"{root}/a.py\n{root}/b.py"),
            t_msg("grep", f"{root}/a.py:42: {pat}"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("read", {"file_path": f"{root}/a.py", "offset": 36, "limit": 20}, "c3")]},
            t_msg("read", "42: …（命中处上下文）"),
            {"role": "assistant", "content": f"找到了：{root}/a.py 第 42 行是 {pat}，上下文我看过了，没别处引用。"}]


def background(rng):
    cmd = rng.choice(CMDS)
    jid = f"pwsh-{rng.randint(100000, 999999):x}"
    out = rng.choice(["[status: completed, exit code: 0] all passed",
                      "[status: completed, exit code: 0] 12 tests OK",
                      "[status: completed, exit code: 1] 1 failed"])
    return [sysm(),
            {"role": "user", "content": f"后台跑一下 {cmd}，跑完告诉我结果"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("pwsh", {"command": cmd, "description": "后台跑验证",
                                          "run_in_background": True,
                                          "timeoutMs": rng.choice([600000, 900000])}, "c1")]},
            t_msg("pwsh", f"started background job {jid}"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("job_output", {"job_id": jid, "wait": True,
                                                "timeout_ms": 600000}, "c2")]},
            t_msg("job_output", out),
            {"role": "assistant", "content": "跑完了：" + out.split("]")[-1].strip() + "，退出码见上。"}]


def delegate(rng):
    goal = rng.choice(GOALS)
    desc = rng.choice(["调研任务", "查资料", "独立核对", "先探路"])
    msg = rng.choice(["只查结论，别动手", "把证据链带回来", "别改文件，只读"])
    return [sysm(),
            {"role": "user", "content": f"这件事你派个人去查：{goal}"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("subagent", {"description": desc, "prompt": f"查清楚：{goal}"}, "c1")]},
            t_msg("subagent", "agent-77 started"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("list_agents", {"scope": "children"}, "c2")]},
            t_msg("list_agents", "agent-77 running"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("send_message", {"agent_id": "agent-77", "message": msg}, "c3")]},
            t_msg("send_message", "delivered"),
            {"role": "assistant", "content": "派下去了（agent-77），我让它只查结论不动手，回来我整合。"}]


def scheduled(rng):
    title = rng.choice(["每天汇总素材", "周报提醒", "双签提醒"])
    return [sysm(),
            {"role": "user", "content": f"给我起个提醒：{title}"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("schedule_create", {"prompt": f"提醒：{title}",
                                                     "title": title,
                                                     "daily": {"time": "09:00:00",
                                                               "time_zone": "Asia/Shanghai"}}, "c1")]},
            t_msg("schedule_create", "created schedule dsh-42"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("schedule_list", {}, "c2")]},
            t_msg("schedule_list", "dsh-42 每天 09:00 Asia/Shanghai"),
            {"role": "assistant", "content": "建好了，每天九点提醒你，列表里能看到。"}]


ASK_CASES = [("切块大小到底定多少，你拿个主意", "切块", "8k 还是 6k？",
              ["8k（长文比例达标）", "6k（块数更多但丢长文）"]),
             ("先签哪批，你定", "双签范围", "全签还是先签核心？",
              ["只签核心 1143", "全签 3121"]),
             ("上下文不够，怎么办", "跑评测", "提 16k 还是单开实例？",
              ["提到 16384", "单开评测实例"]),
             ("这批素材要不要全量重跑", "重跑范围", "全跑还是只跑变的？",
              ["只跑变化部分", "全量重跑"]),
             ("工具轨迹留哪些", "留出集", "留 schedule 还是留 git+db？",
              ["留 schedule+skill", "留 git+db"]),
             ("报告放哪", "输出", "docs/报告 还是 cache？",
              ["docs/报告", "cache"]),
             ("切块按多少字", "切块", "8k 还是 12k？", ["8k", "12k"]),
             ("用哪个模型跑评测", "模型", "gemma 还是 deepseek？",
              ["gemma-4-e4b", "deepseek 云端"])]


def ask_choice(rng):
    q, hdr, question, opts = rng.choice(ASK_CASES)
    return [sysm(),
            {"role": "user", "content": q},
            {"role": "assistant", "content": "",
             "tool_calls": [call("ask_user_question", {"questions": [
                 {"id": "q1", "header": hdr, "question": question,
                  "options": [{"label": x} for x in opts]}]}, "c1")]},
            t_msg("ask_user_question", "selected: " + opts[0]),
            {"role": "assistant", "content": "行，就按 " + opts[0] + " 来，我这就动。"}]


def research(rng):
    q = rng.choice(["ProLong 长上下文配比", "MCP filesystem server 配置", "DSH 工具协议"])
    return [sysm(),
            {"role": "user", "content": f"查一下 {q}，给我结论"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("web_search", {"queries": [q]}, "c1")]},
            t_msg("web_search", "1. 相关文档 A\n2. 相关文档 B"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("web_fetch", {"url": "https://example.com/doc"}, "c2")]},
            t_msg("web_fetch", "正文摘要…"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("write", {"file_path": "docs/报告/调研_" + str(rng.randint(1, 99)) + ".md",
                                           "content": f"# {q}\n\n结论…"}, "c3")]},
            t_msg("write", "written"),
            {"role": "assistant", "content": "查完了，结论写进报告，链接也留着。"}]


def skillflow(rng):
    sk = rng.choice(["office-xlsx", "office-docx", "office-pptx", "archify", "office-render"])
    sample = rng.choice(["docs/素材/黄金样本.md", "docs/素材/对话样本.md", "data/pt/manifest.json"])
    return [sysm(),
            {"role": "user", "content": f"用 {sk} 这套流程出个东西"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("skill", {"name": sk}, "c1")]},
            t_msg("skill", "（技能全文说明 …）"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("read", {"file_path": sample, "limit": 80}, "c2")]},
            t_msg("read", "1: …（素材）"),
            {"role": "assistant", "content": "技能读完了，按它的步骤来，我先取素材。"}]



def goal_loop(rng):
    goal = rng.choice(GOALS)
    return [sysm(),
            {"role": "user", "content": f"这件事要几轮才完，你盯着办：{goal}"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("create_goal", {"objective": goal,
                                                  "max_goal_rounds": rng.choice([4, 6, 8])}, "c1")]},
            t_msg("create_goal", "goal-9 created"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("todo_write", {"todos": [
                 {"content": "拆步骤", "status": "completed"},
                 {"content": "执行", "status": "in_progress"}]}, "c2")]},
            t_msg("todo_write", "updated"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("update_goal", {"goal_id": "goal-9", "revision": 1,
                                                  "action": "complete"}, "c3")]},
            t_msg("update_goal", "completed"),
            {"role": "assistant", "content": "目标挂上了，做完我就标完成。"}]


def job_cleanup(rng):
    jid = f"pwsh-{rng.randint(100000, 999999):x}"
    return [sysm(),
            {"role": "user", "content": "后台还有啥在跑？没用的清掉"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("job_list", {}, "c1")]},
            t_msg("job_list", f"{jid} running"),
            {"role": "assistant", "content": "",
             "tool_calls": [call("job_kill", {"job_id": jid, "reason": "不再需要"}, "c2")]},
            t_msg("job_kill", "requested cancellation"),
            {"role": "assistant", "content": "清掉了，别的一个没动。"}]


BUILDERS = [("plan_execute", plan_execute), ("investigate", investigate),
            ("background", background), ("delegate", delegate),
            ("scheduled", scheduled), ("ask_choice", ask_choice),
            ("research", research), ("skillflow", skillflow),
            ("goal_loop", goal_loop), ("job_cleanup", job_cleanup)]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=45)
    args = ap.parse_args()
    random.seed(20261023)
    snap = json.loads(SNAP.read_text(encoding="utf-8"))
    tools = {t["name"]: t for t in snap["tools"]}
    fam = {t["name"]: t["family"] for t in snap["tools"]}

    rows, seen, by_type = [], set(), Counter()
    for name, fn in BUILDERS:
        if fam.get(next(iter([t["name"] for t in snap["tools"] if False]), ""), "") in HOLDOUT_FAMILIES:
            pass
        n = 0
        for _ in range(args.per_type * 20):
            if n >= args.per_type:
                break
            msgs = fn(random)
            # 留出族：出现 schedule/job 的轨迹不进训练集
            used = [c["function"]["name"] for m in msgs for c in (m.get("tool_calls") or [])]
            if any(fam.get(u) in HOLDOUT_FAMILIES for u in used):
                continue
            text = json.dumps(msgs[1:], ensure_ascii=False)
            h = hashlib.sha256(text.encode()).hexdigest()[:16]
            if h in seen:
                continue
            seen.add(h)
            rows.append({"messages": msgs, "source": f"dsh:{name}",
                         "source_id": f"dsh#{name}#{n}", "group_id": f"dsh:{name}",
                         "simulation": True, "generated": True, "license": "own",
                         "content_hash": h})
            n += 1
        by_type[name] = n

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    rep = {"rows": len(rows), "by_type": dict(by_type), "tools_total": len(tools),
           "holdout_families": list(HOLDOUT_FAMILIES), "simulation": True,
           "file": str(OUT.relative_to(ROOT))}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
