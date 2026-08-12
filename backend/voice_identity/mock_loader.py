"""
YHLZ Voice Identity System V2.3-Phase6 - Mock Model Loader 测试环境优化

职责:
    - 提供 TEST_MODE 全局开关 (环境变量 YHLZ_TEST_MODE=true)
    - MockModelLoader: 强制使用 mock adapter, 不加载 GPU / 真实模型
    - 让 API 测试 100% 可运行 (不依赖 Qwen3 / GPT-SoVITS 真实环境)

设计原则:
    - 纯 stdlib, 无新依赖
    - 不修改已有 Adapter 类, 通过构造参数 mode="mock" 实现
    - 测试启动时调用 setup_test_mode() 即可全局生效
    - 生产环境不受影响 (TEST_MODE 默认关闭)

使用:
    # 测试模块顶部
    from backend.voice_identity.mock_loader import setup_test_mode, is_test_mode
    setup_test_mode()  # 启用 TEST_MODE

    # 或通过环境变量 (启动前设置)
    export YHLZ_TEST_MODE=true
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional

from backend.voice_identity.adapter.tts_adapter import (
    TTSAdapter,
    VoiceCacheInfo,
    build_adapter,
)
from backend.voice_identity.clone.result import Err, Ok, Result

logger = logging.getLogger(__name__)

# 环境变量名
ENV_TEST_MODE = "YHLZ_TEST_MODE"


def _read_env_test_mode() -> bool:
    """从环境变量读取 TEST_MODE"""
    val = os.environ.get(ENV_TEST_MODE, "").lower().strip()
    return val in ("1", "true", "yes", "on")


# 全局 TEST_MODE 状态 (默认从环境变量读取)
_test_mode: bool = _read_env_test_mode()
_test_mode_lock = threading.Lock()


def is_test_mode() -> bool:
    """查询当前是否处于 TEST_MODE"""
    with _test_mode_lock:
        return _test_mode


def set_test_mode(enabled: bool) -> None:
    """显式设置 TEST_MODE (覆盖环境变量)"""
    global _test_mode
    with _test_mode_lock:
        old = _test_mode
        _test_mode = enabled
    if old != enabled:
        logger.info(f"TEST_MODE: {old} → {enabled}")
    # 同步到环境变量 (便于子进程继承)
    os.environ[ENV_TEST_MODE] = "true" if enabled else "false"


def setup_test_mode() -> None:
    """启用 TEST_MODE (一键启动测试环境)

    等价于 set_test_mode(True), 语义更清晰
    """
    set_test_mode(True)


def teardown_test_mode() -> None:
    """关闭 TEST_MODE (测试结束清理)"""
    set_test_mode(False)


class MockModelLoader:
    """Mock 模型加载器

    职责:
        - 在 TEST_MODE 下, 强制以 mock 模式构造 Adapter
        - 不加载 GPU / 真实模型 / Gradio 连接
        - 返回的 Adapter prepare/synthesize 行为与 mock 模式一致

    使用:
        loader = MockModelLoader()
        adapter = loader.load("qwen3")  # 返回 mock Qwen3TTSAdapter
        adapter = loader.load("gpt_sovits")  # 返回 mock GPTSoVITSAdapter
    """

    # 支持的引擎及其 mock 默认配置
    MOCK_CONFIGS: Dict[str, Dict[str, Any]] = {
        "qwen3": {"mode": "mock"},
        "gpt_sovits": {"mode": "mock"},
    }

    def __init__(self, cache_dir: Optional[str] = None):
        self._cache_dir = cache_dir
        self._loaded: Dict[str, TTSAdapter] = {}

    def load(self, engine: str) -> Result[TTSAdapter]:
        """加载 mock adapter

        参数:
            engine: 引擎名 (qwen3 / gpt_sovits)

        返回:
            Ok(TTSAdapter) / Err(原因)
        """
        if engine in self._loaded:
            return Ok(self._loaded[engine])

        config = dict(self.MOCK_CONFIGS.get(engine, {"mode": "mock"}))
        if self._cache_dir is not None:
            config["cache_dir"] = self._cache_dir

        result = build_adapter(engine, config)
        if result.is_err():
            return Err(f"MockModelLoader 加载 {engine} 失败: {result.error}")

        adapter = result.unwrap()
        self._loaded[engine] = adapter
        logger.info(f"MockModelLoader 已加载 {engine} (mock 模式)")
        return Ok(adapter)

    def unload(self, engine: Optional[str] = None) -> None:
        """卸载 mock adapter (None 卸载全部)"""
        if engine is None:
            self._loaded.clear()
        else:
            self._loaded.pop(engine, None)

    def health_check(self) -> Dict[str, Any]:
        """健康检查 (mock 模式始终 ok)"""
        return {
            "test_mode": is_test_mode(),
            "loaded_engines": list(self._loaded.keys()),
            "mock": True,
            "ok": True,
        }


# ==================================================================
# 模块级单例
# ==================================================================

_mock_loader: Optional[MockModelLoader] = None
_mock_loader_lock = threading.Lock()


def get_mock_loader() -> MockModelLoader:
    """获取全局 MockModelLoader 单例"""
    global _mock_loader
    with _mock_loader_lock:
        if _mock_loader is None:
            _mock_loader = MockModelLoader()
        return _mock_loader


def reset_mock_loader() -> None:
    """重置全局单例 (测试用)"""
    global _mock_loader
    with _mock_loader_lock:
        _mock_loader = None


def build_adapter_test_aware(
    engine: str,
    config: Optional[Dict[str, Any]] = None,
) -> Result[TTSAdapter]:
    """TEST_MODE 感知的 adapter 构造器

    - TEST_MODE=true: 强制 mock 模式 (忽略 config 中的 mode/model_path)
    - TEST_MODE=false: 透传给 build_adapter (生产路径)

    用于替换 service.load_adapter_from_config 中的构造调用
    """
    if is_test_mode():
        loader = get_mock_loader()
        return loader.load(engine)

    # 生产路径: 透传
    return build_adapter(engine, config or {})


def build_adapter_from_config_test_aware(
    engine: str,
    config: Optional[Any] = None,
) -> Result[TTSAdapter]:
    """TEST_MODE 感知的 build_adapter_from_config 替代

    与 build_adapter_from_config 签名兼容, 但在 TEST_MODE 下走 mock 路径
    """
    if is_test_mode():
        loader = get_mock_loader()
        return loader.load(engine)

    # 生产路径: 走原始 build_adapter_from_config
    from backend.voice_identity.adapter.config import build_adapter_from_config
    return build_adapter_from_config(engine, config)
