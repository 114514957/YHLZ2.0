"""Replay existing synthetic fixtures with 16k/24k and silence controls, local only."""
import base64,json,sys,time,wave
from pathlib import Path
import httpx,numpy as np
from scipy.signal import resample_poly
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/validation/native_audio_20260930'
sys.stdout.reconfigure(encoding='utf-8')

def ask(path,prompt):
    parts=[{'type':'text','text':prompt}]
    if path:parts.append({'type':'input_audio','input_audio':{'data':base64.b64encode(path.read_bytes()).decode(),'format':'wav'}})
    t=time.perf_counter(); first=None; text=''
    with httpx.Client(timeout=90,trust_env=False) as c:
        with c.stream('POST','http://127.0.0.1:8081/v1/chat/completions',json={
            'model':'gemma-4-e4b','messages':[{'role':'user','content':parts}],
            'reasoning_effort':'none','temperature':0,'max_tokens':64,'stream':True}) as r:
            r.raise_for_status()
            for l in r.iter_lines():
                if not l.startswith('data:'):continue
                s=l[5:].strip()
                if s=='[DONE]':break
                j=json.loads(s)
                for ch in j.get('choices',[]):
                    d=ch.get('delta',{}).get('content') or ''
                    if d:
                        first=first or time.perf_counter();text+=d
    return {'content':text,'first_content_ms':round((first-t)*1000,2) if first else None,'total_ms':round((time.perf_counter()-t)*1000,2)}
res={'scope':'format/semantic controls; model remains same; no independent ASR','cases':[]}
try:
 for i in range(2):
    src=OUT/f'question_{i}.wav'; dst=OUT/f'question_{i}_16k.wav'
    with wave.open(str(src),'rb') as w:pcm=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2');sr=w.getframerate()
    samples=np.clip(np.rint(resample_poly(pcm.astype(np.float32),2,3)),-32768,32767).astype('<i2')
    with wave.open(str(dst),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(samples.tobytes())
    for rate,path in [(16000,dst),(24000,src)]:
      case={'fixture':path.name,'sample_rate':rate,'transcription':ask(path,'转写这段音频，只输出内容。')}
      if rate==16000:case['answer']=ask(path,'请直接回答音频中的问题，不要转写，只说答案。')
      res['cases'].append(case);print(json.dumps(case,ensure_ascii=False));(OUT/'controls.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
 silence=OUT/'silence_16k.wav'
 with wave.open(str(silence),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\x00\x00'*16000)
 res['silence']=ask(silence,'转写这段音频，只输出内容。没有人声时回答无语音。')
 res['status']='completed'
except Exception as e:res['error']={'type':type(e).__name__,'detail':str(e)[:500]}
(OUT/'controls.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))
