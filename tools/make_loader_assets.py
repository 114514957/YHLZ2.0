"""Build web loader assets from the desktop 图片素材 folder (ledger 0223).

1) 加载动画.mp4 (720x1280, white-ish bg) -> chroma-key transparent ->
   loading.webm (vp9 alpha, loop, silent) under assets/webui/.
2) 图标1.jpg -> background flood-removed -> favicon png + app .ico.
QC: sampled alpha ratio sanity (foreground kept between 12-75%).

Usage: python tools/make_loader_assets.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

SRC = Path(r"C:\Users\ACE_WAN——PROJECT\Desktop\图片素材")


def _ff() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def build_webm() -> bool:
    """Decode 加载动画.mp4 frames, chroma-key the near-white background to
    transparent in numpy, and assemble an animated WebP loop (browser keeps
    alpha; this ffmpeg build cannot write alpha webm)."""
    import subprocess

    import numpy as np
    from PIL import Image

    import imageio_ffmpeg

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    src = SRC / "加载动画.mp4"
    fps = 12
    seconds = 4.0
    frames_n = int(fps * seconds)
    cmd = [ff, "-ss", "0.4", "-i", str(src), "-t", str(seconds),
           "-vf", f"fps={fps},format=rgba", "-f", "rawvideo",
           "-pix_fmt", "rgba", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print("decode fail:", r.stderr.decode("utf-8", "replace")[-160:])
        return False
    w, h = 720, 1280
    raw = np.frombuffer(r.stdout, dtype=np.uint8).reshape(-1, w, h, 4)
    frames: list[Image.Image] = []
    bg = np.array([226, 226, 228], dtype=np.int16)
    for f in raw[:frames_n]:
        frgba = f.copy()
        rgb = frgba[:, :, :3].astype(np.int16)
        d = np.abs(rgb - bg).sum(axis=2)
        frgba[d < 70, 3] = 0  # near-background -> transparent
        frames.append(Image.fromarray(frgba, "RGBA"))
    if not frames:
        print("no frames")
        return False
    out = _ROOT / "assets" / "webui" / "loading.webp"
    frames[0].save(out, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=1000 // fps,
                   loop=0, lossless=False, quality=82, method=6)
    alpha_mean = float(np.mean(
        [np.asarray(im)[:, :, 3] > 60 for im in frames]) * 100)
    print(f"loading.webp OK  frames={len(frames)} opaque_ratio={alpha_mean:.1f}%")
    return 15 <= alpha_mean <= 80


def build_icon() -> bool:
    from PIL import Image

    src = SRC / "图标1.jpg"
    im = Image.open(src).convert("RGB")
    w, h = im.size
    px = im.load()
    # flood-fill from all border pixels removing near-white background
    from collections import deque

    seen = bytearray(w * h)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            q.append((x, y))
    th = 232
    while q:
        x, y = q.popleft()
        if x < 0 or y < 0 or x >= w or y >= h or seen[y * w + x]:
            continue
        r, g, b = px[x, y]
        if r >= th and g >= th and b >= th:
            seen[y * w + x] = 1
            q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    rgba = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    drgba = rgba.load()
    from PIL import Image as I

    alphas = I.eval(im.convert("L"), lambda v: v)
    for y in range(h):
        for x in range(w):
            if not seen[y * w + x]:
                drgba[x, y] = (*px[x, y], 255)
    # trim to content bounding box
    bbox = rgba.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
    fav = _ROOT / "assets" / "webui" / "favicon.png"
    rgba.save(fav)
    ico = _ROOT / "assets" / "icons" / "yhlz-app.ico"
    ico.parent.mkdir(parents=True, exist_ok=True)
    base = rgba.copy()
    if base.size[0] > 256:
        base.thumbnail((256, 256))
    base.save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64),
                          (128, 128), (256, 256)])
    print(f"icon ok: favicon.png {fav.stat().st_size}B, {ico} "
          f"{base.size}")
    return True


def main() -> int:
    ok1 = build_webm()
    ok2 = build_icon()
    print("RESULT webm=", ok1, "icon=", ok2)
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
