"""断点续传下载（Range），用于 hf-mirror 大文件被中途掐断的情况。

用法: python tools/dl_resume.py <url> <dst> [expected_bytes]
"""
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    url, dst = sys.argv[1], sys.argv[2]
    expect = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    pos = os.path.getsize(dst) if os.path.exists(dst) else 0
    if expect and pos >= expect:
        print("already complete: %d" % pos)
        return 0
    t0 = time.time()
    last = pos
    attempts = 0
    while True:
        attempts += 1
        if attempts > 12:
            print("too many attempts @ %d" % pos)
            return 1
        req = urllib.request.Request(url, headers={"Range": "bytes=%d-" % pos})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                total = int(r.headers.get("Content-Length") or 0)
                with open(dst, "ab") as f:
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        f.write(b)
                        pos += len(b)
                        if pos - last >= 100 * (1 << 20):
                            last = pos
                            print("%.0f MB  %.1f MB/s" % (pos / 1e6, pos / 1e6 / (time.time() - t0)),
                                  flush=True)
        except Exception as ex:  # noqa: BLE001
            print("retry after %r @%d" % (type(ex).__name__, pos), flush=True)
            time.sleep(3)
            continue
        if expect and pos < expect:
            print("short (%d/%d), resuming" % (pos, expect), flush=True)
            time.sleep(2)
            continue
        if not expect and total and pos < pos:
            continue
        break
    print("done %d bytes in %.0fs" % (pos, time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
