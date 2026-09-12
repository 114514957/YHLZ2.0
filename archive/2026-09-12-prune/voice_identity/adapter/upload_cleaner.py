"""
YHLZ Voice Identity System V2.2 - 上传音频生命周期管理

职责:
    - 清理 _uploads 目录中超时的上传音频文件 (TTL)
    - 提供手动清理接口
    - 克隆成功后可选立即删除上传音频

设计原则:
    - 仅清理 upload.temp_dir 目录, 不触碰永久缓存
    - 按文件 mtime 判断超时
    - 所有操作记录日志, 返回清理统计
    - stdlib only, 不引入新依赖
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from backend.voice_identity.adapter.config import UploadConfig, load_config

logger = logging.getLogger(__name__)


@dataclass
class CleanStats:
    """清理统计"""
    scanned: int = 0          # 扫描文件数
    deleted: int = 0          # 已删除数
    failed: int = 0           # 删除失败数
    freed_bytes: int = 0      # 释放字节数
    errors: List[str] = None  # 错误信息列表

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def to_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "deleted": self.deleted,
            "failed": self.failed,
            "freed_bytes": self.freed_bytes,
            "freed_mb": round(self.freed_bytes / 1024 / 1024, 2),
            "errors": self.errors,
        }


def _iter_audio_files(temp_dir: str) -> List[Path]:
    """枚举 temp_dir 下的音频文件 (按扩展名过滤)"""
    p = Path(temp_dir)
    if not p.exists():
        return []
    exts = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
    return [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in exts]


def cleanup_expired(
    ttl_seconds: Optional[int] = None,
    config: Optional[UploadConfig] = None,
) -> CleanStats:
    """清理超时的上传音频文件

    参数:
        ttl_seconds: TTL (秒), None 则用配置默认值
        config: UploadConfig, None 则从配置文件加载

    返回:
        CleanStats 清理统计
    """
    cfg = config if config is not None else load_config().upload
    ttl = ttl_seconds if ttl_seconds is not None else cfg.ttl_seconds
    if ttl <= 0:
        logger.debug(f"TTL={ttl} (<=0), 跳过清理")
        return CleanStats()

    stats = CleanStats()
    now = time.time()
    files = _iter_audio_files(cfg.temp_dir)
    stats.scanned = len(files)

    for f in files:
        try:
            mtime = f.stat().st_mtime
            age = now - mtime
            if age > ttl:
                size = f.stat().st_size
                f.unlink()
                stats.deleted += 1
                stats.freed_bytes += size
                logger.debug(f"已删除超时上传音频: {f.name} (age={int(age)}s)")
        except Exception as e:
            stats.failed += 1
            stats.errors.append(f"{f.name}: {e}")
            logger.warning(f"删除上传音频失败: {f.name}: {e}")

    if stats.deleted > 0:
        logger.info(
            f"上传音频清理完成: 扫描={stats.scanned} 删除={stats.deleted} "
            f"失败={stats.failed} 释放={stats.freed_bytes}B"
        )
    return stats


def cleanup_file(path: str) -> bool:
    """删除单个上传音频文件 (克隆成功后调用)

    参数:
        path: 文件路径

    返回:
        True=已删除, False=失败或不存在
    """
    try:
        p = Path(path)
        if not p.exists():
            return False
        p.unlink()
        logger.debug(f"已删除上传音频: {p.name}")
        return True
    except Exception as e:
        logger.warning(f"删除上传音频失败: {path}: {e}")
        return False


def cleanup_all(config: Optional[UploadConfig] = None) -> CleanStats:
    """手动清理: 删除 temp_dir 下所有上传音频 (无视 TTL)

    参数:
        config: UploadConfig, None 则从配置文件加载

    返回:
        CleanStats 清理统计
    """
    cfg = config if config is not None else load_config().upload
    stats = CleanStats()
    files = _iter_audio_files(cfg.temp_dir)
    stats.scanned = len(files)

    for f in files:
        try:
            size = f.stat().st_size
            f.unlink()
            stats.deleted += 1
            stats.freed_bytes += size
        except Exception as e:
            stats.failed += 1
            stats.errors.append(f"{f.name}: {e}")

    logger.info(
        f"手动清理上传音频: 扫描={stats.scanned} 删除={stats.deleted} "
        f"失败={stats.failed} 释放={stats.freed_bytes}B"
    )
    return stats
