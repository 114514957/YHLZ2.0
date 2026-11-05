"""用 curl 分块下载（本机代理挂了，直连只在大文件上超时，Range 可用）。

每块 40MB，curl --noproxy 直连，失败重试；写进同一文件，按现有大小续。
用法: python tools/dl_chunks.py <url> <dst> <total_bytes>
"""
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CHUNK = 40 << 20
CURL = r"C:\Windows\System32\curl.exe"


def main() -> int:
    url, dst, total = sys.argv[1], sys.argv[2], int(sys.argv[3])
    tmp = dst + ".chunk"
    t0 = time.time()
    fails = 0
    while True:
        pos = os.path.getsize(dst) if os.path.exists(dst) else 0
        if pos >= total:
            break
        hi = min(pos + CHUNK, total) - 1
        r = subprocess.run(
            [CURL, "-sSL", "--noproxy", "*", "--http1.1",
             "-r", "%d-%d" % (pos, hi), "-m", "600", "-o", tmp, url],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        got = os.path.getsize(tmp) if os.path.exists(tmp) else 0
        if r.returncode != 0 or got == 0:
            fails += 1
            print("chunk @%d failed rc=%s got=%d (%d/12)"
                  % (pos, r.returncode, got, fails), flush=True)
            if fails >= 12:
                return 1
            time.sleep(5)
            continue
        with open(tmp, "rb") as f, open(dst, "ab") as o:
            while True:
                b = f.read(1 << 20)
                if not b:
                    break
                o.write(b)
        os.remove(tmp)
        pos = os.path.getsize(dst)
        print("%.0f/%.0f MB  %.1f MB/s"
              % (pos / 1e6, total / 1e6, pos / 1e6 / (time.time() - t0)), flush=True)
    print("done %d bytes" % os.path.getsize(dst))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
