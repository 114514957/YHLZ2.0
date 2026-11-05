"""环境守卫：清掉 NO_PROXY 里带方括号的 IPv6 项（台账 1096/1097）。

背景：某些启动器（如 DSH harness）会往 NO_PROXY 注入 `[::1]`。httpx 0.28 解析
任意请求的代理旁路表时会抛 `InvalidURL: Invalid port: ':1]'`——不是一次请求，
是**每个** httpx 请求，甚至连 `import gradio` 都会在导入阶段炸掉。

三层防线：
1. `backend/__init__.py`：导入时消毒（覆盖所有 import backend 的工具/测试）；
2. 本文件：可单独执行，也作为 `.venv` sitecustomize 的参照实现；
3. `.venv/Lib/site-packages/sitecustomize.py`：解释器启动即执行，覆盖第三方库
   在导入阶段读取环境变量的情况（backend 层救不到 gradio）。

用法：
    python tools/env_guard.py            # 报告本进程看到的条目
    from tools.env_guard import sanitize_now; sanitize_now()
"""
from __future__ import annotations

import os

_KEYS = ("NO_PROXY", "no_proxy")


def bracketed_entries(value: str) -> list[str]:
    return [p.strip() for p in str(value or "").split(",")
            if p.strip().startswith("[") and p.strip().endswith("]")]


def sanitize_now() -> list[str]:
    """Remove bracketed host entries in-place; returns human-readable changes."""
    changes: list[str] = []
    for key in _KEYS:
        raw = os.environ.get(key)
        if not raw:
            continue
        dropped = bracketed_entries(raw)
        if not dropped:
            continue
        kept = [p.strip() for p in raw.split(",")
                if p.strip() and p.strip() not in dropped]
        os.environ[key] = ",".join(kept)
        changes.append(f"{key}: dropped {dropped}")
    return changes


if __name__ == "__main__":
    for key in _KEYS:
        print(f"{key}={os.environ.get(key)!r}")
    print("changes:", sanitize_now() or "none")
    for key in _KEYS:
        print(f"{key}={os.environ.get(key)!r}")
