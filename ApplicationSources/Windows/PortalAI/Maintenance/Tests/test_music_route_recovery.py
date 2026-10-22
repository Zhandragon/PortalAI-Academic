"""Music specialist reporting and dialogue-score routing without model loads."""
import ast
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import MagicMock,patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'Agent'))
import music_understanding_enhanced as enhanced
import music_amd_bridge as music


class MusicRouteTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.bridge=enhanced.EnhancedMusicUnderstandingBridge();self.bridge.root=self.root
        self.bridge.legacy=MagicMock();self.bridge.legacy.understand.return_value={'features':{'tempo':120}}

    def test_linux_does_not_attempt_existing_windows_specialist(self):
        # Change only this module's platform view. Mutating os.name globally
        # makes pathlib instantiate the wrong concrete path class on Windows.
        with patch.object(enhanced,'os',SimpleNamespace(name='posix')),patch.object(enhanced,'_run_json') as execute:
            result=self.bridge.understand('fixture.wav')
        execute.assert_not_called()
        self.assertTrue(result['success']);self.assertTrue(result['partial'])
        self.assertFalse(result['enhanced_music_understanding']);self.assertEqual(result['semantic_backend'],'deterministic-only')

    def test_all_failed_analyzers_are_failure_not_empty_success(self):
        self.bridge.legacy.understand.side_effect=RuntimeError('decode failed')
        with patch.object(self.bridge,'_specialist_available',return_value=(True,None)),\
             patch.object(enhanced,'_run_json',side_effect=RuntimeError('worker failed')):
            result=self.bridge.understand('fixture.wav',semantic=False)
        self.assertFalse(result['success']);self.assertFalse(result['enhanced_music_understanding'])
        self.assertEqual(result['semantic_backend'],'unavailable')

    def test_failed_moss_does_not_claim_moss_with_deterministic_fallback(self):
        with patch.object(self.bridge,'_specialist_available',return_value=(True,None)),\
             patch.object(enhanced,'_run_json',side_effect=RuntimeError('worker failed')):
            result=self.bridge.understand('fixture.wav',semantic=False)
        self.assertTrue(result['success']);self.assertTrue(result['partial'])
        self.assertEqual(result['semantic_backend'],'deterministic-only')

    def test_successful_moss_only_reports_backends_actually_used(self):
        with patch.object(self.bridge,'_specialist_available',return_value=(True,None)),\
             patch.object(enhanced,'_run_json',return_value={'text':'Supported audio observation'}):
            result=self.bridge.understand('fixture.wav',semantic=True)
        self.assertTrue(result['success']);self.assertTrue(result['enhanced_music_understanding'])
        self.assertEqual(result['semantic_backend'],'MOSS-Music')

    def helper(self,duration=15):
        tree=ast.parse((ROOT/'Agent/ai_tools.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_generate_matched_music_serial')
        scope={'Path':Path,'math':__import__('math'),'_media_duration_seconds':lambda video:duration,
               'quiesce_gpu_workers':MagicMock(),'_set_gpu_state':MagicMock(),'_clear_gpu_state':MagicMock(),
               'service_start':MagicMock(),'service_wait':MagicMock(),'_acestep_model_labels':lambda:[],
               'resolve_root':lambda path:self.root/path,'AceStepBridge':MagicMock()}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(ROOT/'Agent/ai_tools.py'),'exec'),scope)
        return scope

    def test_scaled_dialogue_score_uses_exact_duration_without_service(self):
        scope=self.helper(12.5);output=self.root/'score.flac';output.touch()
        with patch.object(music,'use_rocm',return_value=True),patch.object(music,'plan',return_value={'backend':'rocm'}),\
             patch.object(music,'generate',return_value={'files':[str(output)]}) as generate:
            result=scope['_generate_matched_music_serial']({},Path('shot.mp4'),'music',None,True)
        generate.assert_called_once_with({'backend':'rocm'},'music','',12.5,True)
        scope['service_start'].assert_not_called();scope['service_wait'].assert_not_called()
        self.assertEqual(result[1:],(output,12.5))

    def test_scaled_dialogue_score_does_not_round_or_truncate_limits(self):
        for duration in (8,30.1):
            scope=self.helper(duration)
            with patch.object(music,'use_rocm',return_value=True),patch.object(music,'generate') as generate:
                with self.assertRaisesRegex(ValueError,'10..30'):
                    scope['_generate_matched_music_serial']({},Path('shot.mp4'),'music',None,True)
            generate.assert_not_called();scope['quiesce_gpu_workers'].assert_not_called()

    def test_windows_nvidia_score_keeps_service_route(self):
        scope=self.helper(12.5);bridge=scope['AceStepBridge'].return_value
        bridge.generate.return_value=('service-task',{'done':True});bridge.download.return_value=[str(self.root/'score.wav')]
        with patch.object(music,'use_rocm',return_value=False),patch.object(music,'generate') as scaled:
            result=scope['_generate_matched_music_serial']({'outputs':{'music':'Outputs/Music'}},Path('shot.mp4'),'music',None,True)
        scaled.assert_not_called();scope['service_start'].assert_called_once_with('acestep')
        bridge.generate.assert_called_once_with('music',None,13,True);self.assertEqual(result[0],'service-task')


if __name__=='__main__':unittest.main()
