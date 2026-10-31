"""PID lock + owned-process verification for QQ Bridge profiles (P2).

A lock file stores pid / create_time / profile / workdir / entry /
instance_id. Stale locks (owner gone or PID reused) are replaced; a live
matching owner makes acquire fail closed. Termination helpers refuse to touch
a process whose recorded identity no longer matches.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
import uuid

CREATE_TIME_TOLERANCE = 1.0


class LockError(RuntimeError):
    """Lock held by a live owner, or lock file cannot be obtained."""


def pid_alive(pid: int) -> bool:
    """Liveness check that never signals the process.

    On Windows a ``kill(pid, 0)`` call is CTRL_C_EVENT (0) for the console API
    and can deliver a real Ctrl+C to a shared console group; use psutil /
    OpenProcess instead.
    """
    pid = int(pid or 0)
    if pid <= 0:
        return False
    try:
        import psutil

        return bool(psutil.pid_exists(pid))
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            kernel32.CloseHandle(handle)
            return bool(ok) and code.value == STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)  # p0-audit-allow: POSIX-only fallback, never Windows
        return True
    except OSError:
        return False


def proc_create_time(pid: int) -> float:
    try:
        import psutil

        return float(psutil.Process(int(pid)).create_time())
    except Exception:
        return 0.0


def read_info(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def make_info(profile: str, *, entry: str | None = None, role: str = "bridge") -> dict:
    return {
        "pid": os.getpid(),
        "create_time": proc_create_time(os.getpid()) or time.time(),
        "profile": str(profile),
        "role": str(role),
        "workdir": str(pathlib.Path.cwd()),
        "entry": str(entry or ""),
        "instance_id": uuid.uuid4().hex[:12],
        "started_at": time.time(),
    }


def owner_matches(info: dict, *, entry: str | None = None) -> tuple[bool, str]:
    """Verify recorded owner identity (pid alive + create_time + entry)."""
    pid = int(info.get("pid") or 0)
    if not pid_alive(pid):
        return False, "pid_not_alive"
    recorded = float(info.get("create_time") or 0.0)
    if recorded:
        current = proc_create_time(pid)
        if current and abs(current - recorded) > CREATE_TIME_TOLERANCE:
            return False, "pid_reused"
    recorded_entry = str(info.get("entry") or "")
    if entry and recorded_entry and \
            os.path.normcase(os.path.abspath(recorded_entry)) != \
            os.path.normcase(os.path.abspath(entry)):
        return False, "entry_mismatch"
    return True, "ok"


def acquire_pid_lock(path: pathlib.Path, info: dict) -> dict:
    """Create the lock or fail closed. Returns the info that was written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            old = read_info(path)
            ok, reason = owner_matches(old)
            if ok:
                raise LockError(
                    f"已被 pid={old.get('pid')} role={old.get('role')} "
                    f"profile={old.get('profile')} 持有")
            if attempt == 1:
                raise LockError(f"锁文件无法取得: {path} ({reason})")
            path.unlink(missing_ok=True)
            continue
        os.write(fd, json.dumps(info, ensure_ascii=False).encode("utf-8"))
        os.close(fd)
        return info
    raise LockError(f"锁文件无法取得: {path}")


def release_pid_lock(path: pathlib.Path, info: dict) -> None:
    current = read_info(path)
    if current.get("instance_id") and info.get("instance_id") and \
            current.get("instance_id") != info.get("instance_id"):
        return
    path.unlink(missing_ok=True)


def terminate_owned(info: dict, *, entry: str | None = None,
                    timeout: float = 5.0) -> tuple[bool, str]:
    """Terminate only if the recorded identity still matches; else refuse."""
    pid = int(info.get("pid") or 0)
    ok, reason = owner_matches(info, entry=entry)
    if not ok:
        return False, reason
    try:
        import psutil

        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=max(0.5, float(timeout)))
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=max(0.5, float(timeout)))
        return True, "terminated"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}"
