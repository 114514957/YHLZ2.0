"""
YHLZ Voice Identity System - 上传音频清理模块测试

覆盖:
    - cleanup_expired: TTL 清理
    - cleanup_file: 单文件删除
    - cleanup_all: 全量清理
    - 边界: 目录不存在 / 空目录 / 非音频文件保留
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import wave
import math
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from backend.voice_identity.adapter.upload_cleaner import (
    CleanStats,
    cleanup_expired,
    cleanup_file,
    cleanup_all,
    _iter_audio_files,
)
from backend.voice_identity.adapter.config import UploadConfig


def _make_wav(path: str, duration_s: float = 1.0, sr: int = 16000) -> None:
    """生成 wav 文件"""
    n = int(duration_s * sr)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sr))
            frames.extend(struct.pack("<h", v))
        w.writeframes(bytes(frames))


def _touch(path: str, age_seconds: float) -> None:
    """修改文件 mtime 为 age_seconds 前"""
    t = time.time() - age_seconds
    os.utime(path, (t, t))


class TestUploadCleaner(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="yhlz_cleaner_")
        self.cfg = UploadConfig(temp_dir=self.tmp_dir, ttl_seconds=100)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_file(self, name: str, age: float = 0, ext: str = ".wav") -> str:
        path = os.path.join(self.tmp_dir, name + ext)
        _make_wav(path, 0.5)
        if age > 0:
            _touch(path, age)
        return path

    # ------------------------------------------------------------------
    # cleanup_expired
    # ------------------------------------------------------------------

    def test_cleanup_expired_deletes_old_files(self):
        """TTL 清理: 删除超时文件, 保留新文件"""
        old = self._make_file("old", age=200)  # 200s 前 > TTL 100s
        new = self._make_file("new", age=10)   # 10s 前 < TTL
        stats = cleanup_expired(config=self.cfg)
        self.assertEqual(stats.deleted, 1)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))

    def test_cleanup_expired_no_old_files(self):
        """无超时文件 → deleted=0"""
        self._make_file("a", age=10)
        self._make_file("b", age=20)
        stats = cleanup_expired(config=self.cfg)
        self.assertEqual(stats.deleted, 0)
        self.assertEqual(stats.scanned, 2)

    def test_cleanup_expired_empty_dir(self):
        """空目录 → scanned=0"""
        stats = cleanup_expired(config=self.cfg)
        self.assertEqual(stats.scanned, 0)
        self.assertEqual(stats.deleted, 0)

    def test_cleanup_expired_dir_not_exist(self):
        """目录不存在 → 空结果"""
        cfg = UploadConfig(temp_dir="/nonexistent/path", ttl_seconds=10)
        stats = cleanup_expired(config=cfg)
        self.assertEqual(stats.scanned, 0)

    def test_cleanup_expired_ttl_zero_skips(self):
        """TTL<=0 → 跳过清理"""
        self._make_file("a", age=9999)
        cfg = UploadConfig(temp_dir=self.tmp_dir, ttl_seconds=0)
        stats = cleanup_expired(config=cfg)
        self.assertEqual(stats.deleted, 0)

    def test_non_audio_files_preserved(self):
        """非音频文件保留 (如 .txt)"""
        old_wav = self._make_file("old", age=200)
        txt_path = os.path.join(self.tmp_dir, "notes.txt")
        with open(txt_path, "w") as f:
            f.write("test")
        _touch(txt_path, 200)
        stats = cleanup_expired(config=self.cfg)
        self.assertEqual(stats.deleted, 1)  # 仅删 wav
        self.assertTrue(os.path.exists(txt_path))  # txt 保留

    # ------------------------------------------------------------------
    # cleanup_file
    # ------------------------------------------------------------------

    def test_cleanup_file_success(self):
        """单文件删除成功"""
        p = self._make_file("single")
        self.assertTrue(cleanup_file(p))
        self.assertFalse(os.path.exists(p))

    def test_cleanup_file_not_exist(self):
        """文件不存在 → False"""
        self.assertFalse(cleanup_file(os.path.join(self.tmp_dir, "nope.wav")))

    # ------------------------------------------------------------------
    # cleanup_all
    # ------------------------------------------------------------------

    def test_cleanup_all_deletes_everything(self):
        """全量清理: 删除所有音频 (无视 TTL)"""
        self._make_file("a", age=10)
        self._make_file("b", age=9999)
        self._make_file("c", age=1)
        stats = cleanup_all(config=self.cfg)
        self.assertEqual(stats.deleted, 3)
        self.assertEqual(stats.scanned, 3)

    def test_cleanup_all_with_non_audio(self):
        """全量清理仅删音频, 保留其他"""
        self._make_file("a")
        txt = os.path.join(self.tmp_dir, "x.txt")
        with open(txt, "w") as f:
            f.write("keep")
        stats = cleanup_all(config=self.cfg)
        self.assertEqual(stats.deleted, 1)
        self.assertTrue(os.path.exists(txt))

    # ------------------------------------------------------------------
    # _iter_audio_files
    # ------------------------------------------------------------------

    def test_iter_audio_files_filters_by_ext(self):
        """枚举: 仅返回支持的音频扩展名"""
        _make_wav(os.path.join(self.tmp_dir, "a.wav"), 0.3)
        _make_wav(os.path.join(self.tmp_dir, "b.mp3"), 0.3)
        with open(os.path.join(self.tmp_dir, "c.txt"), "w") as f:
            f.write("x")
        files = _iter_audio_files(self.tmp_dir)
        names = [f.name for f in files]
        self.assertIn("a.wav", names)
        # b.mp3 实际不是 wav, _make_wav 仍按 wav 写, 但扩展名 mp3 应被枚举到
        self.assertIn("b.mp3", names)
        self.assertNotIn("c.txt", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
