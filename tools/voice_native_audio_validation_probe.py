"""Opt-in local-only native-audio probe; no devices, QQ, memory, or service restart.
Creates synthetic fixed fixtures with the existing Xiaoyi profile, posts WAVs
only to loopback Gemma, and synthesizes one reply. Not live duplex certification.
"""
from __future__ import annotations
import argparse, asyncio, base64, hashlib, json, os, sys, time, wave
from pathlib import Path
import httpx
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.target_voice_profile import build_target_qwen_config
from backend.tts_qwen_provider import create_qwen_provider
from backend.tts_provider_port import TTSRequest

def dump(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

async def run(out):
    out.mkdir(parents=True,exist_ok=False)
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    report={'scope':'synthetic audio -> native Gemma -> Xiaoyi TTS; no devices',
            'independent_asr':False,'live_duplex_tested':False,'cases':[]}
    provider=None
    try:
        config=build_target_qwen_config(tail_verify=False,max_new_tokens=256,stop_timeout_s=10)
        provider=create_qwen_provider(config,worker_id='native-audio-validation')
        async def synth(text,name,hold=False):
            start=time.perf_counter()
            session=await provider.open(TTSRequest(session_id='validation',turn_id=name,
                speech_id=name,provider_epoch=0,voice_id=config.resolved_voice_id))
            opened=time.perf_counter(); events=[]; pcm=[]; packet_ms=[]; stamps={}
            async def consume():
                async for event in session.audio_events():
                    now=time.perf_counter(); events.append(event.kind)
                    if event.chunk is not None:
                        stamps.setdefault('first_pcm',now)
                        pcm.append(event.chunk.data); packet_ms.append(event.chunk.duration_ms)
                    if event.kind=='PCM_STREAM_END':stamps['pcm_end']=now
            task=asyncio.create_task(consume())
            try:
                await session.push_text(text)
                if hold:await asyncio.sleep(1)
                pre_pcm=len(pcm); commit=time.perf_counter()
                await session.commit_text(); await asyncio.wait_for(task,120)
                await session.wait_stopped(10)
                if not pcm:raise RuntimeError('no PCM: '+repr(events))
                wav=out/(name+'.wav')
                with wave.open(str(wav),'wb') as w:
                    w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b''.join(pcm))
                audio_ms=sum(packet_ms)
                return {'wav':str(wav),'text':text,'open_ms':round((opened-start)*1000,2),
                    'precommit_hold_ms':1000 if hold else 0,'pcm_before_commit':pre_pcm,
                    'commit_to_first_pcm_ms':round((stamps['first_pcm']-commit)*1000,2),
                    'commit_to_pcm_end_ms':round((stamps['pcm_end']-commit)*1000,2),
                    'audio_ms':audio_ms,'packet_ms':packet_ms,'events':events,
                    'generation_rtf':round((stamps['pcm_end']-commit)*1000/audio_ms,3)}
            finally:
                if not task.done():
                    await session.cancel('probe_cleanup'); task.cancel()
        async def ask(content):
            start=time.perf_counter(); first=None; pieces=[]; finish=None
            async with httpx.AsyncClient(timeout=120,trust_env=False) as client:
                async with client.stream('POST','http://127.0.0.1:8081/v1/chat/completions',json={
                    'model':'gemma-4-e4b','messages':[{'role':'user','content':content}],
                    'stream':True,'max_tokens':64,'temperature':0,'reasoning_effort':'none'}) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith('data:'):continue
                        payload=line[5:].strip()
                        if payload=='[DONE]':break
                        obj=json.loads(payload)
                        if obj.get('error'):raise RuntimeError(str(obj['error']))
                        for choice in obj.get('choices',[]):
                            delta=choice.get('delta',{}).get('content') or ''
                            if delta:
                                if first is None:first=time.perf_counter()
                                pieces.append(delta)
                            finish=choice.get('finish_reason') or finish
            return {'first_content_ms':None if first is None else round((first-start)*1000,2),
                'total_ms':round((time.perf_counter()-start)*1000,2),'content':''.join(pieces),
                'delta_count':len(pieces),'finish_reason':finish}
        async with httpx.AsyncClient(timeout=10,trust_env=False) as client:
            props=(await client.get('http://127.0.0.1:8081/props')).json()
        report['server']={k:props.get(k) for k in ['model_alias','model_ftype','modalities','build_info','total_slots']}
        for i,(question,expected) in enumerate([('七加五等于多少？只说答案。',['12','十二']),('八减三等于多少？只说答案。',['5','五'])]):
            case={'question':question,'expected_any':expected};report['cases'].append(case)
            case['fixture']=await synth(question,'question_'+str(i),hold=(i==0));dump(out/'summary.json',report)
            audio=base64.b64encode(Path(case['fixture']['wav']).read_bytes()).decode()
            # Do not send fixture transcript/answer to the audio condition.
            case['audio']=await ask([{'type':'text','text':'请直接回答音频中的问题，不要转写，只说答案。'},
                {'type':'input_audio','input_audio':{'data':audio,'format':'wav'}}])
            case['audio']['matches_expected']=any(x in case['audio']['content'] for x in expected)
            dump(out/'summary.json',report)
            case['text_control']=await ask(question)
            if case['audio']['content']:
                case['reply']=await synth(case['audio']['content'][:80],'reply_'+str(i))
                case['sequential_request_to_reply_pcm_ms']=round(case['audio']['total_ms']+case['reply']['open_ms']+case['reply']['commit_to_first_pcm_ms'],2)
            dump(out/'summary.json',report)
        report['status']='completed'
    except Exception as e:
        report['status']='error';report['error']={'type':type(e).__name__,'detail':str(e)[:1000]}
    finally:
        if provider:provider.shutdown(timeout_s=10)
        dump(out/'summary.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['status']=='completed' else 1
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();raise SystemExit(asyncio.run(run(args.out)))
