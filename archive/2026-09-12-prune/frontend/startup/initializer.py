"""
YHLZ 前端一键启动核心 (Startup Core)

职责:
    - 一键启动完整伙伴核心: Environment → Config → Backend →
      Runtime → Identity → Memory → Model → Avatar → Ready
    - 每步返回状态 (ok/detail), 失败可定位
    - 不阻塞: 逐步执行, 每步可跳过 (配置)

设计原则:
    - 一键启动, 用户无需手动选择模型/开启功能/连接服务
    - 每步必须返回状态 (可展示 ✓/✗)
    - 失败不崩溃: 返回 error 步骤 + 可重试
    - 线程安全 (RLock)
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 启动步骤 (可解释)
STARTUP_STEPS: List[str] = [
    "environment",  # 环境检查
    "config",       # 配置加载
    "backend",      # 后端连接
    "runtime",      # Runtime 验证
    "identity",     # 身份加载
    "memory",       # 记忆加载
    "model",        # 模型初始化
    "avatar",       # 形象初始化
    "ready",        # 就绪
]


class StartupCoreError(Exception):
    """启动核心异常"""


class StartupCore:
    """一键启动核心 (V10.1 Frontend)

    用法:
        core = StartupCore(backend_url="http://127.0.0.1:8000")
        for step in core.run():
            print(step)  # {step, ok, detail, elapsed_ms}
    """

    def __init__(
        self,
        backend_url: str = "http://127.0.0.1:8000",
        root_dir: Optional[str] = None,
        timeout: float = 5.0,
    ):
        self._lock = threading.RLock()
        self._backend_url = str(backend_url).rstrip("/")
        self._root_dir = root_dir or str(
            Path(__file__).resolve().parent.parent.parent,
        )
        self._timeout = float(timeout)
        self._results: Dict[str, Dict[str, Any]] = {}

    # ── 主入口 ──────────────────────────────────────────────────
    def run(
        self,
        skip: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """执行一键启动全流程

        Args:
            skip: 跳过步骤列表 (默认不跳过)

        Returns:
            每步结果: {step, ok, detail, elapsed_ms, skipped}
        """
        skip_set = set(skip or [])
        steps: List[Dict[str, Any]] = []
        with self._lock:
            self._results.clear()
        for name in STARTUP_STEPS:
            if name in skip_set:
                steps.append({
                    "step": name, "ok": True,
                    "detail": "已跳过", "elapsed_ms": 0.0,
                    "skipped": True,
                })
                continue
            start = time.perf_counter()
            try:
                result = self._dispatch(name)
                ok = bool(result.get("ok", False))
                detail = result.get("detail", "")
            except Exception as e:  # noqa: BLE001 启动隔离
                ok = False
                detail = f"异常: {e}"
                logger.error(f"[Startup] {name} 失败: {e}")
            elapsed = round(
                (time.perf_counter() - start) * 1000.0, 1,
            )
            entry = {
                "step": name, "ok": ok,
                "detail": detail, "elapsed_ms": elapsed,
                "skipped": False,
            }
            with self._lock:
                self._results[name] = dict(entry)
            steps.append(entry)
            if not ok and name != "ready":
                # 失败不继续 (ready 步骤本身无条件)
                break
        return steps

    def _dispatch(self, name: str) -> Dict[str, Any]:
        """分派步骤执行"""
        handlers: Dict[str, Callable[[], Dict[str, Any]]] = {
            "environment": self._check_environment,
            "config": self._load_config,
            "backend": self._connect_backend,
            "runtime": self._verify_runtime,
            "identity": self._load_identity,
            "memory": self._load_memory,
            "model": self._init_model,
            "avatar": self._init_avatar,
            "ready": lambda: {"ok": True, "detail": "元亨在线"},
        }
        fn = handlers.get(name)
        if fn is None:
            raise StartupCoreError(f"未知启动步骤: {name}")
        return fn()

    # ── 步骤实现 ────────────────────────────────────────────────
    def _check_environment(self) -> Dict[str, Any]:
        """环境检查: Python/依赖/目录"""
        import sys
        deps_ok = True
        missing: List[str] = []
        for mod in ("flask", "requests", "psutil"):
            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)
                deps_ok = False
        dirs_ok = True
        for d in ("logs", "webui_templates", "webui_static"):
            Path(self._root_dir, d).mkdir(exist_ok=True)
        return {
            "ok": deps_ok and dirs_ok,
            "detail": (
                f"Python {sys.version_info.major}.{sys.version_info.minor}"
                + ("" if deps_ok else f" 缺少依赖: {missing}")
            ),
        }

    def _load_config(self) -> Dict[str, Any]:
        """配置加载: webui_config.json / gui_config.json"""
        cfg = {}
        for name in ("webui_config.json", "gui_config.json"):
            p = Path(self._root_dir, name)
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        cfg[name] = json.load(f)
                except Exception as e:
                    logger.warning(f"[Startup] 配置读取失败 {name}: {e}")
        return {
            "ok": True,
            "detail": f"配置 {len(cfg)} 项",
        }

    def _connect_backend(self) -> Dict[str, Any]:
        """后端连接: 探测 :8000"""
        return self._http_get("/health", "后端服务在线")

    def _verify_runtime(self) -> Dict[str, Any]:
        """Runtime 验证: 模块状态"""
        return self._http_get("/modules/status", "Runtime 正常")

    def _load_identity(self) -> Dict[str, Any]:
        """身份加载: 人格配置"""
        return self._http_get("/personality/current", "身份已加载")

    def _load_memory(self) -> Dict[str, Any]:
        """记忆加载: 记忆统计"""
        return self._http_get("/memory/list", "记忆已加载")

    def _init_model(self) -> Dict[str, Any]:
        """模型初始化: TTS 引擎列表"""
        return self._http_get("/tts/engines", "模型已初始化")

    def _init_avatar(self) -> Dict[str, Any]:
        """形象初始化: 检测 Live2D 模型目录"""
        model_dir = Path(self._root_dir, "assets", "live2d")
        models = []
        if model_dir.is_dir():
            models = [
                p.name for p in model_dir.iterdir()
                if p.is_dir() and any(
                    f.suffix == ".json" for f in p.iterdir()
                )
            ]
        ok = len(models) > 0
        return {
            "ok": ok,
            "detail": (
                f"Live2D 模型 {len(models)} 个: {models[:3]}"
                if ok else "未检测到 Live2D 模型 (将使用占位形象)"
            ),
        }

    # ── 工具 ────────────────────────────────────────────────────
    def _http_get(self, path: str, ok_detail: str) -> Dict[str, Any]:
        """HTTP GET 探测后端"""
        url = f"{self._backend_url}{path}"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "YHLZ-Frontend/1.0",
            })
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                status = r.status
            if status == 200:
                return {"ok": True, "detail": ok_detail}
            return {
                "ok": False,
                "detail": f"HTTP {status}: {path}",
            }
        except Exception as e:
            return {
                "ok": False,
                "detail": f"后端不可达 ({self._backend_url}{path}): {e}",
            }

    # ── 查询 ────────────────────────────────────────────────────
    def result(self, step: str) -> Optional[Dict[str, Any]]:
        """查询某步骤结果"""
        with self._lock:
            r = self._results.get(step)
            return dict(r) if r else None

    def results(self) -> Dict[str, Dict[str, Any]]:
        """全部步骤结果"""
        with self._lock:
            return {k: dict(v) for k, v in self._results.items()}

    def all_ok(self) -> bool:
        """是否全部成功 (已运行步骤全部 ok, ready 步已执行)"""
        with self._lock:
            if "ready" not in self._results:
                return False
            return all(
                v.get("ok", False) or v.get("skipped", False)
                for v in self._results.values()
            )

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            ok_count = sum(
                1 for v in self._results.values()
                if v.get("ok") or v.get("skipped")
            )
            return {
                "mode": "rule_based",
                "backend_url": self._backend_url,
                "steps_total": len(STARTUP_STEPS),
                "steps_ok": ok_count,
                "steps_run": len(self._results),
            }


__all__ = [
    "STARTUP_STEPS",
    "StartupCore",
    "StartupCoreError",
]
