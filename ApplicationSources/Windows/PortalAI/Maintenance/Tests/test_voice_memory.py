"""Voice admission may recover only before effects, using owned healthy restoration."""
import json,sys,subprocess,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
from voice_memory import VoiceMemoryError,run_voice_stage,GIB
from chat_voice import VoiceStopped,VoiceIO
import stt_bridge


class VoiceMemoryTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.calls=[];self.check=Mock();self.original=Mock();self.idle=Mock()
        self.stack.enter_context(patch('workload_request.request_guard',return_value=self.original))
        self.stack.enter_context(patch('service_manager.root_dir',return_value=ROOT))
        self.lease=self.stack.enter_context(patch('service_manager.acquire_gpu_lease',side_effect=lambda *a,**k:self.calls.append('lease') or 'lease'))
        self.begin=self.stack.enter_context(patch('service_manager.qwen_gpu_handoff_begin',side_effect=lambda *a,**k:self.calls.append('unload') or {'active':True}))
        self.end=self.stack.enter_context(patch('service_manager.qwen_gpu_handoff_end',side_effect=lambda *a,**k:self.calls.append('restore') or {'ready':True}))
        self.release=self.stack.enter_context(patch('service_manager.release_gpu_lease',side_effect=lambda *a:self.calls.append('release')))
        self.low=VoiceMemoryError('Speech-to-text','base',3*GIB,2*GIB)

    def run_stage(self,admit,operation,**kw):
        return run_voice_stage(ROOT,'transcription',admit,operation,check=self.check,handoff_check=self.idle,**kw)

    def test_enough_memory_leaves_model_resident(self):
        operation=Mock(return_value='speech');self.assertEqual(self.run_stage(Mock(),operation),'speech')
        self.begin.assert_not_called();self.lease.assert_not_called();self.assertEqual(operation.call_count,1)

    def test_expressive_gpu_voice_always_serializes_and_restores(self):
        admit=Mock();operation=Mock(side_effect=lambda check:self.calls.append('voice') or 'speech')
        self.assertEqual(self.run_stage(admit,operation,require_handoff=True),'speech')
        self.assertEqual(self.calls,['lease','unload','voice','restore','release'])
        admit.assert_called_once();operation.assert_called_once()

    def test_low_memory_handoff_rechecks_and_restores_before_return(self):
        admit=Mock(side_effect=[self.low,None]);operation=Mock(side_effect=lambda check:self.calls.append('voice') or 'transcript')
        self.assertEqual(self.run_stage(admit,operation),'transcript')
        self.assertEqual(self.calls,['lease','unload','voice','restore','release']);self.assertEqual(admit.call_count,2)
        self.assertGreater(self.original.call_count,2);self.assertGreater(self.idle.call_count,1)

    def test_import_time_memory_drop_retries_only_once_before_inference(self):
        operation=Mock(side_effect=[self.low,'transcript'])
        self.assertEqual(self.run_stage(Mock(),operation),'transcript');self.assertEqual(operation.call_count,2)
        self.begin.assert_called_once();self.end.assert_called_once()

    def test_second_memory_rejection_is_not_retried(self):
        operation=Mock(side_effect=self.low)
        with self.assertRaises(VoiceMemoryError):self.run_stage(Mock(),operation)
        self.assertEqual(operation.call_count,2);self.begin.assert_called_once();self.end.assert_called_once()

    def test_unknown_failure_or_playback_failure_is_never_replayed(self):
        for error in (RuntimeError('after a side effect'),MemoryError('allocation failed'),OSError('audio device')):
            operation=Mock(side_effect=error)
            with self.assertRaises(type(error)):self.run_stage(Mock(),operation)
            self.assertEqual(operation.call_count,1)
        self.begin.assert_not_called()

    def test_cancel_while_waiting_never_unloads_model(self):
        self.lease.side_effect=TimeoutError('held');self.idle.side_effect=[None,VoiceStopped()]
        with self.assertRaises(VoiceStopped):self.run_stage(Mock(side_effect=self.low),Mock())
        self.begin.assert_not_called();self.release.assert_not_called()

    def test_busy_or_revoked_request_cannot_unload(self):
        self.idle.side_effect=VoiceStopped('new reply')
        with self.assertRaises(VoiceStopped):self.run_stage(Mock(side_effect=self.low),Mock())
        self.begin.assert_not_called()

    def test_cancelled_worker_is_cleaned_before_restoration(self):
        def operation(check):self.calls.append('worker-cleaned');raise VoiceStopped()
        with self.assertRaises(VoiceStopped):self.run_stage(Mock(side_effect=[self.low,None]),operation)
        self.assertEqual(self.calls,['lease','unload','worker-cleaned','restore','release'])

    def test_restore_failure_is_reported_and_lease_released(self):
        self.end.side_effect=TimeoutError('not healthy')
        with self.assertRaisesRegex(TimeoutError,'healthy'):self.run_stage(Mock(side_effect=[self.low,None]),Mock(return_value='done'))
        self.release.assert_called_once()

    def test_new_generation_cannot_report_success(self):
        self.end.side_effect=None;self.end.return_value={'stale_generation':True,'restored':False}
        with self.assertRaisesRegex(RuntimeError,'cancelled'):self.run_stage(Mock(side_effect=[self.low,None]),Mock())
        self.release.assert_called_once()

    def test_foreign_listener_or_no_model_does_not_bypass_ram_floor(self):
        self.begin.side_effect=None;self.begin.return_value={'active':False,'reason':'foreign'};operation=Mock()
        with self.assertRaises(VoiceMemoryError):self.run_stage(Mock(side_effect=self.low),operation)
        operation.assert_not_called();self.end.assert_not_called();self.release.assert_called_once()

    def test_both_voice_paths_use_the_same_memory_coordinator(self):
        voice=VoiceIO(ROOT,lambda:None)
        with patch('voice_memory.run_voice_stage',return_value={'text':'recognized'}) as run:
            self.assertEqual(voice.transcribe('synthetic.wav'),'recognized')
            self.assertEqual(run.call_args.args[1],'transcription')
        with patch('piper_bridge.output_path',return_value=ROOT/'synthetic-does-not-exist.wav'),patch('voice_memory.run_voice_stage') as run:
            voice.speak('Hello');self.assertEqual(run.call_args.args[1],'speech')

    def test_structured_worker_rejection_is_typed_and_clean(self):
        bridge=stt_bridge.SttBridge.__new__(stt_bridge.SttBridge)
        bridge.root=ROOT;bridge.worker=Path(__file__);bridge.python=Path(sys.executable);bridge._env=lambda:{}
        payload=self.low.payload();result=subprocess.CompletedProcess([],10,'PORTABLEAI_STT_RESULT='+json.dumps(payload),'')
        with patch('subprocess.run',return_value=result):
            with self.assertRaises(VoiceMemoryError) as caught:bridge._run([])
        self.assertNotIn('PORTABLEAI_STT_RESULT',str(caught.exception))
        self.assertIn('2.00 GiB',str(caught.exception))

    def test_malformed_or_effectful_payload_cannot_authorize_retry(self):
        for values in ({'phase':'inference'},{'files':['already-created.wav']},{'success':True},{'available_bytes':True},{'required_bytes':0}):
            self.assertIsNone(VoiceMemoryError.from_payload({**self.low.payload(),**values}))

if __name__=='__main__':unittest.main()
