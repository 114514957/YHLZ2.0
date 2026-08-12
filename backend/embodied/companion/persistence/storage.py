"""
YHLZ Embodied AI V6.0 - 统一持久化存储 (JSONL Storage)

职责:
    - 统一 JSONL 状态存储 (所有子系统状态经此读写)
    - 原子写入 (临时文件 + rename, 防中途崩溃损坏)
    - 记录校验 (schema_version / type / timestamp / data)
    - 损坏数据跳过 (不崩溃, 计数返回)

格式:
    {"schema_version": "9.5.0", "type": "experience",
     "timestamp": 123.0, "data": {...}}

设计原则:
    - 纯规则, 无黑盒
    - 损坏行跳过并计数 (可审计)
    - 线程安全 (RLock)
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """存储操作异常"""


# 记录必填字段 (可解释)
REQUIRED_FIELDS: List[str] = [
    "schema_version",  # 结构版本
    "type",            # 记录类型
    "timestamp",       # 时间戳
    "data",            # 数据体
]


class JSONLStorage:
    """JSONL 存储 (原子写 + 校验 + 损坏跳过)

    用法:
        storage = JSONLStorage()
        storage.write(path, records)
        records, skipped = storage.read(path)
        storage.append(path, record)
    """

    def __init__(self, schema_version: str = "9.5.0"):
        if not schema_version:
            raise StorageError("schema_version 不能为空")
        self._lock = threading.RLock()
        self._schema_version = str(schema_version)

    # ── 写入 (原子) ──────────────────────────────────────────────
    def write(self, path: str,
              records: List[Dict[str, Any]]) -> int:
        """全量写入 (原子: 临时文件 + rename)

        Args:
            path: 目标文件路径
            records: 记录列表 (每条含 data)

        Returns:
            写入条数
        """
        with self._lock:
            if not path:
                raise StorageError("未指定存储路径")
            try:
                os.makedirs(
                    os.path.dirname(os.path.abspath(path)),
                    exist_ok=True,
                )
            except OSError as e:
                raise StorageError(f"创建目录失败: {e}")
            tmp_path = path + ".tmp"
            n = 0
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    for rec in records:
                        line = self._serialize(rec)
                        f.write(line + "\n")
                        n += 1
                # 原子替换 (避免中途崩溃产生半文件)
                os.replace(tmp_path, path)
            except OSError as e:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                raise StorageError(f"写入失败: {e}")
            logger.info(f"[Storage] 写入 {n} 条到 {path}")
            return n

    def append(self, path: str, record: Dict[str, Any]) -> int:
        """追加一条记录 (原子: 先写再 rename)

        注: 追加同样走临时文件合并, 保证一致性
        """
        with self._lock:
            if not path:
                raise StorageError("未指定存储路径")
            try:
                os.makedirs(
                    os.path.dirname(os.path.abspath(path)),
                    exist_ok=True,
                )
                existing = []
                if os.path.exists(path):
                    existing, _ = self.read(path)
                existing.append(record)
                return self.write(path, existing)
            except StorageError:
                raise
            except Exception as e:
                raise StorageError(f"追加失败: {e}")

    # ── 读取 (损坏跳过) ─────────────────────────────────────────
    def read(self, path: str) -> Tuple[List[Dict[str, Any]], int]:
        """读取全部有效记录

        Args:
            path: 文件路径

        Returns:
            (records, skipped): 有效记录 + 损坏跳过数

        Raises:
            StorageError: 文件不存在 / 读取失败
        """
        with self._lock:
            if not path:
                raise StorageError("未指定存储路径")
            if not os.path.exists(path):
                raise StorageError(f"文件不存在: {path}")
            records: List[Dict[str, Any]] = []
            skipped = 0
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        ok, rec, reason = self.validate_line(line)
                        if ok:
                            records.append(rec)
                        else:
                            skipped += 1
                            logger.warning(
                                f"[Storage] 跳过损坏行: {reason}",
                            )
            except OSError as e:
                raise StorageError(f"读取失败: {e}")
            return records, skipped

    # ── 校验 (可解释) ───────────────────────────────────────────
    def validate_line(self, line: str) -> Tuple[bool, Optional[Dict], str]:
        """校验单行 JSONL

        Returns:
            (ok, record, reason)
        """
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            return False, None, "JSON 解析失败"
        missing = [f for f in REQUIRED_FIELDS if f not in rec]
        if missing:
            return False, None, f"缺字段 {missing}"
        if not isinstance(rec["data"], dict):
            return False, None, "data 必须是对象"
        return True, rec, "ok"

    def build_record(self, rtype: str, data: Dict[str, Any],
                     timestamp: Optional[float] = None) -> Dict[str, Any]:
        """构造标准记录"""
        if not rtype:
            raise StorageError("记录类型不能为空")
        if not isinstance(data, dict):
            raise StorageError("data 必须是 dict")
        return {
            "schema_version": self._schema_version,
            "type": rtype,
            "timestamp": timestamp if timestamp is not None
            else time.time(),
            "data": data,
        }

    def _serialize(self, rec: Dict[str, Any]) -> str:
        """序列化 (校验后输出 JSON 行)"""
        ok, valid, reason = self.validate_line(
            json.dumps(rec, ensure_ascii=False),
        )
        if not ok:
            raise StorageError(f"非法记录: {reason}")
        return json.dumps(rec, ensure_ascii=False)

    # ── 统计 ─────────────────────────────────────────────────────
    @staticmethod
    def by_type(records: List[Dict[str, Any]]) -> Dict[str, int]:
        """按类型统计"""
        out: Dict[str, int] = {}
        for r in records:
            out[r["type"]] = out.get(r["type"], 0) + 1
        return out

    def stats(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """存储统计"""
        return {
            "mode": "rule_based",
            "schema_version": self._schema_version,
            "total": len(records),
            "by_type": self.by_type(records),
        }


__all__ = [
    "JSONLStorage",
    "REQUIRED_FIELDS",
    "StorageError",
]
