"""Reproducible training-safe suite. Denies network, subprocesses and production writes."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import sys
import socket
from urllib.parse import urlsplit
from urllib.request import url2pathname
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.dont_write_bytecode = True
os.environ.update(YHLZ_TRAINING_ACTIVE='1',YHLZ_FINETUNE_ACTIVE='1',PYTHONUTF8='1')
MODULES = [
 'test_memory_carriers','test_memory_summary_scheduler','test_memory_endurance',
 'test_memory_resource_policy','test_memory_channel_lifecycle','test_memory_index_audit',
 'test_memory_health','test_persona_eval_evidence', 'test_persona_live_safety','test_persona_effects','test_text_tool_contract','test_text_memory_inference_gate','test_persona_text_boundary','test_target_dev_bridge','test_qq_security',
 'test_prompt_structure','test_context_compaction','test_target_orchestrator',
 'test_persona_versions','test_memory_recall_budget','test_memory_review',
 'test_target_memory','test_target_entry','test_target_prompts',
 'test_cognition_governance','test_target_persona_loop','test_qq_memory_boundaries',
 'test_qq_connection','test_qq_delivery','test_notify_guard','test_qq_group_features',
 'test_console_text_routes', 'test_memory_review_retry', 'test_turn_evidence',
 'test_scorer_v2',
]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=True)
    sandbox=Path(tempfile.mkdtemp(prefix='yhlz-memory-offline-')).resolve()
    violations=[]
    active=True
    def allowed(path):
        if isinstance(path,int): return True
        try:
            raw=os.fsdecode(path)
            if raw.startswith("file:"):
                raw=url2pathname(urlsplit(raw).path)
            resolved=Path(raw).resolve()
            return resolved.is_relative_to(sandbox) or resolved.is_relative_to(output)
        except (TypeError,ValueError): return False
    def guard(event,values):
        if not active: return
        if event=='socket.connect':
            caller=sys._getframe(1).f_code
            if caller is getattr(socket, '_fallback_socketpair', socket.socketpair).__code__:
                return  # Windows asyncio self-pipe only; not arbitrary loopback access.
        paths=[]
        if event=='open':
            path,mode,flags=values
            if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)):
                paths=[path]
        elif event=='sqlite3.connect':
            path=values[0]
            if str(path) != ':memory:': paths=[path]
        elif event in {'os.remove','os.rmdir','os.mkdir'}: paths=[values[0]]
        elif event in {'os.rename','os.link','os.symlink'}: paths=list(values[:2])
        elif event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'}:
            violations.append(event)
            raise PermissionError('offline guard: '+event)
        elif event=='import' and str(values[0]).split('.')[0] in {'torch','sentence_transformers','transformers'}:
            violations.append('model import:'+str(values[0]))
            raise PermissionError('offline guard: model import')
        for path in paths:
            if not allowed(path):
                violations.append(event+':'+str(path))
                raise PermissionError('offline guard: production write/database open')
    sys.addaudithook(guard)
    with ExitStack() as stack:
        stack.enter_context(patch.object(tempfile,'tempdir',str(sandbox)))
        from backend import target_memory as memory, target_kw_index as kw
        from backend import target_entry as entry, growth_log, entity_graph, intrinsic_drives
        from backend import target_scheduler_tools as tools, target_persona_loop as persona
        from backend import yuanheng_kb as kb, qq_delivery
        from tools import qq_bot
        replacements=[(memory,'DEFAULT_DB',sandbox/'memstore'/'mem.db'),
          (kw,'DEFAULT_DB',sandbox/'kw.db'),(entry,'SESSIONS_DIR',sandbox/'sessions'),
          (growth_log,'GROWTH_FILE',sandbox/'growth.md'),(entity_graph,'DB_PATH',sandbox/'entities.db'),
          (intrinsic_drives,'DRIVES_FILE',sandbox/'drives.json'),
          (tools,'DIARY_FILE',sandbox/'diary.md'),(tools,'TASK_FILE',sandbox/'tasks.md'),
          (tools,'_SKILL_SEEN',sandbox/'skills.json'),
          (persona,'PENDING_FILE',sandbox/'pending.json'),(persona,'REJECTED_FILE',sandbox/'rejected.json'),
          (kb,'DEFAULT_KB_DB',sandbox/'kb.db'),
          (qq_bot,'QQ_STATUS',sandbox/'qq_status.json'),
          (qq_bot,'GROUP_DAILY_STATE',sandbox/'qq_daily.json'),
          (qq_delivery,'DEFAULT_STATUS_PATH',sandbox/'delivery.json')]
        stack.enter_context(patch.dict(qq_delivery.DeliveryManager.__init__.__kwdefaults__,status_path=sandbox/'delivery.json'))
        for mod,name,value in replacements: stack.enter_context(patch.object(mod,name,value))
        stack.enter_context(patch.object(kw.KeywordIndex.__init__,'__defaults__',(sandbox/'kw.db',)))
        suite=unittest.defaultTestLoader.loadTestsFromNames(['backend.'+name for name in MODULES])
        log=io.StringIO(); started=time.perf_counter()
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
        elapsed=time.perf_counter()-started
    active=False
    (output/'regression.log').write_text(log.getvalue(),encoding='utf-8')
    report={'ok':result.wasSuccessful() and not violations,'tests_run':result.testsRun,
      'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
      'duration_s':round(elapsed,3),'modules':MODULES,'guard_violations':violations,
      'sandbox':str(sandbox),'training_markers':True,'real_model_validation':False,
      'production_deployment':False}
    (output/'regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['ok']: print(log.getvalue()[-16000:])
    return 0 if report['ok'] else 1

if __name__=='__main__': raise SystemExit(main())
