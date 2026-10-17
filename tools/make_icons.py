"""从原图生成元亨的方形多尺寸图标（ledger 0828）。

问题（2026-10-17）：`assets/webui/favicon.png` 是 **234×256 非正方形**，
`assets/icons/yhlz-app{,2}.ico` 里 6 个尺寸也全是压扁的（15×16 / 22×24 / 29×32 /
44×48 / 58×64 / 117×128）——托盘、桌面快捷方式、浏览器标签一缩放就糊。

做法：**取正方形人脸特写**（横向满幅、纵向从顶部起，正好框住脸），
再生成标准方形多尺寸 ICO（16…256）与方形 favicon。可重复执行：
源图一旦是方形，裁剪就是 no-op。

用法：
    python tools/make_icons.py                          # 默认源/输出
    python tools/make_icons.py --source path/to/x.png   # 换源
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import time

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "assets" / "webui" / "favicon.png"
ICONS_DIR = ROOT / "assets" / "icons"
FAVICON = ROOT / "assets" / "webui" / "favicon.png"
FAVICON_SMALL = ROOT / "assets" / "webui" / "favicon-32.png"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def square_crop(img: Image.Image, *, face_top_ratio: float = 0.02) -> Image.Image:
    """取正方形：横向满幅、纵向从顶部起（框住脸部），不拉伸。"""
    w, h = img.size
    if w == h:
        return img
    side = min(w, h)
    top = int(round(max(0.0, min(1.0, face_top_ratio)) * h))
    top = min(top, h - side)
    return img.crop((0, top, side, top + side))


def build(source: pathlib.Path, *, out_icons: pathlib.Path = ICONS_DIR,
          out_favicon: pathlib.Path = FAVICON) -> dict:
    src = Image.open(source).convert("RGBA")
    sq = square_crop(src)
    base = sq.resize((256, 256), Image.LANCZOS)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = out_icons / f"_backup_{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    report: dict = {"source": str(source), "source_size": src.size,
                    "square_source": sq.size, "sizes": list(ICO_SIZES),
                    "files": [], "backups": []}

    for name in ("yhlz-app.ico", "yhlz-app2.ico"):
        target = out_icons / name
        if target.exists():
            bak = backup / name
            shutil.copy2(target, bak)
            report["backups"].append(str(bak))
        base.save(target, format="ICO",
                  sizes=[(s, s) for s in ICO_SIZES])
        report["files"].append({"path": str(target),
                                "bytes": target.stat().st_size})

    for target in (out_favicon, FAVICON_SMALL):
        if target.exists():
            bak = backup / target.name
            shutil.copy2(target, bak)
            report["backups"].append(str(bak))
    base.save(out_favicon, format="PNG")
    base.resize((32, 32), Image.LANCZOS).save(FAVICON_SMALL, format="PNG")
    report["files"].append({"path": str(out_favicon),
                            "bytes": out_favicon.stat().st_size})
    report["files"].append({"path": str(FAVICON_SMALL),
                            "bytes": FAVICON_SMALL.stat().st_size})
    return report


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="生成元亨方形多尺寸图标")
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    args = ap.parse_args()
    rep = build(pathlib.Path(args.source))
    print(f"源: {rep['source']} {rep['source_size']} → 方形 {rep['square_source']}")
    print(f"尺寸: {rep['sizes']}")
    for f in rep["files"]:
        print(f"  写出 {f['path']} ({f['bytes']} bytes)")
    for b in rep["backups"]:
        print(f"  备份 {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
