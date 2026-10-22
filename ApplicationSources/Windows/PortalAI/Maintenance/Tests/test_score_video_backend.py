"""Execute the real scaled scoring branch with synthetic media workers."""
import ast
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import music_amd_bridge as music


class ScoreBackendTests(unittest.TestCase):
    def test_result_reports_admitted_rocm_or_linux_cuda_backend(self):
        tree=ast.parse((ROOT/'Agent/ai_tools.py').read_text(encoding='utf-8-sig'))
        node=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="args.cmd == 'score-video'")
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);video=root/'source.mp4';audio=root/'score.flac';out=root/'scored.mp4'
            for backend in ('cuda','rocm'):
                events=[];profile={'backend':backend,'engine':'acestep-rocm'}
                args=SimpleNamespace(cmd='score-video',video=str(video),prompt='gentle strings',
                    lyrics=None,instrumental=True,output=str(out),music_volume=.25)
                @contextmanager
                def lease(*a):
                    events.append('reclaim')
                    try:yield
                    finally:events.append('restore')
                def admit():events.append('admit');return profile
                def generate(*a):events.append('generate');return {'files':[str(audio)],'profile':profile}
                emit=Mock(side_effect=StopIteration)
                scope={'args':args,'Path':Path,'root_dir':lambda:root,'_media_duration_seconds':lambda path:15.,
                    'media_reference':lambda base,path:Path(path),'media_output':lambda base,path:Path(path),
                    '_exclusive_gpu':lease,'_sound_video':Mock(return_value=out),'emit':emit,
                    'service_start':Mock(side_effect=AssertionError('CUDA service branch must not run'))}
                with self.subTest(backend=backend),patch.object(music,'use_rocm',return_value=True), \
                     patch.object(music,'plan',side_effect=admit),patch.object(music,'generate',side_effect=generate):
                    with self.assertRaises(StopIteration):
                        exec(compile(ast.Module(body=[node],type_ignores=[]),'score-route','exec'),scope)
                payload=emit.call_args.args[0]
                self.assertEqual(payload['backend'],backend)
                self.assertEqual(payload['profile'],profile)
                self.assertEqual(events,['reclaim','admit','generate','restore'])
                scope['service_start'].assert_not_called()
                self.assertEqual(scope['_sound_video'].call_args.args[2:4],(None,audio))


if __name__=='__main__':unittest.main()
