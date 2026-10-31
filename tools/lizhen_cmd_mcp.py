"""Job-scoped normal CMD MCP for Lizhen. No PowerShell and no elevation."""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys

from mcp.server.fastmcp import FastMCP
mcp = FastMCP("cmd")
WORKSPACE = Path.cwd()


def _kill_tree(proc):
    if proc.poll() is not None: return
    subprocess.run([os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
                    "/d", "/c", "taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),timeout=10)
    if proc.poll() is None:proc.kill()
    proc.wait(timeout=5)


class _CommandJob:
    """The OS kills this command tree even if the MCP server is terminated."""
    def __init__(self, proc):
        class Basic(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),
                      ('flags',wintypes.DWORD),('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),
                      ('active',wintypes.DWORD),('affinity',ctypes.c_size_t),
                      ('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),
                      ('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype=wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        self.handle=self.kernel.CreateJobObjectW(None,None)
        info=Extended();info.basic.flags=0x2000
        if (not self.handle or not self.kernel.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info))
                or not self.kernel.AssignProcessToJobObject(self.handle,wintypes.HANDLE(int(proc._handle)))):
            self.close();_kill_tree(proc)
            raise RuntimeError('无法建立命令进程清理约束')
    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle);self.handle=None


def _decode(buf: bytes) -> str:
    """Decode legacy console output: cmd.exe writes the ANSI codepage to pipes
    even after `chcp 65001` (chcp only affects console handles), so a UTF-8 path
    such as ACE_WAN——PROJECT arrives as GBK bytes. Try UTF-8, then GB18030, and
    only then fall back to replacement characters."""
    for enc in ('utf-8', 'gb18030'):
        try:
            return buf.decode(enc)
        except UnicodeDecodeError:
            continue
    return buf.decode('utf-8', 'replace')


def execute_command(command: str, timeout_seconds: int = 60, relative_dir: str = ".") -> dict:
    if os.name != "nt": raise RuntimeError("此工具仅提供 Windows 普通 CMD")
    if ctypes.windll.shell32.IsUserAnAdmin():
        raise PermissionError("拒绝管理员令牌；请从普通 CMD 启动")
    if not command.strip():raise ValueError("command 不能为空")
    if re.search(r"(?i)(?<![a-z0-9_])(?:runas|powershell|pwsh)(?:\.exe)?(?![a-z0-9_])",command):
        raise PermissionError("只能使用普通 CMD，禁止提权与 PowerShell")
    root=WORKSPACE.resolve();cwd=(root/relative_dir).resolve()
    if cwd != root and root not in cwd.parents:
        raise PermissionError("工作目录必须位于当前任务工作区")
    timeout=max(1,min(int(timeout_seconds),120))
    comspec=os.environ.get("COMSPEC",r"C:\Windows\System32\cmd.exe")
    env=dict(os.environ);env['PYTHONIOENCODING']='utf-8'
    proc=subprocess.Popen(f'"{comspec}" /d /s /c "chcp 65001 >nul & {command}"',
                          executable=comspec,cwd=str(cwd),env=env,
                          stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)
    job=_CommandJob(proc)
    try:
        out,err=proc.communicate(timeout=timeout)
        timed_out=False
    except subprocess.TimeoutExpired:
        _kill_tree(proc);out,err=proc.communicate(timeout=5);timed_out=True
    finally:
        if proc.poll() is None:_kill_tree(proc)
        job.close()
    return {'exit_code':proc.returncode,'stdout':_decode(out)[:20000],
            'stderr':_decode(err)[:10000],'timed_out':timed_out,
            'shell':'cmd.exe','elevated':False}


@mcp.tool()
def execute(command: str, timeout_seconds: int = 60, relative_dir: str = ".") -> str:
    """Execute a command directly in ordinary non-admin Windows CMD in this job workspace.
    Use this tool for every shell command; never use the default PowerShell tool.
    Do not run commands that change files outside the authorized workspace.
    """
    return json.dumps(execute_command(command,timeout_seconds,relative_dir),ensure_ascii=False)


def _log_to_file(name: str) -> None:
    """stdio 传输下 stdout 只承载 JSON-RPC，stderr 会被宿主当成故障输出。

    FastMCP 的 configure_logging 会挂 RichHandler(console=stderr) 并调
    logging.basicConfig；而 basicConfig 在 root 已有 handler 时是空操作，
    所以提前给 root 装好文件 handler，日志就不会再进 stderr。
    """
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / name, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',required=True)
    args=parser.parse_args();WORKSPACE=Path(args.workspace).resolve()
    if not WORKSPACE.is_dir():raise SystemExit('workspace does not exist')
    _log_to_file(f'lizhen_cmd_mcp-{WORKSPACE.name}.log')
    mcp.run(transport='stdio')
