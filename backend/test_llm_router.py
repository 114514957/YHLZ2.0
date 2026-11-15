# -*- coding: utf-8 -*-
"""llm_router / llm_endpoint / llm_usage 的单测（**不联网**）。

覆盖：
  1. 端点解析：默认 cloud；env 覆盖；云端缺密钥要**明确报错**
  2. 记账：记录能落盘、summary 能汇总
  3. 重试：前两次失败第三次成功 → 返回结果且 retries=2
  4. 重试耗尽 → 抛 LLMUnavailable（**不静默降级**）
  5. 4xx（非 429）不重试
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import llm_endpoint as EP  # noqa: E402
from backend import llm_router as R  # noqa: E402
from backend import llm_usage as U  # noqa: E402


class EndpointTest(unittest.TestCase):
    def setUp(self):
        EP.reload()
        self._env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        EP.reload()

    def test_default_cloud(self):
        for k in ("YHLZ_LLM_PROVIDER", "YHLZ_LLM_BASE_URL", "YHLZ_LLM_MODEL",
                  "YHLZ_LLM_KEY"):
            os.environ.pop(k, None)
        ep = EP.endpoint()
        self.assertEqual(ep["provider"], "cloud")
        self.assertIn("deepseek", ep["base_url"])
        self.assertTrue(ep["api_key"], "本机配置里应有密钥")

    def test_env_override(self):
        os.environ["YHLZ_LLM_MODEL"] = "deepseek-reasoner"
        os.environ["YHLZ_LLM_PROVIDER"] = "local"
        EP.reload()
        ep = EP.endpoint()
        self.assertEqual(ep["provider"], "local")
        self.assertEqual(ep["model"], "deepseek-reasoner")

    def test_cloud_without_key_raises(self):
        os.environ["YHLZ_LLM_PROVIDER"] = "cloud"
        os.environ["YHLZ_LLM_KEY"] = ""
        EP.reload()
        with mock.patch.object(EP, "CONFIG_PATH", Path(tempfile.mkdtemp()) / "none.json"):
            EP.reload()
            with self.assertRaises(RuntimeError):
                EP.endpoint()


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = self.tmp / "llm_usage.jsonl"
        self._orig = U._PATH
        U._PATH = self.p

    def tearDown(self):
        U._PATH = self._orig

    def test_record_and_summary(self):
        U.record(channel="qq", model="deepseek-chat", provider="cloud",
                 prompt_tokens=1000, completion_tokens=500, seconds=1.2)
        U.record(channel="qq", model="deepseek-chat", provider="cloud",
                 prompt_tokens=2000, completion_tokens=300, seconds=0.8, ok=False,
                 error="boom")
        s = U.summary(self.p)
        self.assertEqual(s["calls"], 2)
        self.assertEqual(s["in"], 3000)
        self.assertEqual(s["out"], 800)
        self.assertEqual(s["fails"], 1)
        self.assertGreater(s["cost"], 0)
        self.assertLessEqual(s["p50"], s["p95"])


class RetryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = U._PATH
        U._PATH = self.tmp / "u.jsonl"
        EP.reload()

    def tearDown(self):
        U._PATH = self._orig
        EP.reload()

    def test_retry_then_success(self):
        calls = {"n": 0}

        def flaky(body, to):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("net down")
            return {"choices": [{"message": {"content": "好"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2}}, 0.5

        with mock.patch.object(R, "_once", side_effect=flaky), \
                mock.patch.object(R.time, "sleep", lambda *_: None):
            out = R.chat([{"role": "user", "content": "在吗"}], retries=3)
        self.assertEqual(out["choices"][0]["message"]["content"], "好")
        self.assertEqual(calls["n"], 3)

    def test_exhausted_raises(self):
        def always_fail(body, to):
            raise RuntimeError("down")

        with mock.patch.object(R, "_once", side_effect=always_fail), \
                mock.patch.object(R.time, "sleep", lambda *_: None):
            with self.assertRaises(R.LLMUnavailable):
                R.chat([{"role": "user", "content": "在吗"}], retries=2)

    def test_4xx_not_retried(self):
        import urllib.error
        calls = {"n": 0}

        def bad_request(body, to):
            calls["n"] += 1
            raise urllib.error.HTTPError("u", 401, "unauthorized", {}, io.BytesIO(b""))

        with mock.patch.object(R, "_once", side_effect=bad_request), \
                mock.patch.object(R.time, "sleep", lambda *_: None):
            with self.assertRaises(R.LLMUnavailable):
                R.chat([{"role": "user", "content": "在吗"}], retries=3)
        self.assertEqual(calls["n"], 1, "401 不该重试")


if __name__ == "__main__":
    unittest.main(verbosity=2)
