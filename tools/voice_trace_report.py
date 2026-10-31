"""Offline, content-free voice latency report; never claims acoustic acceptance."""
from __future__ import annotations
import argparse
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRS = {
    'request_to_callback_ms': ('request_received', 'playback_callback_first_nonzero'),
    'session_queue_ms': ('session_queue_enter', 'session_queue_exit'),
    'session_preprocess_ms': ('session_queue_exit', 'llm_request_start'),
    'llm_first_content_ms': ('llm_request_start', 'llm_first_content'),
    'first_text_segment_ms': ('llm_first_content', 'first_segment_ready'),
    'tts_submit_to_pcm_ms': ('first_tts_submit', 'first_pcm_produced'),
    'pcm_to_callback_ms': ('first_pcm_received', 'playback_callback_first_nonzero'),
}


def summarize(records):
    completed = [r for r in records if r.get('status') == 'completed']
    metrics = {}
    for name, (start, end) in PAIRS.items():
        values = []
        for record in completed:
            events = record.get('events_ms', {})
            a, b = events.get(start), events.get(end)
            if (isinstance(a, (int, float)) and isinstance(b, (int, float))
                    and math.isfinite(a) and math.isfinite(b) and b >= a):
                values.append(b-a)
        values.sort()
        metrics[name] = {'samples':len(values),
                         'p50': round(statistics.median(values), 3) if values else None,
                         'p95': round(values[math.ceil(.95*len(values))-1], 3) if values else None}
    overlaps = []
    for record in completed:
        events = record.get('events_ms', {})
        if all(isinstance(events.get(k), (int, float)) for k in ('llm_done', 'playback_callback_first_nonzero')):
            overlaps.append(events['playback_callback_first_nonzero'] < events['llm_done'])
    return {'records':len(records), 'completed':len(completed),
            'not_completed':len(records)-len(completed), 'metrics':metrics,
            'playback_before_llm_done':{'measurable':len(overlaps), 'observed':sum(overlaps)},
            'percentiles':'median P50; nearest-rank P95; completed turns only',
            'speech_end_to_acoustic_ms':None, 'hardware_acceptance':'not_established',
            'limitations':['Request arrival is not human speech end.',
                          'Nonzero callback is not acoustic sound or Bluetooth delivery.',
                          'At least 20 warm real-model turns per route are required for the planned gate.',
                          'TTS can start before final delta even when callback happens after LLM completion.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT/'artifacts/voice_turn_traces')
    parser.add_argument('--out', type=Path)
    args=parser.parse_args()
    records=[]
    invalid=0
    if args.directory.is_dir():
        for path in sorted(args.directory.glob('*.json')):
            try:
                value=json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(value, dict) or not isinstance(value.get('events_ms'), dict):
                    raise ValueError('invalid trace')
                records.append(value)
            except (OSError, ValueError):
                invalid+=1
    report=summarize(records)
    report['invalid_files']=invalid
    text=json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding='utf-8')
    print(text)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
