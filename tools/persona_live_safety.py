"""Fail-closed, process-local safety rails for persona model evaluation.

This is not an OS security boundary. Run in a dedicated Python process, never
embed it in the serving daemon. No process launch, lifecycle changes or audio.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PureWindowsPath
import sys
from urllib.parse import urlsplit


def local_endpoint(url: str) -> dict:
    """Only a literal loopback HTTP endpoint; no DNS, credentials or redirects."""
    try:
        u = urlsplit(url)
        host = str(u.hostname or '')
        if (u.scheme != 'http' or u.username is not None or u.password is not None
                or u.query or u.fragment or u.path != '/v1/chat/completions'
                or not ipaddress.ip_address(host).is_loopback):
            raise ValueError('unsupported endpoint')
        port = u.port or 80
    except (ValueError, TypeError) as exc:
        raise RuntimeError('评测地址必须是无认证信息的字面量回环 HTTP /v1/chat/completions') from exc
    return {'host': host, 'port': port, 'root': f'http://{u.netloc}', 'base_url': url}


def _arg(argv, *flags):
    values = []
    for i, value in enumerate(argv):
        for flag in flags:
            if value == flag and i + 1 < len(argv):
                values.append(argv[i + 1])
            elif value.startswith(flag + '='):
                values.append(value.split('=', 1)[1])
    return values


def endpoint_process_evidence(url: str, *, connections=None, process_factory=None) -> dict:
    """Correlate listening address -> unique PID -> startup argv (not global first PID).

    Startup adapter declaration is NOT proof of dynamic adapter state. Unknown,
    inaccessible and ambiguous processes fail closed; no raw argv is retained.
    """
    spec = local_endpoint(url)
    if connections is None or process_factory is None:
        import psutil
        if connections is None:
            connections = psutil.net_connections(kind='tcp')
        if process_factory is None:
            process_factory = psutil.Process
    pids = set()
    for conn in connections:
        if str(conn.status).upper() != 'LISTEN' or not conn.laddr:
            continue
        ip, port = conn.laddr[:2]
        # Conservative IPv4/IPv6 matching: don't infer dual-stack coverage.
        wildcard = '::' if ':' in spec['host'] else '0.0.0.0'
        if int(port) == spec['port'] and ip in (spec['host'], wildcard):
            if conn.pid is None:
                raise RuntimeError('监听进程 PID 不可读；不作模型归因')
            pids.add(int(conn.pid))
    if len(pids) != 1:
        raise RuntimeError('评测端口没有唯一可归因的监听进程')
    try:
        proc = process_factory(next(iter(pids)))
        argv = [str(x) for x in proc.cmdline()]
        if not argv or PureWindowsPath(argv[0]).name.lower() not in ('llama-server', 'llama-server.exe'):
            raise RuntimeError('评测端口不是可验证的 llama-server')
        loras = _arg(argv, '--lora')
        scaled_loras = _arg(argv, '--lora-scaled')
        # Multi-adapter or scaled configurations need API-level inspection.
        if len(loras) != 1 or scaled_loras:
            raise RuntimeError('需要唯一 --lora 启动声明；多适配器/缩放配置尚不支持归因')
        models = _arg(argv, '-m', '--model')
        return {
            'pid': proc.pid, 'create_time': proc.create_time(),
            'listen_host': spec['host'], 'listen_port': spec['port'],
            'argv_sha256': hashlib.sha256(json.dumps(argv).encode()).hexdigest(),
            'lora': PureWindowsPath(loras[0]).name,
            'model_file': PureWindowsPath(models[0]).name if len(models) == 1 else '',
            'identity_scope': 'endpoint_bound_startup_declaration',
            'loaded_adapter_verified': False,
        }
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError('无法读取评测端口进程身份') from exc


class EvaluationGuard:
    """Audit Python I/O. Every denied attempt invalidates the run even if swallowed.

    Trusted runtime/package roots are supplied explicitly; project data is not
    implicitly readable. Code-root exceptions only allow Python source/bytecode.
    No arbitrary fd access, network outside the model address, child process,
    dynamically loaded model library, symlink, or filesystem mutation outside tmp.
    """
    def __init__(self, sandbox, endpoint, *, code_roots=(), runtime_roots=(), read_files=()):
        self.sandbox = Path(sandbox).resolve()
        self.endpoint = local_endpoint(endpoint)
        self.code_roots = tuple(Path(p).resolve() for p in code_roots)
        self.runtime_roots = tuple(Path(p).resolve() for p in runtime_roots)
        self.read_files = frozenset(Path(p).resolve() for p in read_files)
        self.violations = []
        self.active = False
        self._installed = False

    def install(self):
        if not self._installed:
            sys.addaudithook(self.check)
            self._installed = True
        self.active = True

    def _deny(self, event):
        self.violations.append(event)  # no private path/args in the report
        raise PermissionError('persona evaluation guard: ' + event)

    def _path(self, value, *, write=False, listing=False):
        if isinstance(value, int):
            return False
        try:
            p = Path(os.fsdecode(value)).resolve()
        except (TypeError, ValueError, OSError):
            return False
        if p.is_relative_to(self.sandbox):
            return True
        if write:
            return False
        if p in self.read_files and not listing:
            return True
        if any(p.is_relative_to(root) for root in self.runtime_roots):
            return True
        return any(p.is_relative_to(root) for root in self.code_roots) and (
            listing or p.suffix.lower() in {'.py', '.pyc'})

    def check(self, event, args):
        if not self.active:
            return
        paths, write, listing = [], False, False
        if event == 'open':
            p, mode, flags = args
            write = bool(isinstance(mode, str) and any(c in mode for c in 'wax+')) or bool(
                flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            paths = [p]
        elif event == 'sqlite3.connect':
            if str(args[0]) == ':memory:':
                return
            # URI filenames intentionally fail unless explicitly ordinary sandbox paths.
            paths, write = [args[0]], True
        elif event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime', 'os.truncate'}:
            paths, write = [args[0]], True
        elif event in {'os.rename', 'os.replace'}:
            paths, write = list(args[:2]), True
        elif event in {'os.listdir', 'os.scandir'}:
            paths, listing = [args[0]], True
        elif event in {'os.link', 'os.symlink', 'subprocess.Popen', 'os.system', 'os.startfile',
                       'os.exec', 'os.posix_spawn', 'socket.bind'}:
            self._deny(event)
        elif event == 'socket.connect':
            address = args[1]
            if not (isinstance(address, tuple) and len(address) >= 2
                    and address[:2] == (self.endpoint['host'], self.endpoint['port'])):
                self._deny(event)
        elif event == 'socket.getaddrinfo':
            if not (args[0] == self.endpoint['host'] and str(args[1]) == str(self.endpoint['port'])):
                self._deny(event)
        elif event == 'import' and str(args[0]).split('.')[0] in {
                'torch', 'transformers', 'sentence_transformers'}:
            self._deny('model_import')
        for path in paths:
            if not self._path(path, write=write, listing=listing):
                self._deny(event + (':write' if write else ':read'))

    def assert_clean(self):
        if self.violations:
            raise RuntimeError('评测隔离触发拒绝，整轮不作验收: ' + ','.join(sorted(set(self.violations))))


async def cancel_evaluation_tasks(initial_tasks):
    """Join newly created tasks BEFORE restoring patched filesystem globals.

    Must run in a dedicated evaluation event loop. A cancellation-resistant task
    is an error, not an excuse to restore globals under a live background writer.
    """
    count = 0
    for _ in range(8):
        tasks = [t for t in asyncio.all_tasks() if t not in initial_tasks
                 and t is not asyncio.current_task() and not t.done()]
        if not tasks:
            return count
        count += len(tasks)
        for task in tasks:
            task.cancel()
        _, pending = await asyncio.wait(tasks, timeout=2.0)
        if pending:
            raise RuntimeError('评测后台任务拒绝取消；禁止恢复生产路径，必须结束专用进程')
    raise RuntimeError('评测后台任务持续派生；禁止恢复生产路径')

class IsolatedRuntime:
    """Patch application data roots; use empty fixtures, never copy private data.

    Core compiled persona constants stay identical. Learned private persona/style
    are intentionally absent and declared in the evidence, not silently replayed.
    """
    def __init__(self, sandbox, endpoint):
        from contextlib import ExitStack
        self.stack = ExitStack()
        self.sandbox = Path(sandbox).resolve()
        self.endpoint = endpoint
        self.guard = None
        self.initial_tasks = set()

    async def __aenter__(self):
        from unittest.mock import patch
        from backend import target_memory as memory, target_kw_index as kw
        from backend import target_entry as entry, entity_graph, intrinsic_drives
        from backend import target_style, target_prompts, target_scheduler_tools as st
        from backend import target_persona_loop as persona, env_loader, communities
        import tempfile
        from types import FunctionType
        import httpx  # preload transport before the audit rail; requests still audited
        import httpcore
        import anyio
        import importlib.util
        # httpcore probes optional sniffio on every request. With no sniffio,
        # Python otherwise scans a changed artifact/script directory mid-run.
        # Cache the known absence only for this worker scope; keep the real
        # transport's documented asyncio fallback, without widening read access.
        sniffio_missing = importlib.util.find_spec('sniffio') is None
        self.initial_tasks = set(asyncio.all_tasks())
        root = self.sandbox
        replacements = [
            (memory, 'DEFAULT_DB', root/'memstore'/'mem.db'),
            (memory, 'GOLDEN_MEMORY', root/'golden'),
            (memory, 'COGNITION_FILE', root/'foundation.md'),
            (kw, 'DEFAULT_DB', root/'kw.db'),
            (entry, 'SESSIONS_DIR', root/'sessions'),
            (entity_graph, 'DB_PATH', root/'entities.db'),
            (communities, 'COMM_FILE', root/'communities.json'),
            (intrinsic_drives, 'DRIVES_FILE', root/'drives.json'),
            (target_style, 'STYLE_COUNTS', root/'style.json'),
            (target_prompts, 'PERSONA_DIMS_FILE', root/'persona_dims.json'),
            (st, '_SKILL_SEEN', root/'skills_seen.json'),
            (st, '_PROJECT_ROOT', root),
            (persona, 'REJECTED_FILE', root/'rejected.json'),
            (env_loader, '_loaded', True),
            (tempfile, 'tempdir', str(root)),
        ]
        try:
            if sniffio_missing:
                self.stack.enter_context(patch.dict(sys.modules, sniffio=None))
            for mod, name, value in replacements:
                self.stack.enter_context(patch.object(mod, name, value))
            if isinstance(kw.KeywordIndex.__init__, FunctionType):
                self.stack.enter_context(patch.object(kw.KeywordIndex.__init__, '__defaults__', (root/'kw.db',)))
            # Defaults captured at definition time must be redirected as well.
            defaults = dict(memory.TargetMemoryService.__init__.__kwdefaults__ or {})
            if 'db_path' in defaults:
                self.stack.enter_context(patch.dict(memory.TargetMemoryService.__init__.__kwdefaults__, db_path=root/'memstore'/'mem.db'))
            self.stack.enter_context(patch.dict(os.environ, {
                'YHLZ_MEMORY_LLM_MODE':'disabled', 'YHLZ_MEMORY_SEMANTIC_MODE':'disabled',
                'YHLZ_TRAINING_ACTIVE':'1', 'YHLZ_FINETUNE_ACTIVE':'1',
                'HTTP_PROXY':'', 'HTTPS_PROXY':'', 'ALL_PROXY':'',
                'http_proxy':'', 'https_proxy':'', 'all_proxy':'',
                'NO_PROXY':'127.0.0.1,::1', 'no_proxy':'127.0.0.1,::1',
            }))
            project = Path(__file__).resolve().parents[1]
            self.guard = EvaluationGuard(root, self.endpoint,
                code_roots=(project/'backend', project/'tools'),
                runtime_roots=(sys.prefix, sys.base_prefix))
            self.guard.install()
        except BaseException:
            self.stack.close()
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # Deliberately don't restore globals on cancellation-resistant tasks.
        # The dedicated worker must exit instead of exposing production paths.
        self.cancelled_tasks = await cancel_evaluation_tasks(self.initial_tasks)
        self.guard.active = False
        self.stack.close()
        self.guard.assert_clean()
        return False

def adapter_api_evidence(url: str, expected: str) -> dict:
    """Read actual active adapter state; no POST, restart or global model switch."""
    import urllib.request
    import math
    spec = local_endpoint(url)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise RuntimeError('禁止适配器 API 重定向')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(spec['root']+'/lora-adapters', timeout=8) as response:
            data = json.loads(response.read(65537))
        if not isinstance(data, list) or len(data) != 1:
            raise RuntimeError('适配器 API 必须只返回一个适配器')
        item = data[0]
        name = PureWindowsPath(str(item['path'])).name
        scale = float(item['scale'])
        if name != expected or not math.isfinite(scale) or scale != 1.0:
            raise RuntimeError('适配器 API 名称/启用权重与预期不一致')
        return {'lora':name, 'scale':scale, 'id':item['id'],
                'api_sha256':hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest(),
                'loaded_adapter_verified':True}
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError('无法验证 /lora-adapters 运行状态') from exc
