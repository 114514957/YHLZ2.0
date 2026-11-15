# -*- coding: utf-8 -*-
"""LLM 端点解析：**全项目只有这里决定"用哪个模型"**（台账 1239 起）。

配置优先级（高 → 低）：
  1. 环境变量 `YHLZ_LLM_PROVIDER` / `YHLZ_LLM_BASE_URL` / `YHLZ_LLM_MODEL` / `YHLZ_LLM_KEY`
  2. `config/llm.local.json`（**不入 git**，本机专用）
  3. 内置默认：**cloud（DeepSeek）**——老爹 1229/1231 定论：项目 LLM 直接上大模型，
     **本地 llama 彻底下线，不做兜底**。

用法：
    from backend.llm_endpoint import endpoint
    ep = endpoint()            # {"provider","base_url","model","api_key","timeout_s"}
    build_openai_compatible_llm_turn(base_url=ep["base_url"], model=ep["model"],
                                     api_key=ep["api_key"])
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

__all__ = ["endpoint", "provider", "is_cloud", "reload", "CLOUD_DEFAULT"]

CLOUD_DEFAULT = {
    "base_url": "https://api.deepseek.com/v1/chat/completions",
    "model": "deepseek-chat",
}
LOCAL_DEFAULT = {
    "base_url": "http://127.0.0.1:8081/v1/chat/completions",
    "model": "gemma-4-e4b",
}
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "llm.local.json"

_cache: dict[str, Any] | None = None


def _file_cfg() -> dict[str, Any]:
    try:
        if CONFIG_PATH.is_file():
            return json.loads(io.open(CONFIG_PATH, encoding="utf-8").read())
    except Exception:  # noqa: BLE001
        pass
    return {}


def reload() -> None:
    """清缓存（改配置后调用；测试用）。"""
    global _cache
    _cache = None


def provider() -> str:
    """`cloud` / `local`。默认 cloud。"""
    v = (os.getenv("YHLZ_LLM_PROVIDER") or "").strip().lower()
    if v in ("cloud", "local"):
        return v
    f = _file_cfg().get("provider")
    if str(f or "").strip().lower() in ("cloud", "local"):
        return str(f).strip().lower()
    return "cloud"


def is_cloud() -> bool:
    return provider() == "cloud"


def endpoint() -> dict[str, Any]:
    """解析出可用的端点参数。云端缺密钥时**明确报错**，不静默回落。"""
    global _cache
    if _cache is not None:
        return dict(_cache)
    prov = provider()
    f = _file_cfg()
    default = CLOUD_DEFAULT if prov == "cloud" else LOCAL_DEFAULT

    base = (os.getenv("YHLZ_LLM_BASE_URL")
            or f.get("base_url") or default["base_url"])
    model = (os.getenv("YHLZ_LLM_MODEL")
             or f.get("model") or default["model"])
    key = (os.getenv("YHLZ_LLM_KEY")
           or f.get("api_key") or "")
    out = {
        "provider": prov,
        "base_url": str(base),
        "model": str(model),
        "api_key": str(key),
        "timeout_s": int(os.getenv("YHLZ_LLM_TIMEOUT") or f.get("timeout_s") or 120),
        "temperature": float(os.getenv("YHLZ_LLM_TEMP") or f.get("temperature") or 0.7),
        "max_tokens": int(os.getenv("YHLZ_LLM_MAXTOK") or f.get("max_tokens") or 800),
    }
    if prov == "cloud" and not out["api_key"]:
        raise RuntimeError(
            "云端模型没有密钥：请设 YHLZ_LLM_KEY，或把密钥写进 %s（该文件不入 git）"
            % CONFIG_PATH)
    _cache = out
    return dict(out)
