"""人格回归「版本 × 得分」批量扫描（2026-09-25，台账 0502）。

逐个切换本地 llama-server 的 LoRA、跑同一套 38 题、把每版一行写进
`docs/报告/人格回归基线.md`。存在的理由是**一个必须成立的约束**：
不管中途怎么崩，生产最终都要回到 v7b——所以恢复写在 finally 里，
且最后会**校验**实际加载的版本。

为什么用子进程：每个版本一次 `persona_regression --live`，互相不串状态
（记忆库/编排器都是新建），比在同一进程里连跑四轮可靠。

用法：
    python tools/persona_version_sweep.py                  # 默认 v6/v7/v7c/v7b
    python tools/persona_version_sweep.py --versions v7b v7c
    python tools/persona_version_sweep.py --restore-only    # 只把生产恢复回 v7b
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# 默认扫描顺序：v6 → v7 → v7c → v7b。**v7b 放最后**，这样正常跑完时
# 生产已经是 v7b，不需要额外恢复（异常路径仍由 finally 兜底）。
DEFAULT_VERSIONS = ("v6", "v7", "v7c", "v7b")
PRODUCTION_LORA = "v7b"


def lora_file(version: str) -> str:
    return f"yuanheng-{version}-lora.gguf"


def _run(cmd: list[str]) -> int:
    print("\n$ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(_ROOT))


def restore_production() -> bool:
    """把 8081 拉回生产 v7b 并**校验**；返回是否成功。"""
    from tools.llama_lora_up import running_lora, switch

    want = lora_file(PRODUCTION_LORA)
    if running_lora() == want:
        print(f"[恢复] 已在 {want}，无需切换")
        return True
    try:
        got = switch(PRODUCTION_LORA)
    except Exception as exc:  # noqa: BLE001
        print(f"[恢复失败] {type(exc).__name__}: {exc}", file=sys.stderr)
        return False
    ok = got == want
    print(f"[恢复] 8081 -> {got}（{'OK' if ok else '不符！'}）")
    return ok


def sweep(versions: list[str], timeout: float, repeat: int = 1,
          answers_dir: str = "") -> int:
    """逐版切换并跑 N 轮。``repeat`` >1 时同版本多跑几次——
    这是**噪声底线**的来源（同一判定、同一版本，差异 = 采样抖动）。

    每次切换只做一次，重复轮共用同一个已加载的 LoRA（省下反复加载）。
    """
    from tools.llama_lora_up import switch

    py = str(_ROOT / ".venv" / "Scripts" / "python.exe")
    rows: list[tuple[str, str]] = []      # (版本, 结果或错误)
    aborted = False
    restored = True
    try:
        for v in versions:
            lora = lora_file(v)
            print(f"\n{'=' * 60}\n== 版本 {v}（{lora}）\n{'=' * 60}", flush=True)
            try:
                got = switch(v, timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                print(f"[跳过 {v}] 切换失败：{type(exc).__name__}: {exc}",
                      file=sys.stderr)
                rows.append((v, f"切换失败 {type(exc).__name__}"))
                aborted = True
                break
            if got != lora:
                rows.append((v, f"LoRA 不符（{got}）"))
                aborted = True
                break
            for r in range(1, max(1, int(repeat)) + 1):
                label = v if r == 1 else f"{v}#{r}"
                cmd = [py, "-B", "tools/persona_regression.py", "--live",
                       "--version", label, "--expect-lora", lora]
                if answers_dir:
                    cmd += ["--save-answers",
                            str(pathlib.Path(answers_dir) / f"{label.replace('#', '_r')}.json")]
                rc = _run(cmd)
                if rc == 0:
                    rows.append((label, "已出分"))
                elif rc == 2:
                    rows.append((label, "中止（环境/版本校验，未出分）"))
                    aborted = True
                    break
                else:
                    rows.append((label, f"退出码 {rc}"))
                    aborted = True
                    break
            if aborted:
                break
    finally:
        print(f"\n{'=' * 60}\n== 恢复生产（{PRODUCTION_LORA}）\n{'=' * 60}", flush=True)
        restored = restore_production()

    print("\n== 扫描结果 ==")
    for v, msg in rows:
        print(f"  {v:<7} {msg}")
    if aborted:
        print("  （中途中止：后续未跑）")
    print(f"  生产恢复：{'成功' if restored else '**失败，需人工处理**'}")
    return 0 if (rows and not aborted and restored) else 1


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="人格回归版本扫描")
    ap.add_argument("--versions", nargs="*", default=list(DEFAULT_VERSIONS),
                    help=f"要跑的版本（默认 {' '.join(DEFAULT_VERSIONS)}）")
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="每次切换等待 /health 的上限秒数")
    ap.add_argument("--repeat", type=int, default=1,
                    help="每个版本跑几轮（>1 用来量噪声底线；默认 1）")
    ap.add_argument("--answers-dir", default="",
                    help="原始答案存档目录（给复判与噪声分析用）")
    ap.add_argument("--restore-only", action="store_true",
                    help="只把生产恢复回 v7b，不跑评测")
    args = ap.parse_args(argv)

    if args.restore_only:
        return 0 if restore_production() else 1
    return sweep(list(args.versions), args.timeout, args.repeat,
                 args.answers_dir)


if __name__ == "__main__":
    raise SystemExit(main())