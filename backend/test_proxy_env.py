"""代理环境消毒的回归测试（ledger 0815）。

2026-10-13 22:0x 事故：从 DSH 会话里重启的 daemon 继承了
`NO_PROXY=...,[::1]`，httpx 对**每个**请求抛 `InvalidURL: Invalid port: ':1]'`
→ 元亨在 QQ 上全哑。这里把"清方括号项、其余保留、大小写两份都扫"钉死。
"""
from __future__ import annotations

import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.env_loader import sanitize_proxy_env  # noqa: E402


class SanitizeProxyEnvTest(unittest.TestCase):
    def test_drops_bracketed_ipv6_and_keeps_rest(self):
        env = {"NO_PROXY": "localhost,127.0.0.1,::1,.maas.aliyuncs.com,[::1]"}
        changes = sanitize_proxy_env(env)
        self.assertEqual(env["NO_PROXY"],
                         "localhost,127.0.0.1,::1,.maas.aliyuncs.com")
        self.assertTrue(changes and "NO_PROXY" in changes[0])

    def test_no_change_when_clean(self):
        env = {"NO_PROXY": "localhost,127.0.0.1"}
        self.assertEqual(sanitize_proxy_env(env), [])
        self.assertEqual(env["NO_PROXY"], "localhost,127.0.0.1")

    def test_small_case_variant_too(self):
        env = {"no_proxy": "[::1],localhost"}
        sanitize_proxy_env(env)
        self.assertEqual(env["no_proxy"], "localhost")

    def test_untouched_without_bracketed_entries(self):
        """没方括号项就一个字都不改（保守：不动用户配置）。"""
        env = {"NO_PROXY": " b , a ,b,, "}
        self.assertEqual(sanitize_proxy_env(env), [])
        self.assertEqual(env["NO_PROXY"], " b , a ,b,, ")

    def test_dedupes_and_trims_when_it_does_rewrite(self):
        env = {"NO_PROXY": " b ,[::1], b , a "}
        sanitize_proxy_env(env)
        self.assertEqual(env["NO_PROXY"], "b,a")

    def test_proxy_urls_untouched(self):
        env = {"HTTP_PROXY": "http://127.0.0.1:7897",
               "HTTPS_PROXY": "http://127.0.0.1:7897", "NO_PROXY": "[::1]"}
        sanitize_proxy_env(env)
        self.assertEqual(env["HTTP_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(env["NO_PROXY"], "")

    def test_missing_key_is_fine(self):
        self.assertEqual(sanitize_proxy_env({}), [])

    def test_httpx_really_accepts_the_sanitized_value(self):
        """端到端机制验证：清过之后 httpx 能建 client（不清就 InvalidURL）。"""
        try:
            import httpx
        except Exception:  # noqa: BLE001
            self.skipTest("httpx 不可用")
        import os

        bad = "localhost,127.0.0.1,[::1]"
        env = {"NO_PROXY": bad, "no_proxy": bad,
               "HTTP_PROXY": "http://127.0.0.1:7897"}
        old = {k: os.environ.get(k) for k in env}
        try:
            os.environ.update(env)
            with self.assertRaises(httpx.InvalidURL):
                httpx.Client(timeout=1)
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            clean = dict(env)
            sanitize_proxy_env(clean)
            os.environ.update(clean)
            with httpx.Client(timeout=1) as client:
                self.assertIsNotNone(client)
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
