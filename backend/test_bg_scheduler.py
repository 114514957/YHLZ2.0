"""T5 统一后台推理调度测试（ledger 0613）。纯 asyncio，无模型/网络/DB。"""
from __future__ import annotations

import asyncio
import sys
import unittest

sys.path.insert(0, ".")

import backend.bg_scheduler as bg  # noqa: E402


class BgSchedulerTest(unittest.TestCase):
    def setUp(self):
        bg.reset_for_tests()

    def test_single_active_slot(self):
        async def main():
            running = {"n": 0, "max": 0}

            async def job():
                running["n"] += 1
                running["max"] = max(running["max"], running["n"])
                await asyncio.sleep(0.05)
                running["n"] -= 1
                return "ok"

            res = await asyncio.gather(bg.run(job), bg.run(job), bg.run(job))
            return res, running

        res, running = asyncio.run(main())
        self.assertEqual(running["max"], 1)
        self.assertTrue(all(r["ok"] for r in res))

    def test_foreground_priority_waits(self):
        async def main():
            bg.foreground_enter()
            task = asyncio.create_task(bg.run(lambda: asyncio.sleep(0, result="x")))
            await asyncio.sleep(0.05)
            started_while_fg = bg._counters["started"]
            bg.foreground_exit()
            r = await task
            return started_while_fg, r

        started_while_fg, r = asyncio.run(main())
        self.assertEqual(started_while_fg, 0)   # 前台期间后台未启动
        self.assertTrue(r["ok"])

    def test_policy_skip(self):
        async def main():
            return await bg.run(lambda: asyncio.sleep(0, result=1),
                                policy_check=lambda: False)

        r = asyncio.run(main())
        self.assertEqual(r["status"], "skipped_policy")
        self.assertEqual(bg._counters["skipped_policy"], 1)
        self.assertEqual(bg._counters["started"], 0)

    def test_timeout(self):
        async def main():
            return await bg.run(lambda: asyncio.sleep(5), timeout_s=0.05)

        r = asyncio.run(main())
        self.assertEqual(r["status"], "timeout")
        self.assertEqual(bg._counters["timeout"], 1)

    def test_error_recorded(self):
        async def boom():
            raise RuntimeError("x")

        r = asyncio.run(bg.run(boom))
        self.assertEqual(r["status"], "error")
        self.assertEqual(bg._counters["error"], 1)

    def test_status_has_recent(self):
        async def main():
            await bg.run(lambda: asyncio.sleep(0, result=1), kind="extract",
                         endpoint="8081")

        asyncio.run(main())
        s = bg.status()
        self.assertEqual(s["counters"]["done"], 1)
        self.assertEqual(s["recent"][-1]["kind"], "extract")
        self.assertEqual(s["recent"][-1]["endpoint"], "8081")


if __name__ == "__main__":
    unittest.main()
