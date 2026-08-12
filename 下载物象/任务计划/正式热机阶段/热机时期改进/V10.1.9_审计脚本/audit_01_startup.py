# -*- coding: utf-8 -*-
"""V10.1.9 审计 #01: 冷启动可靠性测试 (隔离端口 8900, 连续 10 次)

职责（责任书 §二）: 启动测试工程师
审计域: V10.1.9 Prompt §五 启动可靠性测试
  - 每次: spawn backend.main 应用实例 → 轮询 /health → 记录启动耗时 → 终止
  - 端口冲突测试: 实例 A 运行中再启动实例 B (预期 B 绑定失败快速退出)
  - 实例 stdout/stderr 全部落盘, 供事后检查依赖缺失/异常
证据: runs/startup_XX.log(.err.log) + runs/startup_summary.json
"""

# ── 标准库导入 ──────────────────────────────────────────────
import json        # 序列化测试结果到 JSON 证据文件
import subprocess  # spawn 独立后端实例 (隔离端口)
import sys         # (保留: 后续扩展参数解析用)
import time        # 启动耗时测量与轮询节流
import urllib.request  # 轻量 HTTP 轮询 /health (不依赖 requests)
from pathlib import Path  # 路径对象 (跨平台安全拼接)

# ── 全局常量 (本脚本只读, 禁止业务代码引用) ─────────────────
ROOT = Path(r"D:\YHLZ2.0")                     # 项目根 (subprocess cwd)
VENV_PY = ROOT / "venv" / "Scripts" / "python.exe"  # 解释器 (venv)
PORT = 8900                                    # 隔离测试端口 (避开 8000/5000)
HEALTH_URL = f"http://127.0.0.1:{PORT}/health" # 就绪探针地址
RUN_DIR = Path(__file__).parent / "runs"       # 证据输出目录 (本脚本同级)
RUN_DIR.mkdir(exist_ok=True)                   # 证据目录不存在则创建

# 启动命令模板: 以隔离端口运行真实 backend.main 应用
# (log_level=warning 减少噪音; 不触碰运行中的 8000 实例)
BOOT_CODE = (
    "import uvicorn; from backend.main import app; "
    "uvicorn.run(app, host='127.0.0.1', port=8900, log_level='warning')"
)


def port_busy() -> bool:
    """端口就绪探测: /health 返回 200 即视为实例已就绪

    返回: True=实例已响应; False=未就绪或异常 (探针自身绝不抛错)
    """
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1.0) as r:
            return r.status == 200   # 只有 HTTP 200 才算就绪
    except Exception:
        return False  # 连接失败/超时均视为未就绪 (静默)


def wait_health(timeout: float = 120.0) -> float:
    """等待实例就绪, 返回实际等待秒数

    参数: timeout=最大等待秒数 (默认 120s, 覆盖慢启动 edge-tts 预热)
    返回: 就绪耗时秒数; 超时返回 -1.0 (调用方按失败处理)
    """
    start = time.time()              # 记录等待起点
    while time.time() - start < timeout:  # 轮询直到超时
        if port_busy():
            return time.time() - start   # 就绪, 返回耗时
        time.sleep(0.5)              # 500ms 轮询节流 (避免打爆端口)
    return -1.0                      # 超时信号


def main() -> None:
    """主流程: 冷启动 10 次 + 端口冲突测试 + 汇总落盘"""
    # ── 1. 冷启动 10 次 ──────────────────────────────────────
    results = []     # 成功启动的耗时列表 (秒)
    failures = []    # 失败记录 (每次失败一行说明)
    for i in range(1, 11):  # 连续 10 次冷启动
        # 每次独立日志文件: stdout/stderr 分离, UTF-8 落盘
        log = RUN_DIR / f"startup_{i:02d}.log"
        err = RUN_DIR / f"startup_{i:02d}.err.log"
        if port_busy():  # 前置检查: 上次实例未清理干净则跳过本轮
            failures.append(f"run{i}: 端口 {PORT} 已被占用(前次实例未退出?)")
            continue
        # spawn 独立后端实例 (cwd=项目根, 保证 backend.main 可导入)
        proc = subprocess.Popen(
            [str(VENV_PY), "-c", BOOT_CODE],
            cwd=str(ROOT),
            stdout=open(log, "w", encoding="utf-8"),
            stderr=open(err, "w", encoding="utf-8"),
        )
        t = wait_health()      # 等待 /health 就绪 (≤120s)
        if t < 0:              # 超时未就绪 → 记录失败并终止
            failures.append(f"run{i}: 120s 内 /health 未就绪 (exit={proc.poll()})")
            proc.terminate()
        else:                  # 就绪 → 记录耗时并终止
            results.append(round(t, 2))
            proc.terminate()
        time.sleep(0.5)        # 冷却: 等端口完全释放再进入下一轮

    # ── 2. 端口冲突测试 (实例 A 常驻, B 应快速失败) ──────────
    log_a = RUN_DIR / "conflict_a.log"      # A 的 stdout (常驻实例)
    err_a = RUN_DIR / "conflict_a.err.log"  # A 的 stderr
    proc_a = subprocess.Popen(              # 先启动 A 并保持运行
        [str(VENV_PY), "-c", BOOT_CODE],
        cwd=str(ROOT),
        stdout=open(log_a, "w", encoding="utf-8"),
        stderr=open(err_a, "w", encoding="utf-8"),
    )
    t = wait_health(timeout=120.0)          # 等 A 就绪
    conflict_result = "SKIP"                # A 未就绪则跳过冲突测试
    if t > 0:
        start = time.time()                 # 记录 B 启动时刻
        err_b = RUN_DIR / "conflict_b.err.log"  # B 的 stderr (应含 bind 错误)
        proc_b = subprocess.Popen(          # 在 A 运行中启动 B
            [str(VENV_PY), "-c", BOOT_CODE],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,      # B 的 stdout 丢弃 (预期快速失败)
            stderr=open(err_b, "w", encoding="utf-8"),
        )
        try:
            rc = proc_b.wait(timeout=60)    # 60s 内应因绑定失败退出
            conflict_result = f"OK: B 退出 code={rc} 耗时={round(time.time()-start, 2)}s"
        except subprocess.TimeoutExpired:   # 60s 未退出 = 端口被共享 (异常)
            conflict_result = "FAIL: B 60s 未退出 (端口被共享?)"
            proc_b.terminate()
    proc_a.terminate()                      # 清理常驻实例 A

    # ── 3. 结果汇总落盘 + 控制台输出 ─────────────────────────
    summary = {
        "runs": results,                    # 每次启动耗时 (秒)
        "success": len(results),            # 成功次数
        "failed": failures,                 # 失败明细
        "avg_startup_s": round(sum(results) / len(results), 2) if results else None,
        "min_s": min(results) if results else None,
        "max_s": max(results) if results else None,
        "port_conflict": conflict_result,   # 端口冲突测试结论
    }
    out = RUN_DIR / "startup_summary.json"  # 证据: JSON 汇总
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))  # 控制台即时可见


if __name__ == "__main__":
    main()  # 仅作为脚本直接运行时执行 (可被 unittest/导入复用)
