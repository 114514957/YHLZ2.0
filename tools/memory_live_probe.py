"""Explicit local memory diagnostic using synthetic data in a guarded worker.

Not production acceptance: disables implicit work, verifies endpoint/adapter,
then permits only the explicitly invoked memory hooks to use the existing model.
"""
from __future__ import annotations
import argparse, asyncio, hashlib, json, os, sqlite3, tempfile, time
from pathlib import Path
from tools.persona_eval_evidence import build_manifest, new_run_id, write_new_json
from tools.persona_live_safety import IsolatedRuntime, endpoint_process_evidence, adapter_api_evidence
from tools.persona_regression import _sandbox_writes, _restore_writes

async def probe(args):
    from backend.memory_resource_policy import load_memory_resource_policy, MemoryResourcePolicy
    if load_memory_resource_policy().reason == 'training-active':
        raise RuntimeError('inherited training marker: memory diagnostic refused')
    out=Path(args.output).resolve(); out.mkdir(parents=True, exist_ok=False)
    endpoint='http://127.0.0.1:8081/v1/chat/completions'
    identity=endpoint_process_evidence(endpoint)
    if identity['lora'] != 'yuanheng-v8-lora.gguf': raise RuntimeError('unexpected adapter')
    adapter=adapter_api_evidence(endpoint,identity['lora'])
    root=Path(__file__).resolve().parents[1]
    write_new_json(out/'manifest.json',build_manifest(root,[],run_id=new_run_id(),mode='memory_live_diagnostic'))
    data=Path(tempfile.mkdtemp(prefix='yhlz_memory_probe_'))
    saved=_sandbox_writes(data); runtime=IsolatedRuntime(data,endpoint)
    report={'diagnostic_only':True,'acceptance':False,'production_deployment':False,
            'endpoint_before':identity,'adapter_before':adapter,'sandbox':str(data),
            'calls':[],'steps':{},'implicit_background_enabled':False}
    try:
        async with runtime:
            from backend.llm_vllm_provider import LlmVllmProvider
            from backend.target_memory_llm import MemoryLLMService
            from backend.target_memory import TargetMemoryService
            from backend.target_kw_index import KeywordIndex
            provider=LlmVllmProvider(base_url=endpoint.rsplit('/v1/chat/completions',1)[0],
                model='gemma-4-e4b',request_timeout_s=60)
            owner_task=asyncio.current_task()
            phase=''
            class Observed:
                async def stream_chat(self,messages,**kwargs):
                    if asyncio.current_task() is not owner_task:
                        raise RuntimeError('unexpected implicit inference')
                    record={'phase':phase,'max_tokens':kwargs.get('max_tokens'),
                            'input_sha256':hashlib.sha256(json.dumps(messages,ensure_ascii=False).encode()).hexdigest(),
                            'output':'','error':''}
                    report['calls'].append(record); started=time.perf_counter()
                    try:
                        async for delta in provider.stream_chat(messages,**kwargs):
                            record['output']+=delta; yield delta
                    except Exception as e:
                        record['error']=type(e).__name__; raise
                    finally: record['duration_s']=round(time.perf_counter()-started,3)
            observed=Observed()
            # Only these explicit calls bypass the worker's training pause.
            # Serving/environment resource guards remain enabled and unchanged.
            hooks=MemoryLLMService(observed,local=observed,resource_guard=False,max_tokens=512)
            db=data/'fixture.db'; kw=KeywordIndex(data/'fixture_kw.db')
            memory=TargetMemoryService(db_path=db,kw_index=kw,window_turns=2,l1_scope='diagnostic')
            memory.set_resource_policy(MemoryResourcePolicy(mode='local'),semantic_enabled=False)
            memory.set_llm_hooks(hooks,hooks)
            memory._auto_adjudicate=lambda item:None
            memory._auto_link_causal=lambda item:None
            turns=[('user','这是合成验收数据。测试员青禾喜欢银杏茶，不喜欢浓咖啡。'),
                   ('assistant','记住了，青禾偏爱银杏茶。'),
                   ('user','我们约好星期五整理蓝色卡片，这件事还没有完成。'),
                   ('assistant','蓝色卡片整理仍是待办。'),
                   ('user','现在核对记忆流程。'),('assistant','开始核对。')]
            try:
                for role,text in turns:memory.append_turn(role=role,text=text)
                before=memory.health()['summary_backlog']; phase='compress'
                await memory.process_summary()
                after=memory.health()['summary_backlog']
                report['steps']['compression']={'before':before,'after':after,'summary':memory.summary_line(),
                    'error':memory.health().get('summary_error'),'success':before>0 and after==0 and bool(memory.summary_line())}
                phase='candidates'
                items=await memory.submit_candidates(text=turns[0][1],transcript='\n'.join(r+':'+t for r,t in turns),
                    evidence_ref='synthetic:qinghe:1',source='owner_synthetic')
                report['steps']['candidates']={'status':getattr(hooks,'last_candidate_status','unknown'),'count':len(items),'items':[x.to_dict() for x in items]}
                phase='adjudicate'
                verdicts=[]
                for item in items:
                    await memory.adjudicate_async([item])
                    verdicts.append({'id':item.id,'status':getattr(hooks,'last_judge_status','unknown')})
                with sqlite3.connect(db) as con:
                    rows=con.execute('SELECT id,tier,summary,status,evidence_ref,source FROM l2_items').fetchall()
                    fts=con.execute('SELECT sid,summary FROM l2_fts').fetchall()
                restarted=TargetMemoryService(db_path=db,kw_index=KeywordIndex(data/'fixture_kw.db'),
                    window_turns=2,l1_scope='diagnostic')
                restarted.set_resource_policy(MemoryResourcePolicy(mode='disabled'),semantic_enabled=False)
                recalled=restarted.recall('银杏茶',limit=5)
                report['steps']['reopen']={'rows':rows,'fts':fts,'recall':recalled,
                    'summary_restored':restarted.summary_line()==memory.summary_line(),
                    'recall_has_anchor':'银杏茶' in json.dumps(recalled,ensure_ascii=False),
                    'all_l2':bool(rows) and all(r[1]=='L2' for r in rows)}
                report['steps']['adjudication']={'route':hooks.last_judge_route,'verdicts':verdicts,
                    'note':'independent raw outputs must parse; DB success alone does not prove judgment'}
            finally: await provider.close()
        report['guard_violations']=runtime.guard.violations
        report['endpoint_after']=endpoint_process_evidence(endpoint)
        report['adapter_after']=adapter_api_evidence(endpoint,identity['lora'])
        report['identity_unchanged']=identity==report['endpoint_after'] and adapter==report['adapter_after']
    except BaseException as exc:
        report['failure']={'type':type(exc).__name__,'detail':str(exc)}
        raise
    finally:
        _restore_writes(saved)
        write_new_json(out/'result.json',report)
        print(json.dumps(report,ensure_ascii=False,default=str),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    parser.add_argument('--run-local',action='store_true',required=True)
    asyncio.run(probe(parser.parse_args()))
