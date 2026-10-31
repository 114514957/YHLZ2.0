"""Account-level QQ consumer lock (P2, guide 13.3).

One Windows named mutex per bot UIN (``Local\\YHLZ_QQ_<uin>``) shared by any
bridge build (Full or Lite) so two consumers can never own the same account.
Fail closed: on conflict the caller must not start. The OS releases the mutex
when the owning process dies. Non-Windows falls back to an exclusive pid file.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import time

ERROR_ALREADY_EXISTS = 183
MUTEX_PREFIX = "Local\\YHLZ_QQ_"


class AccountLock:
    def __init__(self, uin: str) -> None:
        self.uin = str(uin)
        self.name = MUTEX_PREFIX + self.uin
        self._handle = None
        self._fallback_path: pathlib.Path | None = None
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> bool:
        if self._acquired:
            return True
        if os.name == "nt":
            return self._acquire_windows()
        return self._acquire_fallback()

    def _acquire_windows(self) -> bool:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.CreateMutexW(None, True, self.name)
        if not handle:
            return False
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        self._acquired = True
        return True

    def _acquire_fallback(self) -> bool:
        path = pathlib.Path(tempfile.gettempdir()) / f"yhlz_qq_{self.uin}.lock"
        for _ in range(2):
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    pid = int(path.read_text(encoding="utf-8").strip() or "0")
                except Exception:
                    pid = 0
                alive = False
                if pid > 0:
                    try:
                        os.kill(pid, 0)  # p0-audit-allow: POSIX-only fallback
                        alive = True
                    except OSError:
                        alive = False
                if alive:
                    return False
                path.unlink(missing_ok=True)
                continue
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            self._fallback_path = path
            self._acquired = True
            return True
        return False

    def release(self) -> None:
        if not self._acquired:
            return
        if os.name == "nt" and self._handle:
            import ctypes

            ctypes.windll.kernel32.ReleaseMutex(self._handle)  # type: ignore[attr-defined]
            ctypes.windll.kernel32.CloseHandle(self._handle)  # type: ignore[attr-defined]
            self._handle = None
        if self._fallback_path is not None:
            self._fallback_path.unlink(missing_ok=True)
            self._fallback_path = None
        self._acquired = False


def account_name(uin: str) -> str:
    return MUTEX_PREFIX + str(uin)


def lock_info(uin: str) -> dict:
    return {"name": account_name(uin), "backend": "win_mutex" if os.name == "nt"
            else "pid_file", "acquired_at": time.time()}
