"""会话存档迁移的回归测试（ledger 0817）。

背景：`save_session` 的守卫**故意**拒绝静默接管"无 channel 的旧存档"
（`legacy public archive requires channel migration`）。2026-10-13 群 1094579571
的会话正因此每轮保存失败 → 上下文从不落盘 → 下一轮读回旧文件 → 表现成"精分"。

这里钉死三件事：
  1. 无 channel 的旧存档：非 owner 会话 **save 必须被拒**（守卫不能被绕过）；
  2. `migrate_legacy_archive()` 显式迁移后 **save 成功**，且**先备份**；
  3. 迁移是幂等的、坏名字被拒、别人的 channel 不能被冒用。
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend import target_entry as te  # noqa: E402


class _FakeMemory:
    def __init__(self) -> None:
        self.bound: list = []

    def bind_archive(self, history) -> None:
        self.bound.append(history)


def _session(channel: str, history=None) -> te.ConversationSession:
    s = te.ConversationSession.__new__(te.ConversationSession)
    s.channel = channel
    s.history = history if history is not None else [
        {"role": "user", "content": "老历史"},
        {"role": "assistant", "content": "老回复"},
    ]
    s.history_limit = 20
    s.memory = _FakeMemory()
    s._session_name = "default"
    s._is_owner = lambda: channel == "console"   # type: ignore[assignment]
    return s


class LegacyArchiveGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()) / "sessions"
        self.tmp.mkdir(parents=True)
        self.patch = mock.patch.object(te, "SESSIONS_DIR", self.tmp)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.legacy = self.tmp / "qq_qq_g1094579571.json"
        self.legacy.write_text(json.dumps(
            {"title": "老群会话", "turns": 5,
             "history": [{"role": "user", "content": "昨天聊过"}],
             "saved_at": time.time() - 86400}, ensure_ascii=False),
            encoding="utf-8")

    def test_guard_rejects_untagged_public_archive(self):
        s = _session("qq_g1094579571")
        with self.assertRaises(ValueError) as ctx:
            s.save_session("qq_qq_g1094579571")
        self.assertIn("channel migration", str(ctx.exception))

    def test_owner_session_still_may_overwrite(self):
        s = _session("console")
        s.save_session("qq_qq_g1094579571")     # owner：旧存档仍可用

    def test_migration_makes_save_work_and_backs_up(self):
        rep = te.ConversationSession.migrate_legacy_archive(
            "qq_qq_g1094579571", "qq_g1094579571")
        self.assertTrue(rep["ok"], rep)
        self.assertTrue(pathlib.Path(rep["backup"]).exists())
        data = json.loads(self.legacy.read_text(encoding="utf-8"))
        self.assertEqual(data["channel"], "qq_g1094579571")
        self.assertEqual(data["schema"], 2)
        self.assertEqual(data["migrated_from"], "legacy-no-channel")
        # 迁移后同一通道的 save 必须通过，且历史保留（旧 1 条 + 新 2 条）
        s = _session("qq_g1094579571")
        s.save_session("qq_qq_g1094579571")
        saved = json.loads(self.legacy.read_text(encoding="utf-8"))
        self.assertEqual(saved["channel"], "qq_g1094579571")
        self.assertEqual(len(saved["history"]), 2)   # 会话内存里的那两条

    def test_migration_is_idempotent_and_name_safe(self):
        te.ConversationSession.migrate_legacy_archive(
            "qq_qq_g1094579571", "qq_g1094579571")
        again = te.ConversationSession.migrate_legacy_archive(
            "qq_qq_g1094579571", "qq_g1094579571")
        self.assertFalse(again["ok"])
        self.assertEqual(again["reason"], "already-tagged")
        with self.assertRaises(ValueError):
            te.ConversationSession.migrate_legacy_archive("../evil", "x")
        self.assertEqual(
            te.ConversationSession.migrate_legacy_archive("nope", "x")["reason"],
            "missing")


if __name__ == "__main__":
    unittest.main()
