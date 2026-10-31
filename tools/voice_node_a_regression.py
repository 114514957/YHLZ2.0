"""Repeatable isolated Node A regression. Does not open hardware or voice models."""
import argparse
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
MODULES = [
 'test_duplex_wiring', 'test_phase3_barge_in', 'test_session_kernel',
 'test_target_composition', 'test_target_runtime', 'test_tts_qwen_provider',
 'test_tts_pcm_stream_end', 'test_voice_streaming', 'test_target_entry',
 'test_llm_stream', 'test_tts_segmented_provider', 'test_voice_stream_binding',
 'test_target_daemon', 'test_target_voice_profile', 'test_target_workbench_adapter',
 'test_target_chain', 'test_chain_audio_streaming', 'test_daemon_target_voice',
 'test_voice_node_a_completion', 'test_target_playback', 'test_target_playback_format',
 'test_playback_reference', 'test_playback_aec', 'test_voice_trace',
 'test_native_audio_ingress', 'test_asr_bridge', 'test_streaming_asr_bridge',
 'test_speech_segment', 'test_target_memory', 'test_voice_jobs',
]

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--out',type=Path,default=ROOT/'artifacts/validation/20261001_node_a_final')
 args=parser.parse_args()
 args.out.mkdir(parents=True,exist_ok=True)
 started=time.perf_counter()
 with patch('backend.entity_graph.ingest_text',new_callable=AsyncMock), patch(
       'backend.intrinsic_drives.observe'), patch('backend.intrinsic_drives.dad_direction'):
  suite=unittest.defaultTestLoader.loadTestsFromNames(['backend.'+m for m in MODULES])
  with (args.out/'unittest.log').open('w',encoding='utf-8') as log:
   result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
 report={'modules':MODULES,'tests_run':result.testsRun,'failures':len(result.failures),
         'errors':len(result.errors),'skipped':len(result.skipped),'passed':result.wasSuccessful(),
         'elapsed_s':round(time.perf_counter()-started,3),
         'evidence':'unit_and_isolated_integration','real_voice_model_loaded':False,
         'audio_device_opened':False,'hardware_acceptance':'not_run',
         'isolation':'entity_graph.ingest_text/intrinsic_drives.observe/dad_direction mocked; memory stores use test fixtures'}
 (args.out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False))
 return 0 if result.wasSuccessful() else 1

if __name__=='__main__':
 raise SystemExit(main())
