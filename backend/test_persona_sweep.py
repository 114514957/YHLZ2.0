"""persona_version_sweep 测试（2026-09-25，台账 0502）。

只测不碰进程的纯部分：文件名映射、以及两条设计不变式——
①默认扫描必须**以 v7b 收尾**（正常跑完时生产就已经是 v7b，不用额外恢复）；
②默认扫描的每个版本都必须真的有 LoRA 资产（不然跑到一半才炸）。
"""
import unittest

from tools import persona_version_sweep as sw
from tools.llama_lora_up import resolve_lora


class SweepInvariantTest(unittest.TestCase):
    def test_lora_file_mapping(self):
        self.assertEqual(sw.lora_file("v7b"), "yuanheng-v7b-lora.gguf")
        self.assertEqual(sw.lora_file("v6"), "yuanheng-v6-lora.gguf")

    def test_default_scan_ends_on_production(self):
        """不变式①：最后一个版本必须是生产版，否则正常跑完还得靠恢复兜底。"""
        self.assertEqual(sw.DEFAULT_VERSIONS[-1], sw.PRODUCTION_LORA)

    def test_production_is_in_default_scan(self):
        """生产版必须被扫到，否则表里没有基线行。"""
        self.assertIn(sw.PRODUCTION_LORA, sw.DEFAULT_VERSIONS)

    def test_every_default_version_has_asset(self):
        """不变式②：默认扫描的每个版本都必须存在 LoRA 文件。"""
        for v in sw.DEFAULT_VERSIONS:
            self.assertTrue(resolve_lora(v).is_file(), v)

    def test_no_duplicate_versions(self):
        self.assertEqual(len(sw.DEFAULT_VERSIONS),
                         len(set(sw.DEFAULT_VERSIONS)))


if __name__ == "__main__":
    unittest.main()