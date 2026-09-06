"""Access capability tests (0168): file read-only guard + web content discipline."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from backend.target_access import file_list, file_read, web_fetch, _category_blocked
from backend.target_scheduler_tools import setup_scheduler_capabilities


class TestFileGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "a.txt").write_text("hello world", encoding="utf-8")
        (self.tmp / "b.md").write_text("# title\ncontent", encoding="utf-8")
        (self.tmp / ".env").write_text("SECRET=1", encoding="utf-8")
        (self.tmp / "big.bin").write_bytes(b"\x00" * 2_000_000)

    def test_list(self):
        out = file_list(str(self.tmp))
        self.assertIn("a.txt", out)
        self.assertIn("b.md", out)

    def test_read_text(self):
        self.assertEqual(file_read(str(self.tmp / "a.txt")), "hello world")

    def test_sensitive_refused(self):
        out = file_read(str(self.tmp / ".env"))
        self.assertIn("拒绝", out)

    def test_binary_and_huge_refused(self):
        (self.tmp / "small.bin").write_bytes(b"\x00" * 128)
        self.assertIn("非文本", file_read(str(self.tmp / "small.bin")))
        big_text = self.tmp / "big.txt"
        big_text.write_text("x" * 2_000_000, encoding="utf-8")
        self.assertIn("过大", file_read(str(big_text)))
        self.assertIn("过大", file_read(str(self.tmp / "big.bin")))

    def test_registry_exposes_file_and_web(self):
        reg = setup_scheduler_capabilities()
        names = set(reg.names())
        self.assertTrue(
            {"file.list", "file.read", "web.fetch", "web.search"} <= names
        )


class TestWebDiscipline(unittest.TestCase):
    def test_category_blocker(self):
        self.assertEqual(_category_blocked("watch free xxx video"), "adult")

    def test_fetch_rejects_bad_url(self):
        async def go():
            return await web_fetch("ftp://x")

        self.assertIn("仅支持", asyncio.run(go()))

    def test_registry_web_fetch_url_passed_through(self):
        """Regression: handler must unwrap the params dict (bug: dict was fed
        to web_fetch as its url, failing the scheme check)."""
        async def go():
            reg = setup_scheduler_capabilities()
            r = await reg.execute_openai_async(
                "web_fetch", {"url": "https://127.0.0.1:9/x", "max_chars": 200})
            return r

        out = asyncio.run(go())
        self.assertTrue(out["ok"])  # passed scheme validation
        self.assertNotIn("仅支持", out["output"])  # not the old false rejection

    def test_registry_async_execute_file(self):
        async def go():
            reg = setup_scheduler_capabilities()
            return await reg.execute_openai_async(
                "file_list", {"path": str(self_tmp)})

        import tempfile as _t
        from pathlib import Path as _P

        self_tmp = _P(_t.mkdtemp())
        (self_tmp / "x.py").write_text("print(1)", encoding="utf-8")

        async def go2():
            reg = setup_scheduler_capabilities()
            return await reg.execute_openai_async(
                "file_list", {"path": str(self_tmp)})

        r = asyncio.run(go2())
        self.assertTrue(r["ok"])
        self.assertIn("x.py", r["output"])


if __name__ == "__main__":
    unittest.main()
