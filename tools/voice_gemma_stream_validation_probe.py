"""Read-only loopback Gemma stream/abort regression; no memory or audio devices."""
import asyncio,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.llm_vllm_provider import LlmVllmProvider

async def run():
    out=ROOT/'artifacts/validation/gemma_stream_20260930.json'
    p=LlmVllmProvider(base_url='http://127.0.0.1:8081',model='gemma-4-e4b',request_timeout_s=90)
    report={'scope':'existing generic provider, local service only; not voice main-path certification','runs':[]}
    async def one(prompt):
        start=time.perf_counter();first=None;deltas=[]
        async for d in p.stream_chat([{'role':'user','content':prompt}],max_tokens=32,temperature=0):
            first=first or time.perf_counter();deltas.append(d)
        return {'first_content_ms':round((first-start)*1000,2) if first else None,
                'total_ms':round((time.perf_counter()-start)*1000,2),'chars':len(''.join(deltas)),
                'delta_count':len(deltas)}
    try:
        for i in range(20):
            # Distinct text avoids exact whole-prompt cache reuse; not a production prompt benchmark.
            report['runs'].append(await one(f'第{i+1}次测试，请只回答：你好。'))
            out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        seen=[];ready=asyncio.Event()
        async def consume():
            async for d in p.stream_chat([{'role':'user','content':'请连续写二十条简短的中文句子，逐条编号。'}],max_tokens=256,temperature=0):
                seen.append(d);ready.set()
        task=asyncio.create_task(consume())
        await asyncio.wait_for(ready.wait(),90)
        start=time.perf_counter();p.abort('probe_interrupt')
        await asyncio.gather(task,return_exceptions=True)
        stopped=await p.wait_stopped(3);count=len(seen)
        stop_ms=(time.perf_counter()-start)*1000
        await asyncio.sleep(.3)
        report['cancel']={'local_stream_stopped':stopped,'stop_ms':round(stop_ms,2),
            'late_client_deltas_300ms':len(seen)-count,'server_compute_stop_verified':False}
        report['after_cancel']=await one('这是取消后的新请求，请只回答：完成。')
        times=sorted(x['first_content_ms'] for x in report['runs'] if x['first_content_ms'] is not None)
        report['stats']={'nonempty':sum(x['chars']>0 for x in report['runs']),
            'first_content_p50_ms':(times[9]+times[10])/2 if len(times)==20 else None,
            'first_content_p95_ms':times[18] if len(times)==20 else None,
            'percentile_method':'20 samples; nearest-rank P95; median P50; short synthetic prompts'}
        report['status']='completed'
    except Exception as e:report['error']={'type':type(e).__name__,'detail':str(e)[:500]}
    finally:
        await p.close();out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');asyncio.run(run())
