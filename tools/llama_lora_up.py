"""llama-server LoRA 版本切换（2026-09-25，台账 0502）。

用途：让本地 8081 的生产 llama-server **换一个 LoRA 版本重启**，用于
人格回归的"版本 × 得分"对比。API 层不暴露 LoRA，所以唯一硬证据是
读进程命令行——本工具在启动后会**校验实际加载的版本**，不符就报错。

与看护的配合（已读码确认，不碰看护进程）：
`tools/yhlz_watchdog.py` 的 `ensure_stack()` 只有在
「health 不通 **且** 端口未绑 **且** `_proc_alive("llama-server")` 为假 **且**
过 180s 节流」四者同时成立时才重新拉起生产 v7b。本工具换上的实例本身就是
llama-server 进程，因此看护不会插手；万一还是被顶掉，启动后的校验能立刻发现
并重试一次。

用法：
    python tools/llama_lora_up.py --list              # 列出可用 LoRA
    python tools/llama_lora_up.py --show              # 只看当前加载的是哪个
    python tools/llama_lora_up.py --lora v6           # 切到 v6（vn / 全名都接受）
    python tools/llama_lora_up.py --lora v7b          # 恢复生产（等价于 yhlz_paths 默认）
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backend.yhlz_paths import (  # noqa: E402
    LOCAL_MODELS, YH_BASE_GGUF, YH_LLAMA_EXE, YH_LORA_GGUF, YH_MMPROJ_GGUF,
)

LORA_DIR = LOCAL_MODELS / "gguf-lora"
LOG_FILE = _ROOT / "cache" / "logs" / "llama-server.log"
DEFAULT_PORT = 8081
START_TIMEOUT = 180.0     # 模型加载 + 绑定端口；显存吃紧时会慢
HEALTH_TIMEOUT = 5.0


# ---------------- 进程 / 服务探查 ----------------
def _llama_procs() -> list:
    """所有 llama-server 进程（psutil Process 列表）。取不到 psutil 就返回空。"""
    try:
        import psutil
    except Exception:
        return []
    out = []
    for p in psutil.process_iter(["cmdline"]):
        try:
            cl = [str(x) for x in (p.info.get("cmdline") or [])]
        except Exception:
            continue
        if any("llama-server" in x for x in cl):
            out.append(p)
    return out


def _proc_arg(proc, flag: str) -> str:
    """取某进程命令行里 --flag 后面那个参数（无则空串）。"""
    try:
        cl = [str(x) for x in (proc.info.get("cmdline") or [])]
    except Exception:
        return ""
    if flag in cl:
        i = cl.index(flag)
        if i + 1 < len(cl):
            return cl[i + 1]
    return ""


def running_lora() -> str:
    """当前 llama-server 实际加载的 LoRA 文件名（取不到则空串 = 未知）。"""
    for p in _llama_procs():
        v = _proc_arg(p, "--lora")
        if v:
            return pathlib.Path(v).name
    return ""


def running_port() -> int:
    """当前 llama-server 监听的端口（取不到则 0）。"""
    for p in _llama_procs():
        v = _proc_arg(p, "--port")
        if v.isdigit():
            return int(v)
    return 0


def health_ok(port: int = DEFAULT_PORT, timeout: float = HEALTH_TIMEOUT) -> bool:
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return str(json.loads(r.read().decode("utf-8")).get("status", "")).lower() == "ok"
    except Exception:
        return False


def _port_free(port: int) -> bool:
    import socket

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return False
    except Exception:
        return True


# ---------------- LoRA 解析 ----------------
def resolve_lora(name: str) -> pathlib.Path:
    """把 v6 / yuanheng-v6-lora.gguf 都解析成实际文件路径；不存在则抛。"""
    raw = str(name or "").strip()
    if not raw:
        raise ValueError("LoRA 名不能为空")
    cands = [pathlib.Path(raw)]
    if not raw.endswith(".gguf"):
        cands.append(LORA_DIR / f"yuanheng-{raw}-lora.gguf")   # v6 -> yuanheng-v6-lora.gguf
        cands.append(LORA_DIR / f"{raw}.gguf")                 # yuanheng-v6-lora -> ….gguf
    cands.append(LORA_DIR / raw)
    for c in cands:
        if c.is_file():
            return c
    avail = ", ".join(sorted(p.stem for p in LORA_DIR.glob("*.gguf"))) or "(空)"
    raise FileNotFoundError(f"找不到 LoRA「{raw}」；可用：{avail}")


# ---------------- 停止 / 启动 ----------------
def stop_llama(port: int = DEFAULT_PORT, wait: float = 30.0) -> int:
    """停掉所有 llama-server，等端口释放。返回停掉的进程数。"""
    procs = _llama_procs()
    n = 0
    for p in procs:
        try:
            p.terminate()
            n += 1
        except Exception:
            pass
    deadline = time.time() + wait
    while time.time() < deadline:
        if not _llama_procs() and _port_free(port):
            return n
        time.sleep(0.5)
    for p in _llama_procs():   # 顽固进程才强杀
        try:
            p.kill()
        except Exception:
            pass
    time.sleep(1.0)
    return n


def start_llama(lora: pathlib.Path, port: int = DEFAULT_PORT) -> subprocess.Popen:
    """按生产参数启动 llama-server（除 --lora 外与 yhlz_launcher._spawn_llama 一致）。"""
    for need in (YH_LLAMA_EXE, YH_BASE_GGUF, YH_MMPROJ_GGUF):
        if not pathlib.Path(need).exists():
            raise FileNotFoundError(f"缺资产：{need}")
    argv = [str(YH_LLAMA_EXE), "-m", str(YH_BASE_GGUF),
            "--mmproj", str(YH_MMPROJ_GGUF), "--no-mmproj-offload",
            "--lora", str(lora),
            "-ngl", "99", "-c", "8192", "--parallel", "1",
            "-rea", "off", "--alias", "gemma-4-e4b",
            "--host", "127.0.0.1", "--port", str(int(port)), "--jinja"]
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    print("[起] " + " ".join(argv))
    return subprocess.Popen(argv, cwd=str(_ROOT),
                            stdout=open(LOG_FILE, "ab"),
                            stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            close_fds=True)


def switch(name: str, port: int = DEFAULT_PORT,
           timeout: float = START_TIMEOUT) -> str:
    """切到指定 LoRA 并**校验**真的生效；返回实际加载的文件名。

    校验失败会重试一次（防看护在切换窗口内抢注），仍失败则抛错。
    """
    target = resolve_lora(name)
    for attempt in (1, 2):
        stop_llama(port)
        start_llama(target, port)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if health_ok(port):
                break
            time.sleep(1.0)
        else:
            raise RuntimeError(
                f"{timeout:.0f}s 内 /health 未就绪（端口 {port}）；"
                f"看日志：{LOG_FILE}")
        actual = running_lora()
        if actual == target.name:
            return actual
        print(f"[校验] 第 {attempt} 次不符：期望 {target.name}，实际 "
              f"{actual or '(未取到)'} → 重试", file=sys.stderr)
    raise RuntimeError(f"LoRA 校验两次失败：期望 {target.name}，"
                       f"实际 {running_lora() or '(未取到)'}")


def _cmd_list() -> int:
    cur = running_lora()
    files = sorted(LORA_DIR.glob("*.gguf"))
    if not files:
        print(f"（{LORA_DIR} 下没有 .gguf）")
        return 1
    print(f"可用 LoRA（{LORA_DIR}）：")
    for f in files:
        mark = "  ← 当前加载" if f.name == cur else ""
        print(f"  {f.name}  {f.stat().st_size / 1048576:.1f}MB{mark}")
    if cur:
        print(f"当前 llama-server：{cur}（端口 {running_port() or '?'}，"
              f"health {'ok' if health_ok(running_port() or DEFAULT_PORT) else '不通'}）")
    else:
        print("当前没有带 --lora 的 llama-server 在跑")
    return 0


def _cmd_show() -> int:
    print(f"当前 LoRA：{running_lora() or '(未取到)'}")
    print(f"端口：{running_port() or '(未取到)'}")
    print(f"health：{'ok' if health_ok(running_port() or DEFAULT_PORT) else '不通'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="llama-server LoRA 版本切换")
    ap.add_argument("--lora", default="", help="要加载的 LoRA（v6 / v7b / 全名）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--list", action="store_true", help="列出可用 LoRA")
    ap.add_argument("--show", action="store_true", help="只看当前加载的版本")
    ap.add_argument("--timeout", type=float, default=START_TIMEOUT)
    args = ap.parse_args(argv)

    if args.list:
        return _cmd_list()
    if args.show:
        return _cmd_show()
    if not args.lora:
        ap.error("要么给 --lora <版本>，要么用 --list / --show")

    try:
        actual = switch(args.lora, args.port, args.timeout)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"[失败] {exc}", file=sys.stderr)
        return 1
    print(f"[成功] 8081 现加载 LoRA：{actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())