# -*- coding: utf-8 -*-
"""模型实验站（P0）：一次只变一个因子的受控实验。

设计见 `docs/研究/模型实验站_设计_v1.md`。

用法：
    python station.py run --config configs/base_private.json --dry-run
    python station.py run --config configs/exp-0042.json
    python station.py list
    python station.py compare exp-0041 exp-0042

不变量（踩过的坑）：
    冷态     每个配置起新实例再跑（台账 1068：被聊过一轮 45→44）
    后端固定 记录 ngl，数字标明 CPU/GPU（1067：同权重差 1 分）
    判据固定 记录 JUDGE_VERSION（1077→1086 每次改判据都改分）
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "runs")
CONFIGS = os.path.join(HERE, "configs")
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
sys.path.insert(0, os.path.join(YH, "tools"))

LLAMA = os.path.join(YH, "models", "llama-cuda", "llama-server.exe")
PORT = 8093                      # 实验站专用端口，不碰 workbench 的 8091
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ── 配置 ────────────────────────────────────────────────────────
def load_cfg(p: str) -> dict:
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def abspath(p: str) -> str:
    return p if os.path.isabs(p) else os.path.join(YH, p)


def rel(p: str) -> str:
    """`--lora-scaled` / `--control-vector-scaled` 的路径里**不能带盘符冒号**，
    否则被当成 FNAME:SCALE 的分隔符（台账 1074 同款坑）。统一用相对 YH 的路径，
    并把子进程 cwd 设成 YH。
    """
    return os.path.relpath(abspath(p), YH).replace("\\", "/")


def cfg_hash(cfg: dict) -> str:
    body = {k: v for k, v in cfg.items() if k not in ("id", "name", "notes")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()[:16]


def build_cmd(cfg: dict) -> list[str]:
    m = cfg["model"]
    cmd = [LLAMA, "-m", rel(m["base"])]
    if m.get("mmproj"):
        cmd += ["--mmproj", rel(m["mmproj"]), "--no-mmproj-offload"]

    loras = m.get("lora") or []
    if len(loras) == 1 and float(loras[0].get("scale", 1.0)) == 1.0:
        cmd += ["--lora", rel(loras[0]["path"])]
    elif loras:
        spec = ",".join("%s:%s" % (rel(x["path"]), x.get("scale", 1.0)) for x in loras)
        cmd += ["--lora-scaled", spec]

    cv = m.get("control_vector") or []
    if cv:
        spec = ",".join("%s:%s" % (rel(c["path"]), c.get("scale", 1.0)) for c in cv)
        cmd += ["--control-vector-scaled", spec]
        layers = cv[0].get("layers")
        if layers:
            cmd += ["--control-vector-layer-range", str(layers[0]), str(layers[1])]

    cmd += ["-ngl", str(m.get("ngl", 0)), "-c", str(m.get("ctx", 8192)),
            "--parallel", "1", "-rea", "off", "--jinja",
            "--alias", cfg.get("id", "exp"), "--host", "127.0.0.1", "--port", str(PORT)]

    s = cfg.get("sampling") or {}
    if s.get("temperature") is not None:
        cmd += ["--temp", str(s["temperature"])]
    if s.get("top_p") is not None:
        cmd += ["--top-p", str(s["top_p"])]
    if s.get("repeat_penalty") is not None:
        cmd += ["--repeat-penalty", str(s["repeat_penalty"])]
    if s.get("dry_multiplier"):
        cmd += ["--dry-multiplier", str(s["dry_multiplier"])]
        cmd += ["--dry-base", str(s.get("dry_base", 1.75))]
    if s.get("min_p"):
        cmd += ["--min-p", str(s["min_p"])]

    g = cfg.get("grammar")
    if g:
        if g.get("file"):
            cmd += ["--grammar-file", abspath(g["file"])]
        elif g.get("inline"):
            cmd += ["--grammar", g["inline"]]

    for lb in (cfg.get("logit_bias") or []):
        tid = lb.get("token_id")
        if tid is None:
            continue
        cmd += ["--logit-bias", "%s%+d" % (tid, int(lb.get("bias", 0)))]
    return cmd


# ── 服务器 ──────────────────────────────────────────────────────
def wait_health(timeout=240) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with OPENER.open("http://127.0.0.1:%d/health" % PORT, timeout=2) as r:
                if json.loads(r.read().decode()).get("status") == "ok":
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.5)
    return False


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


# ── 跑题库（复用 workbench 的判据与题库）──────────────────────────
def run_suite(name: str, tag: str) -> dict:
    import evals  # noqa: PLC0415
    if name == "persona56":
        return evals._run_persona56(PORT, tag, 300)
    if name == "group":
        return evals._run_group(PORT, tag, 300)
    if name == "material20":
        return evals._run_material20(PORT, tag, 300)
    raise SystemExit("未知套件：%s" % name)


def apply_prompt(cfg: dict) -> None:
    """F3：提示词因子。persona56 用 UNIFIED_SYSTEM，群聊用 _public_system()。
    custom 时直接替换 evals 里的模块级常量（它每次调用现取，改完即生效）。
    """
    import evals  # noqa: PLC0415
    p = cfg.get("prompt") or {}
    kind = p.get("kind", "private")
    if kind == "custom" and p.get("text"):
        evals.UNIFIED_SYSTEM = p["text"]
        print("  [F3] 已替换私聊提示词（%d 字）" % len(p["text"]))
    elif kind == "custom_public" and p.get("text"):
        evals._public_system = lambda: p["text"]
        print("  [F3] 已替换群聊提示词（%d 字）" % len(p["text"]))


def do_run(cfg: dict, dry: bool) -> dict:
    cmd = build_cmd(cfg)
    print("配置 %s｜%s" % (cfg.get("id", "?"), cfg.get("name", "")))
    print("命令：\n  " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    print("题库：%s｜repeats=%d｜cold=%s"
          % ([t["suite"] for t in cfg["tests"]], cfg.get("repeats", 1), cfg.get("cold", True)))
    if dry:
        return {}

    apply_prompt(cfg)
    os.makedirs(RUNS, exist_ok=True)
    logp = os.path.join(RUNS, "server_%s.log" % cfg.get("id", "exp"))
    import persona_bank as PB  # noqa: PLC0415
    rec = {"exp_id": cfg.get("id"), "name": cfg.get("name", ""),
           "config_hash": cfg_hash(cfg), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "backend": "cpu" if cfg["model"].get("ngl", 0) == 0 else "gpu",
           "judge_version": PB.JUDGE_VERSION, "server_cmd": cmd,
           "cold": cfg.get("cold", True), "repeats": []}

    for rep in range(1, int(cfg.get("repeats", 1)) + 1):
        log = open(logp, "a", encoding="utf-8", errors="replace")
        # cwd=YH（相对路径才成立）；DLL 靠 PATH 找 llama 目录
        env = os.environ.copy()
        env["PATH"] = os.path.dirname(LLAMA) + os.pathsep + env.get("PATH", "")
        p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=YH, env=env)
        try:
            if not wait_health():
                raise SystemExit("实例起不来，看 %s" % logp)
            time.sleep(2)          # 让 KV 完全就绪
            results = []
            for t in cfg["tests"]:
                r = run_suite(t["suite"], "%s-r%d" % (cfg.get("id"), rep))
                results.append({"suite": t["suite"], "ok": r.get("ok"),
                                "total": r.get("total"), "by_cat": r.get("by_cat"),
                                "gate_ok": r.get("gate_ok"),
                                "gate_fail": r.get("gate_fail"),
                                "failed_ids": [x["id"] for x in r.get("results", []) if not x["ok"]],
                                "elapsed": round(sum(x.get("elapsed", 0)
                                                     for x in r.get("results", [])), 1)})
                print("  [r%d] %-10s %s/%s 闸门%s"
                      % (rep, t["suite"], r.get("ok"), r.get("total"),
                         "过" if r.get("gate_ok") else "✗"), flush=True)
            rec["repeats"].append({"run": rep, "results": results})
        finally:
            kill_tree(p.pid)
            log.close()
            time.sleep(2)

    # 稳定性
    if len(rec["repeats"]) > 1:
        stab = {}
        for t in cfg["tests"]:
            vals = [next((x["ok"] for x in r["results"] if x["suite"] == t["suite"]), None)
                    for r in rec["repeats"]]
            stab[t["suite"]] = {"values": vals, "same": len(set(vals)) == 1}
        rec["stability"] = stab

    out = os.path.join(RUNS, "%s-%s.json" % (time.strftime("%Y%m%d-%H%M"), rec["exp_id"]))
    with io.open(out, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    print("\n记录：%s" % out)
    return rec


# ── list / compare / plan ───────────────────────────────────────
def cmd_list(_a) -> None:
    files = sorted(f for f in os.listdir(RUNS) if f.endswith(".json")) if os.path.isdir(RUNS) else []
    print("%-22s %-26s %-6s %-4s %s" % ("时间", "实验", "后端", "判据", "结果"))
    for f in files:
        r = json.load(io.open(os.path.join(RUNS, f), encoding="utf-8"))
        res = " | ".join("%s %s/%s" % (x["suite"], x["ok"], x["total"])
                         for x in (r["repeats"][0]["results"] if r.get("repeats") else []))
        print("%-22s %-26s %-6s v%-3s %s" % (f[:15], (r.get("exp_id") or "")[:26],
                                             r.get("backend"), r.get("judge_version"), res))


def cmd_compare(a) -> None:
    got = {}
    for f in os.listdir(RUNS):
        r = json.load(io.open(os.path.join(RUNS, f), encoding="utf-8"))
        if r.get("exp_id") in a.ids:
            got[r["exp_id"]] = r
    for eid in a.ids:
        r = got.get(eid)
        if not r:
            print("%s：没有记录" % eid)
            continue
        print("\n== %s %s（%s，判据 v%s）==" % (eid, r.get("name", ""), r.get("backend"),
                                              r.get("judge_version")))
        for x in r["repeats"][0]["results"]:
            print("   %-10s %s/%s 闸门%s 失败:%s"
                  % (x["suite"], x["ok"], x["total"],
                     "过" if x.get("gate_ok") else "✗", ",".join(x.get("failed_ids") or [])))


def cmd_plan(a) -> None:
    """按因子生成变体：values 用分号分隔，每个变体只改这一处。"""
    base = load_cfg(a.base)
    os.makedirs(CONFIGS, exist_ok=True)
    for i, v in enumerate(a.values.split(";"), 1):
        cfg = json.loads(json.dumps(base))
        cfg["id"] = "%s-%s%d" % (base.get("id", "exp"), a.factor.lower(), i)
        cfg["name"] = "%s = %s" % (a.factor, v)
        if a.factor == "F1":          # 适配器：v9t7:1.0 或 v9t7:0.7+v9t8:0.3
            cfg["model"]["lora"] = [
                {"path": "models/gguf-lora/yuanheng-%s-lora.gguf" % part.split(":")[0],
                 "scale": float(part.split(":")[1])}
                for part in v.split("+")]
        elif a.factor == "F4":        # 采样：dry=0.8,repeat=1.1
            for kv in v.split(","):
                k, val = kv.split("=")
                cfg["sampling"][{"dry": "dry_multiplier"}.get(k, k)] = float(val)
        elif a.factor == "F6":        # logit-bias：token_id:bias
            tid, bias = v.split(":")
            cfg["logit_bias"] = [{"token_id": int(tid), "bias": float(bias)}]
        elif a.factor == "F3":
            cfg["prompt"] = {"kind": v}
        p = os.path.join(CONFIGS, "%s.json" % cfg["id"])
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
        print("  %s  %s" % (cfg["id"], v))


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--config", required=True)
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=lambda a: do_run(load_cfg(a.config), a.dry_run))

    sub.add_parser("list").set_defaults(fn=cmd_list)

    c = sub.add_parser("compare")
    c.add_argument("ids", nargs="+")
    c.set_defaults(fn=cmd_compare)

    p = sub.add_parser("plan")
    p.add_argument("--base", required=True)
    p.add_argument("--factor", required=True, choices=["F1", "F2", "F3", "F4", "F6"])
    p.add_argument("--values", required=True, help="分号分隔")
    p.set_defaults(fn=cmd_plan)

    a = ap.parse_args()
    a.fn(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
