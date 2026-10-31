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


class TestFilePolicy(unittest.TestCase):
    """元亨文件策略：能发图文/能看非危险文件/能转发；不能增删改（2026-09-30）。"""

    def test_dangerous_paths(self):
        from backend.target_access import is_dangerous_path

        for p in ("C:/x/.env", "/home/u/secret.txt", "id_rsa", "auth.json",
                  "my.key", "credential.pem", "token_store.json"):
            self.assertTrue(is_dangerous_path(p), p)
        for p in ("C:/pics/cover.png", "docs/note.md", "音频素材/翻唱产出/a.wav"):
            self.assertFalse(is_dangerous_path(p), p)

    def test_can_view_and_send(self):
        from backend.target_access import can_send, can_view

        self.assertTrue(can_view("docs/note.md"))
        self.assertTrue(can_send("C:/pics/a.jpg"))
        self.assertFalse(can_view("C:/x/.env"))
        self.assertFalse(can_send("C:/x/.env"))

    def test_cannot_modify(self):
        from backend.target_access import can_modify, policy_summary

        self.assertFalse(can_modify())
        p = policy_summary()
        self.assertTrue(p["send_text_image"])
        self.assertTrue(p["view_safe_file"])
        self.assertTrue(p["forward"])
        self.assertFalse(p["add_delete_modify"])

    def test_qq_bridge_send_guard(self):
        from tools.qq_bot import QQBridge

        b = QQBridge("unused", "900", Path("unused"), masters={"100"})
        self.assertTrue(b._file_allowed("docs/note.md"))
        self.assertTrue(b._file_allowed("C:/pics/a.png"))
        self.assertFalse(b._file_allowed("C:/x/.env"))
        self.assertFalse(b._file_allowed("C:/keys/my.key"))


class TestFileBrowseDownloadShare(unittest.TestCase):
    """2026-10-06：文件浏览标注 / 下载 / 分享（主人会话）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        (self.tmp / "doc.md").write_text("# hi", encoding="utf-8")

    def test_list_annotates_kind(self):
        out = file_list(str(self.tmp))
        self.assertIn("[图片] pic.png", out)
        self.assertIn("[文本] doc.md", out)

    def test_share_check_rules(self):
        from backend.target_access import share_check

        ok, detail = share_check(str(self.tmp / "pic.png"))
        self.assertTrue(ok, detail)
        self.assertTrue(Path(detail).is_file())
        self.assertFalse(share_check(str(self.tmp))[0])          # directory
        self.assertFalse(share_check(str(self.tmp / "no.png"))[0])  # missing
        sensitive = self.tmp / "token_store.json"
        sensitive.write_text("{}", encoding="utf-8")
        self.assertFalse(share_check(str(sensitive))[0])

    def test_share_binding_owner_sink(self):
        from backend.target_scheduler_tools import bind_file_share_service

        reg = setup_scheduler_capabilities()
        got: list[str] = []
        bind_file_share_service(reg, got.append)

        async def go():
            return await reg.execute_openai_async(
                "file_share", {"path": str(self.tmp / "pic.png")})

        r = asyncio.run(go())
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0], str(self.tmp / "pic.png"))

    def test_share_unbound_fails_closed(self):
        reg = setup_scheduler_capabilities()
        r = reg.execute("file.share", {"path": str(self.tmp / "pic.png")})
        self.assertIn("未就绪", r["output"])
        self.assertEqual(r.get("attachments"), None)

    def test_download_rejects_denied_ext_and_scheme(self):
        from backend.target_access import file_download

        self.assertIn("仅支持", asyncio.run(file_download("ftp://x/a.png")))
        self.assertIn("不允许的文件类型",
                      asyncio.run(file_download("http://127.0.0.1:9/a.exe")))

    def test_download_saves_managed_file(self):
        import http.server
        import re
        import threading

        from backend.target_access import file_download

        payload = b"\x89PNG\r\n\x1a\n" + b"z" * 128

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}/pic.png"
            out = asyncio.run(file_download(url))
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertIn("已下载", out)
        p = Path(re.search(r"(\S+\.png)", out).group(1))
        try:
            self.assertEqual(p.read_bytes(), payload)
            self.assertIn("cache", str(p))
        finally:
            p.unlink(missing_ok=True)

    def test_registry_exposes_download_and_share(self):
        reg = setup_scheduler_capabilities()
        tools = {t["function"]["name"] for t in reg.export_openai_tools()}
        self.assertTrue({"file_download", "file_share"} <= tools)


if __name__ == "__main__":
    unittest.main()
