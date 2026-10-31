"""Agent harness 轨迹生成 v2（ledger 0900）。

按"未来 agent harness"的形态造多轮轨迹，且**每条都参数化**（路径/命令/目标随机），
避免"同一条复制 60 遍"的假多样性：
  single / chain / parallel / recover / longhorizon / guarded / delegate

约束：工具名/参数 ⊂ harness 注册表（51 项）；**留出 git、db 两族**不进训练；
simulation/generated 标记；近重去重（只比对话本体）。
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
SNAP = ROOT / "data" / "tool_registry" / "harness_tools_latest.json"
OUT = ROOT / "data" / "finetune" / "tool_harness_v1.jsonl"
REPORT = ROOT / "cache" / "v9_materials_preparation" / "harness_traces_report.json"

SYS = ("你在一个 agent harness 里干活：能读写文件、跑命令、查库、抓网、派子任务。"
       "工具名只用注册表里的；参数缺了先问；报错照实说；危险操作先确认。"
       "说话像元亨：短、口语，不列清单。")

HOLDOUT_FAMILIES = ("git", "db")

PATHS = ["config/app.yaml", "src/main.py", "docs/notes.md", "data/pt/manifest.json",
         "tools/v9_pt_corpus.py", "backend/test_x.py", "README.md", "scripts/build.ps1"]
CMDS = ["python -m pytest -q", "python tools/v9_pt_corpus.py", "pwsh -File scripts/build.ps1",
        "python -m unittest backend.test_out_gate"]
GOALS = ["把超时改成 30 秒并跑测试", "清理重复导入并验证", "补一个回归测试",
         "把 manifest 里的 token 数核对一遍", "把 README 更新到最新状态"]
DANGER = [("rm -rf build", "会删掉构建产物"), ("git push --force", "会覆盖远端历史"),
          ("sqlite.exec DROP TABLE ledger", "会删整张表"), ("fs.remove docs", "会删整个文档目录"),
          ("shell.kill 4242", "会杀主进程"), ("git.checkout --hard", "会丢弃未提交改动"),
          ("fs.write_file config/app.yaml", "会整文件覆盖"), ("sqlite.exec DELETE FROM memory", "会清空记忆表"),
          ("shell.run shutdown /s", "会关机"), ("fs.move data", "会移动数据目录")]

RECOVER_Q = ["0812", "素材清单", "工具真实化", "v9u", "记忆样本", "安全拒绝",
             "双签批次", "工具轨迹", "小说切块", "台账 0810", "利贞", "公版文本"]


def call(tool: str, args: dict, cid: str) -> dict:
    return {"id": cid, "type": "function",
            "function": {"name": tool, "arguments": json.dumps(args, ensure_ascii=False)}}


def sysm() -> dict:
    return {"role": "system", "content": SYS}


def single(rng, tool, args, user):
    return [sysm(), {"role": "user", "content": user},
            {"role": "assistant", "content": "",
             "tool_calls": [call(tool, args, "c1")]},
            {"role": "tool", "name": tool, "content": "ok"},
            {"role": "assistant", "content": rng.choice(
                ["办好了。", "行，弄完了。", "好了。", "成了。"])}]


def chain(rng):
    p = rng.choice(PATHS)
    old = rng.choice(["timeout: 10", "retries: 3", "debug: false", "port: 8081"])
    new = old.split(":")[0] + ": " + rng.choice(["30", "5", "true", "9000"])
    cmd = rng.choice(CMDS)
    return [sysm(),
            {"role": "user", "content": f"把 {p} 里那个配置改一下，改完跑一遍验证"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("fs.read_file", {"path": p, "max_bytes": 4000}, "c1")]},
            {"role": "tool", "name": "fs.read_file", "content": f"{old}\n# 其它配置…"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("fs.edit_file", {"path": p, "old": old, "new": new}, "c2")]},
            {"role": "tool", "name": "fs.edit_file", "content": "edited"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("code.test", {"command": cmd, "cwd": "."}, "c3")]},
            {"role": "tool", "name": "code.test", "content": rng.choice(
                ["3 passed", "全部通过（4 项）", "OK"])},
            {"role": "assistant", "content": f"改好了，{old} → {new}，验证也过了。"}]


def parallel(rng):
    a, b = rng.sample(PATHS, 2)
    mb = rng.choice([2000, 3000, 4000, 5000])
    return [sysm(),
            {"role": "user", "content": f"同时看下 {a} 和 {b}"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("fs.read_file", {"path": a, "max_bytes": mb}, "c1"),
                            call("fs.read_file", {"path": b, "max_bytes": mb}, "c2")]},
            {"role": "tool", "name": "fs.read_file", "content": f"{a} 的内容…"},
            {"role": "tool", "name": "fs.read_file", "content": f"{b} 的内容…"},
            {"role": "assistant", "content": f"两个都看了：{a} 是配置，{b} 是代码，没冲突。"}]


def recover(rng):
    q = rng.choice(RECOVER_Q)
    return [sysm(),
            {"role": "user", "content": f"查一下台账里 {q} 那条"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("ledger.query", {"query": q}, "c1")]},
            {"role": "tool", "name": "ledger.query",
             "content": rng.choice(["ERROR: missing required arg 'limit'",
                                    "ERROR: invalid type for 'limit' (expected integer)",
                                    "ERROR: query too short, add more terms"])},
            {"role": "assistant", "content": "",
             "tool_calls": [call("ledger.query", {"query": q, "limit": rng.choice([3, 5, 10])}, "c2")]},
            {"role": "tool", "name": "ledger.query",
             "content": f"{q}｜相关记录 {rng.randint(1, 5)} 条"},
            {"role": "assistant", "content": "查到了。刚才漏了 limit，补上才给查。"}]


def long_horizon(rng):
    p = rng.choice(PATHS)
    pat = rng.choice(["import json", "TODO", "print("])
    return [sysm(),
            {"role": "user", "content": f"把 {p} 里重复/无用的 {pat} 清一遍，清完跑测试，挂了就修"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("plan.create", {"goal": f"清理 {p} 并验证", "max_steps": 5}, "c1")]},
            {"role": "tool", "name": "plan.create", "content": "1 扫描 2 修改 3 测试 4 修 5 复测"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("fs.grep", {"pattern": pat, "path": p}, "c2")]},
            {"role": "tool", "name": "fs.grep", "content": f"{p}:12: {pat}"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("plan.update", {"step_id": "1", "status": "done"}, "c3")]},
            {"role": "tool", "name": "plan.update", "content": "ok"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("fs.edit_file", {"path": p, "old": pat, "new": ""}, "c4")]},
            {"role": "tool", "name": "fs.edit_file", "content": "edited"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("code.test", {"command": rng.choice(CMDS), "cwd": "."}, "c5")]},
            {"role": "tool", "name": "code.test", "content": "1 failed"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("code.lint", {"path": p, "tool": "ruff"}, "c6")]},
            {"role": "tool", "name": "code.lint", "content": "no issues"},
            {"role": "assistant", "content": "清完了。测试有一条挂的，是旧断言，跟这次改动无关，我没动它。"}]


def guarded(rng):
    action, detail = rng.choice(DANGER)
    detail = detail + rng.choice(["，且没法撤销", "，影响线上", "，涉及别人数据", ""])
    return [sysm(),
            {"role": "user", "content": f"{action} 一下"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("guard.confirm", {"action": action, "detail": detail}, "c1")]},
            {"role": "tool", "name": "guard.confirm", "content": "pending"},
            {"role": "assistant", "content": f"这个不可逆（{detail}），我先问一句：确认？你点头我再动。"}]


def delegate(rng):
    goal = rng.choice(GOALS)
    return [sysm(),
            {"role": "user", "content": f"帮我查清楚这件事再动手：{goal}"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("plan.create", {"goal": goal, "max_steps": 3}, "c1")]},
            {"role": "tool", "name": "plan.create", "content": "1 调研 2 实施 3 验证"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("task.delegate",
                                 {"goal": f"先调研：{goal}",
                                  "tools": ["net.search", "fs.grep"],
                                  "budget_steps": rng.choice([6, 8, 10])}, "c2")]},
            {"role": "tool", "name": "task.delegate", "content": f"task-{rng.randint(1, 9)} started"},
            {"role": "assistant", "content": "",
             "tool_calls": [call("task.collect", {"task_id": f"task-{rng.randint(1, 9)}"}, "c3")]},
            {"role": "tool", "name": "task.collect",
             "content": "结论：涉及 2 个文件，改一处配置即可，无需动代码"},
            {"role": "assistant", "content": "子任务回来了：只改一处配置，代码不用动。我可以接着做。"}]


SINGLE_UTTER = {
    "fs": ["看看 {p}", "把 {p} 读出来", "给我 {p} 的内容"],
    "shell": ["跑一下 {c}", "执行 {c}"],
    "net": ["抓一下这个页面", "搜一下素材清单的事"],
    "code": ["跑个片段看看", "执行这段代码"],
    "plan": ["把这事拆一下", "列个步骤"],
    "guard": ["看看审计日志", "查一下白名单"],
    "mem": ["回忆一下素材清单", "记一条：明天发清单"],
    "mcp": ["用 MCP 读一下文件", "用 MCP 列个目录"],
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=60)
    args = ap.parse_args()
    random.seed(20261022)
    snap = json.loads(SNAP.read_text(encoding="utf-8"))
    tools = {t["name"]: t for t in snap["tools"]}
    fam = {t["name"]: t["family"] for t in snap["tools"]}
    train = {n: t for n, t in tools.items() if fam[n] not in HOLDOUT_FAMILIES}

    rows, seen, by_type = [], set(), Counter()

    def add(msgs, typ):
        text = json.dumps(msgs[1:], ensure_ascii=False)
        h = hashlib.sha256(text.encode()).hexdigest()[:16]
        if h in seen:
            return
        seen.add(h)
        rows.append({"messages": msgs, "source": f"harness:{typ}",
                     "source_id": f"harness#{typ}#{by_type[typ]}",
                     "group_id": f"harness:{typ}", "simulation": True,
                     "generated": True, "license": "own", "content_hash": h})
        by_type[typ] += 1

    for _ in range(args.per_type):
        name = random.choice(list(train))
        t = train[name]
        props = list((t.get("properties") or {}).keys())
        vals = {"path": random.choice(PATHS), "src": "a.txt", "dst": "b.txt",
                "pattern": random.choice(["import ", "TODO", "def "]), "command": random.choice(CMDS),
                "db_path": "data/x.db", "url": "https://example.com", "query": "素材清单",
                "text": "明天发素材清单", "title": "素材", "body": "正文", "code": "print(1)",
                "goal": random.choice(GOALS), "action": "list", "entry": "x", "repo": "a/b",
                "ref": "main", "content": "x", "old": "x", "new": "y", "cwd": ".",
                "limit": 5, "top_k": 3, "max_bytes": 4000, "timeout_ms": 30000,
                "recursive": False, "staged": False, "max_chars": 4000, "max_steps": 5,
                "budget_steps": 8, "step_id": "1", "status": "done", "note": "",
                "task_id": "task-1", "reason": "", "detail": "", "since": "", "tool": "ruff",
                "sql": "SELECT 1", "params": "", "db": "data/x.db", "table": "t",
                "headers": "", "state": "open", "name": "main", "paths": ["a.py"],
                "tags": ["素材"], "tools": ["net.search"]}
        a = {k: vals.get(k, "x") for k in props}
        ut = SINGLE_UTTER.get(fam[name], ["处理一下这个"])
        user = random.choice(ut).format(p=a.get("path", ""), c=a.get("command", ""))
        add(single(random, name, a, user), "single")
        add(chain(random), "chain")
        add(parallel(random), "parallel")
        add(recover(random), "recover")
        add(long_horizon(random), "longhorizon")
        add(guarded(random), "guarded")
        add(delegate(random), "delegate")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    rep = {"rows": len(rows), "by_type": dict(by_type), "tools_total": len(tools),
           "holdout_families": list(HOLDOUT_FAMILIES), "train_tools": len(train),
           "simulation": True, "file": str(OUT.relative_to(ROOT))}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
