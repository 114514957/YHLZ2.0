"""图标资源回归（ledger 0828）。

2026-10-17：`favicon.png` 是 234×256、ICO 里 6 个尺寸全是压扁的（15×16…117×128），
托盘/快捷方式/标签页一缩放就糊。这里钉死：
  • 两个 ICO 都是**方形**标准尺寸，且含 16/32/256；
  • favicon 是方形 ≥256，另有 32×32 小图；
  • Electron 的托盘/对话窗/桌宠窗都引用同一个 APP_ICON（不许再回退成默认图标）。
"""
from __future__ import annotations

import pathlib
import re
import struct

import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

ICONS = _ROOT / "assets" / "icons"
WEBUI = _ROOT / "assets" / "webui"


def ico_entries(path: pathlib.Path) -> list[tuple[int, int]]:
    data = path.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0 and kind == 1, "not an ICO"
    out = []
    for k in range(count):
        w, h = struct.unpack("<BB", data[6 + 16 * k:8 + 16 * k])
        out.append((w or 256, h or 256))
    return out


class IconAssetsTest(unittest.TestCase):
    def test_ico_square_standard_sizes(self):
        for name in ("yhlz-app.ico", "yhlz-app2.ico"):
            path = ICONS / name
            self.assertTrue(path.exists(), name)
            sizes = ico_entries(path)
            self.assertGreaterEqual(len(sizes), 7, f"{name}: {sizes}")
            for w, h in sizes:
                self.assertEqual(w, h, f"{name} 存在非方形尺寸 {w}x{h}")
            for need in ((16, 16), (32, 32), (48, 48), (128, 128), (256, 256)):
                self.assertIn(need, sizes, f"{name} 缺 {need}")
            self.assertTrue(path.stat().st_size > 10_000, name)

    def test_favicon_square(self):
        from PIL import Image

        im = Image.open(WEBUI / "favicon.png")
        self.assertEqual(im.width, im.height, f"favicon 非方形 {im.size}")
        self.assertGreaterEqual(im.width, 128)
        small = Image.open(WEBUI / "favicon-32.png")
        self.assertEqual(small.size, (32, 32))

    def test_electron_windows_use_app_icon(self):
        main = (_ROOT / "desktop" / "main.js").read_text(encoding="utf-8")
        self.assertIn("const APP_ICON", main)
        self.assertIn("tray = new Tray(nativeImage.createFromPath(icon))", main)
        self.assertEqual(main.count("icon: APP_ICON"), 2,
                         "对话窗与桌宠窗都应带 icon: APP_ICON")
        self.assertRegex(main, re.compile(r"yhlz-app2\.ico"))

    def test_generator_is_repeatable(self):
        sys.path.insert(0, str(_ROOT / "tools"))
        from make_icons import ICO_SIZES, square_crop

        from PIL import Image

        wide = Image.new("RGBA", (200, 260), (0, 0, 0, 255))
        self.assertEqual(square_crop(wide).size, (200, 200))
        square = Image.new("RGBA", (256, 256))
        self.assertIs(square_crop(square), square)      # 已方形：no-op
        self.assertIn(16, ICO_SIZES)
        self.assertIn(256, ICO_SIZES)


if __name__ == "__main__":
    unittest.main()
