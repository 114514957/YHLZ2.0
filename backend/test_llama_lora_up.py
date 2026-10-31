"""llama_lora_up 测试（2026-09-25，台账 0502）。

只测**只读/纯函数**部分：LoRA 名解析、当前版本探查、列表输出。
绝不测 switch()——那会真的重启生产 8081。
"""
import pathlib
import tempfile
import unittest

from tools import llama_lora_up as up


class ResolveLoraTest(unittest.TestCase):
    def test_short_name_resolves(self):
        p = up.resolve_lora("v7b")
        self.assertTrue(p.is_file())
        self.assertEqual(p.name, "yuanheng-v7b-lora.gguf")

    def test_full_filename_resolves(self):
        self.assertEqual(up.resolve_lora("yuanheng-v6-lora.gguf").name,
                         "yuanheng-v6-lora.gguf")

    def test_bare_stem_resolves(self):
        self.assertEqual(up.resolve_lora("yuanheng-v6-lora").name,
                         "yuanheng-v6-lora.gguf")

    def test_production_default_matches_paths_module(self):
        """生产默认 LoRA（yhlz_paths）必须能被本工具解析到同一个文件。"""
        from backend.yhlz_paths import YH_LORA_GGUF

        self.assertEqual(up.resolve_lora(YH_LORA_GGUF.name), YH_LORA_GGUF)

    def test_unknown_name_raises_with_hint(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            up.resolve_lora("v99")
        self.assertIn("找不到", str(ctx.exception))
        self.assertIn("yuanheng-", str(ctx.exception))   # 提示可用清单

    def test_absolute_path_outside_dir_is_rejected(self):
        tmp = pathlib.Path(tempfile.mkdtemp()) / "x.gguf"
        with self.assertRaises(FileNotFoundError):
            up.resolve_lora(str(tmp))

    def test_empty_name_raises(self):
        with self.assertRaises(ValueError):
            up.resolve_lora("  ")


class IntrospectionTest(unittest.TestCase):
    """探查函数必须永不抛（评测/切换都靠它们判断环境）。"""

    def test_running_lora_shape(self):
        v = up.running_lora()
        self.assertIsInstance(v, str)
        self.assertTrue(v == "" or v.endswith(".gguf"), v)

    def test_running_port_is_int(self):
        self.assertIsInstance(up.running_port(), int)

    def test_health_ok_on_dead_port(self):
        self.assertFalse(up.health_ok(9, timeout=1.0))

    def test_port_free_detects_dead_port(self):
        self.assertTrue(up._port_free(9))

    def test_proc_arg_missing_flag_returns_empty(self):
        class _P:
            info = {"cmdline": ["a", "--port", "8081"]}

        self.assertEqual(up._proc_arg(_P(), "--lora"), "")
        self.assertEqual(up._proc_arg(_P(), "--port"), "8081")


class ListCommandTest(unittest.TestCase):
    def test_list_reports_available_loras(self):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = up.main(["--list"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("yuanheng-v7b-lora.gguf", out)
        self.assertIn("可用 LoRA", out)

    def test_show_reports_current(self):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = up.main(["--show"])
        self.assertEqual(rc, 0)
        self.assertIn("当前 LoRA", buf.getvalue())

    def test_no_args_is_an_error(self):
        with self.assertRaises(SystemExit):
            up.main([])


if __name__ == "__main__":
    unittest.main()