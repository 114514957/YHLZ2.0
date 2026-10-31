"""Opt-in existing-model text route diagnostic. No server bind or production runtime."""
from __future__ import annotations
import argparse
import asyncio
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

async def run(output):
    from tools.persona_regression import preflight, _sandbox_writes, _restore_writes, LIVE_SAFE_TOOLS
    from tools.persona_live_safety import IsolatedRuntime, endpoint_process_evidence, adapter_api_evidence
    from tools.persona_eval_evidence import build_manifest, new_run_id, write_new_json, constrained_policy
    from tools.persona_effect_evidence import FixtureEffects
    from backend.console_server import ConsoleHandler
    from backend.target_daemon import DaemonRuntime
    from backend.target_entry import ConversationSession
    from backend.target_memory import TargetMemoryService
    from backend.target_kw_index import KeywordIndex
    from backend.target_orchestrator import build_openai_compatible_llm_turn
    url='http://127.0.0.1:8081/v1/chat/completions'
    before=endpoint_process_evidence(url)
    adapter=adapter_api_evidence(url,'yuanheng-v8-lora.gguf')
    preflight(url)
    root=Path(tempfile.mkdtemp(prefix='yhlz_console_probe_')).resolve()
    sandbox=IsolatedRuntime(root,url)
    saved=_sandbox_writes(root)
    result={'diagnostic_only':True,'acceptance':False,'production_deployment':False,
            'browser_interaction':False,'http_socket':False,'sandbox':str(root),
            'endpoint_before':before,'adapter_before':adapter,'turns':[],'inference_calls':0,
            'disabled_lifecycle':['daemon_constructor','due_plan_dispatch','persona_consolidation']}
    questions=['用一句话介绍你自己。',
               '把以下知识存入知识库：路由夹具中的青鸟编号为四十二号。',
               '查询知识库：路由夹具中的青鸟编号是什么？']
    manifest=build_manifest(ROOT,[{'id':str(i),'q':q} for i,q in enumerate(questions)],
                            run_id=new_run_id(),mode='console_text_route_diagnostic')
    try:
        async with sandbox:
            memory=TargetMemoryService(db_path=root/'memory.db',kw_index=KeywordIndex(root/'kw.db'),l1_scope='console')
            allowed_task=None
            class Observed:
                def __init__(self,provider):self.provider=provider
                async def __call__(self,messages,schemas):
                    if asyncio.current_task() is not allowed_task:
                        sandbox.guard.violations.append('background_inference')
                        raise RuntimeError('background inference forbidden')
                    result['inference_calls']+=1
                    return await self.provider(messages,schemas)
                def with_stream(self,**kwargs):return Observed(self.provider.with_stream(**kwargs))
            provider=build_openai_compatible_llm_turn(base_url=url,api_key='',model='gemma-4-e4b',
                temperature=0.2,max_tokens=800,reasoning_effort='none',fallback_base_url=None,fallback_model=None)
            async def approve(info):return True
            session=ConversationSession(memory=memory,llm_turn=Observed(provider),approver=approve,channel='console')
            session.style_inject=False
            session._tool_policy=constrained_policy(session._tool_policy,LIVE_SAFE_TOOLS,mode='production',observations=[])
            effects=FixtureEffects(root,memory);effects.bind(session.registry)
            raw_turn=session.run_turn
            async def authorized_turn(*args,**kwargs):
                nonlocal allowed_task
                allowed_task=asyncio.current_task()
                try:return await raw_turn(*args,**kwargs)
                finally:allowed_task=None
            session.run_turn=authorized_turn
            runtime=object.__new__(DaemonRuntime)
            runtime._loop=asyncio.get_running_loop()
            runtime._session=lambda channel:session
            runtime._maybe_consolidate=lambda channel:None
            runtime._run_due_plans=lambda:None
            def handler(path,body=b''):
                h=object.__new__(ConsoleHandler);h.runtime=runtime;h.path=path
                h.headers={'Content-Length':str(len(body))};h.rfile=io.BytesIO(body);h.wfile=io.BytesIO()
                h.send_response=Mock();h.send_header=Mock();h.end_headers=Mock()
                return h
            for q in questions:
                h=handler('/talk',json.dumps({'text':q}).encode())
                started=time.perf_counter()
                await asyncio.to_thread(h.console_do_POST)
                frames=[json.loads(line[6:]) for line in h.wfile.getvalue().decode().splitlines() if line.startswith('data: ')]
                done=[f for f in frames if f['type']=='turn_done']
                if len(done)!=1 or any(f['type']=='error' for f in frames):raise RuntimeError('route did not complete: '+str(frames))
                deltas=[f['delta'] for f in frames if f['type']=='delta']
                result['turns'].append({'question':q,'frames':frames,'answer':done[0]['text'],
                    'delta_count':len(deltas),'delta_matches_done':''.join(deltas)==done[0]['text'],
                    'duration_s':round(time.perf_counter()-started,3)})
            h=handler('/history');h.console_do_GET()
            result['history']=json.loads(h.wfile.getvalue())
            archive=json.loads((root/'sessions'/'console.json').read_text(encoding='utf-8'))
            result['archive_exists']=True
            result['archive_last_answer_present']='四十二号' in json.dumps(archive,ensure_ascii=False)
            result['kb_readback']=effects.check_requested_content('kb.add','路由夹具中的青鸟编号为四十二号。')
            result['effect_receipts']=effects.receipts
            result['retrieved_anchor']='四十二号' in result['turns'][-1]['answer']
        result['guard_violations']=sandbox.guard.violations
        result['endpoint_after']=endpoint_process_evidence(url)
        result['adapter_after']=adapter_api_evidence(url,'yuanheng-v8-lora.gguf')
        result['identity_unchanged']=before==result['endpoint_after'] and adapter==result['adapter_after']
        result['ok']=all(t['delta_matches_done'] for t in result['turns']) and result['kb_readback']['matches']==1 and result['retrieved_anchor'] and result['identity_unchanged'] and not result['guard_violations']
    finally:_restore_writes(saved)
    write_new_json(output/'manifest.json',manifest)
    write_new_json(output/'result.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['ok'] else 1

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-local',action='store_true');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.run_local:parser.error('requires explicit --run-local')
    if any(os.getenv(k,'').lower() in {'1','true','yes','on'} for k in ('YHLZ_TRAINING_ACTIVE','YHLZ_FINETUNE_ACTIVE')):
        parser.error('inherited training-active marker: diagnostic refused')
    args.output.mkdir(parents=True,exist_ok=False)
    return asyncio.run(run(args.output.resolve()))

if __name__=='__main__':raise SystemExit(main())
