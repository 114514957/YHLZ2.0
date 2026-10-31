# -*- coding: utf-8 -*-
"""工具契约测试（2026-10-20，老爹要求「工具要经过测试可用，别写错调用就坏了」）。

三件事：
  1. **schema 合法**：每个暴露的工具都要能被 OpenAI tools 视图接受
     （name 合规、description 非空、parameters 是 object、required ⊆ properties）。
  2. **坏参数不崩**：用畸形参数打每个工具，必须返回 `{"ok": ...}` 而不是抛异常。
     —— 实测曾有两个真崩：`qq_process(max_items="abc")` 与 `qq_digest(date=12345)`。
  3. **关键工具真能用**：`qq.export` / `qq.status` 跑真实数据并断言结构。

安全约束（重要）：探针**绝不能让工具真干活**。
  · SCHEMA_ONLY 里的工具（会调云端/出声/联网/下载）只查 schema，不执行；
  · EARLY_FAIL 里的只打"校验阶段就失败"的参数。
"""
from __future__ import annotations

import asyncio
import json
import re
import unittest

from backend.target_scheduler_tools import setup_scheduler_capabilities

# 会真干活/花钱/出声/联网 → 不执行，只查 schema
SCHEMA_ONLY = {"qq_summarize", "song_play", "song_send", "file_download",
               "web_fetch", "web_search", "qq_digest"}

# 可以安全执行、且会早期失败
EARLY_FAIL = {
    "qq_process": [("max_items 非数字", {"max_items": "abc"})],
}

HOSTILE = [
    ("空参", {}),
    ("垃圾键", {"__bad__": 1}),
    ("类型错", {"limit": "not-a-number", "group_id": 12345}),
    ("空串", {"group_id": "", "query": "", "path": ""}),
    ("None 值", {"group_id": None, "limit": None, "query": None}),
]


def _reg():
    return setup_scheduler_capabilities()


def _names(reg) -> list[str]:
    return sorted(t["function"]["name"] for t in reg.export_openai_tools())


class TestToolSchema(unittest.TestCase):
    def test_schema_shape(self):
        reg = _reg()
        tools = reg.export_openai_tools()
        self.assertTrue(tools, "工具视图为空")
        for t in tools:
            self.assertEqual(t.get("type"), "function")
            fn = t.get("function") or {}
            name = fn.get("name") or ""
            self.assertRegex(name, r"^[a-z][a-z0-9_]*$", "工具名不合规: %r" % name)
            self.assertTrue((fn.get("description") or "").strip(),
                            "%s 缺 description" % name)
            params = fn.get("parameters")
            self.assertIsInstance(params, dict, "%s 的 parameters 不是对象" % name)
            self.assertEqual(params.get("type"), "object", "%s parameters.type 应为 object" % name)
            props = params.get("properties")
            self.assertIsInstance(props, dict, "%s 缺 properties" % name)
            for req in params.get("required") or []:
                self.assertIn(req, props, "%s 的 required「%s」不在 properties 里" % (name, req))

    def test_names_unique(self):
        reg = _reg()
        names = _names(reg)
        self.assertEqual(len(names), len(set(names)), "工具名重复")


class TestToolRobustness(unittest.TestCase):
    def test_bad_args_never_raise(self):
        reg = _reg()
        bad: list[str] = []
        for name in _names(reg):
            if name in SCHEMA_ONLY:
                continue
            cases = EARLY_FAIL.get(name, HOSTILE)
            for label, params in cases:
                try:
                    res = asyncio.run(reg.execute_openai_async(name, dict(params)))
                except Exception as exc:  # noqa: BLE001
                    bad.append("%s(%s) 抛 %s: %s"
                               % (name, label, type(exc).__name__, str(exc)[:80]))
                    continue
                if not isinstance(res, dict):
                    bad.append("%s(%s) 返回非 dict" % (name, label))
                elif "ok" not in res:
                    bad.append("%s(%s) 返回缺 ok" % (name, label))
        self.assertEqual(bad, [], "以下调用会让工具坏掉：\n" + "\n".join(bad))

    def test_qq_process_rejects_bad_max_items(self):
        reg = _reg()
        res = asyncio.run(reg.execute_openai_async("qq_process", {"max_items": "abc"}))
        # 注意区分两层 ok：
        #   注册表 ok=True 表示"工具跑完了、没抛异常"；
        #   载荷里 ok=False 表示"这次业务请求被拒"。后者才是我们要断言的。
        self.assertTrue(res.get("ok"), "工具本身不该失败")
        payload = json.loads(str(res.get("output")))
        self.assertFalse(payload.get("ok"), payload)
        self.assertIn("max_items", str(payload.get("error") or ""))
        self.assertEqual(payload.get("processed"), 0, "参数错了就不该真跑抽取")

    def test_qq_digest_rejects_bad_date(self):
        reg = _reg()
        res = asyncio.run(reg.execute_openai_async("qq_digest", {"date": 12345}))
        out = str(res.get("output") or res.get("error") or "")
        self.assertIn("YYYY-MM-DD", out)


class TestQQToolsRealBehavior(unittest.TestCase):
    """真数据断言：这两个只读、便宜，可以真跑。"""

    def test_qq_status_reports_real_counts(self):
        reg = _reg()
        res = asyncio.run(reg.execute_openai_async("qq_status", {}))
        self.assertTrue(res.get("ok"), res)
        out = str(res.get("output") or "")
        self.assertIn("QQ 数据状态", out)
        self.assertRegex(out, r"群历史 \d+ 条")
        self.assertRegex(out, r"知识库 \d+ 条")

    def test_qq_export_creates_files_and_counts(self):
        reg = _reg()
        res = asyncio.run(reg.execute_openai_async("qq_export", {}))
        self.assertTrue(res.get("ok"), res)
        payload = json.loads(str(res.get("output")))
        self.assertEqual(payload.get("source"), "lite_group_history")
        self.assertIsInstance(payload.get("messages"), int)
        self.assertGreaterEqual(payload.get("messages"), 0)
        self.assertIsInstance(payload.get("files"), list)
        for f in payload.get("files") or []:
            self.assertIn("group_id", f)
            self.assertIn("file", f)
            self.assertIsInstance(f.get("messages"), int)

    def test_qq_export_bad_group_is_error_not_crash(self):
        reg = _reg()
        res = asyncio.run(reg.execute_openai_async(
            "qq_export", {"group_id": "绝不可能存在的群名"}))
        # handler 自己会返回 ok:false 的 JSON（不是抛异常）
        out = str(res.get("output") or "")
        self.assertIn("对不上", out)
        self.assertIn("available", out)

    def test_qq_export_none_group_means_all(self):
        reg = _reg()
        res = asyncio.run(reg.execute_openai_async(
            "qq_export", {"group_id": None, "limit": None}))
        payload = json.loads(str(res.get("output")))
        self.assertTrue(payload.get("ok"), payload)
        self.assertGreaterEqual(payload.get("groups", 0), 1)


if __name__ == "__main__":
    unittest.main()
