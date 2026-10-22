"""Runtime relocation and media-integrity regressions without GPU generation."""
import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'Agent'))
import musetalk_runtime as runtime
import musetalk_integrity_runner as runner
from musetalk_bridge import MuseTalkBridge


class MuseTalkPortableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT/'Video/MuseTalk/scripts/inference.py').read_text(encoding='utf-8')

    def test_current_source_hardened_without_shell_strings(self):
        source, mode = runner.patch_source(self.source)
        self.assertEqual(mode, 'clean-upstream-in-memory-hardening')
        self.assertNotIn('os.system(', source)
        ast.parse(source)
        self.assertIn('MuseTalk composite sequence is incomplete', source)
        self.assertIn('raise\n', source)

    def test_trailing_whitespace_does_not_disable_integrity(self):
        source = '\n'.join(line+'  ' for line in self.source.splitlines())+'\n'
        self.assertEqual(runner.patch_source(source)[1], 'clean-upstream-in-memory-hardening')

    def test_compositing_fix_does_not_reference_ori_frame_in_preprocessing(self):
        source, _ = runner.patch_source(self.source)
        before, after = source.split('# Pad generated images to original video size')
        self.assertIn('y2 = min(y2, frame.shape[0])', before)
        self.assertNotIn('ori_frame.shape', before)
        self.assertIn('y2 = min(y2, ori_frame.shape[0])', after)

    def test_ffmpeg_extraction_preserves_spaced_path_as_one_argument(self):
        source, _ = runner.patch_source(self.source)
        calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == 'run'
                 and isinstance(n.args[0], ast.List) and any(isinstance(x, ast.Constant)
                    and x.value == '-start_number' for x in n.args[0].elts)]
        self.assertEqual(len(calls), 1)
        import os
        env={'subprocess':subprocess, 'os':os, 'video_path':'X:/Portable AI/video & input.mp4',
             'save_dir_full':'X:/Portable AI/Cache/Media Jobs'}
        with patch.object(subprocess, 'run') as run:
            exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.Expr(calls[0])],type_ignores=[])), '<test>', 'exec'),env)
        args=run.call_args.args[0]
        self.assertIn(env['video_path'], args)
        self.assertTrue(run.call_args.kwargs['check'])

    def test_relocated_runtime_and_cache_do_not_inherit_host_python(self):
        with tempfile.TemporaryDirectory(prefix='Portable AI ') as d:
            root=Path(d)
            for rel in (runtime.PYTHON,runtime.PACKAGES+'/torch/__init__.py'):
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
            with patch.dict('os.environ', {'PYTHONHOME':'C:/Wrong', 'PYTHONPATH':'C:/Wrong'}):
                env=runtime.environment(root)
            self.assertNotIn('PYTHONHOME',env);self.assertNotIn('PYTHONPATH',env)
            for key in ('TEMP','TMP','TMPDIR','HF_HOME','TORCH_HOME','NUMBA_CACHE_DIR','MPLCONFIGDIR'):
                self.assertTrue(Path(env[key]).is_relative_to(root))
            self.assertEqual(runtime.resolve(root)[0],root/runtime.PYTHON)

    def test_wrong_python_abi_rejected(self):
        with patch.object(runtime.sys,'version_info',(3,12,0)):
            with self.assertRaisesRegex(RuntimeError,'ABI'):runtime.activate(ROOT)

    def _bridge(self, root):
        with patch('musetalk_bridge.root_dir', return_value=root):
            return MuseTalkBridge()

    def test_success_is_fresh_and_space_safe_and_staged_on_ssd(self):
        with tempfile.TemporaryDirectory(prefix='Portable AI ') as d:
            root=Path(d);video=root/'input video.mp4';audio=root/'input audio.wav'
            video.write_bytes(b'video');audio.write_bytes(b'audio');b=self._bridge(root)
            def run(args, **kwargs):
                self.assertIn('-I',args);self.assertNotIn('-m',args)
                self.assertEqual(args[args.index('-X')+1], 'utf8')
                results=Path(args[args.index('--result_dir')+1]);self.assertTrue(results.is_relative_to(root/'Cache'))
                job=results.parent;name='result_'+job.name.split('_',1)[1][:12]+'.mp4'
                out=results/'v15'/name;out.parent.mkdir();out.write_bytes(b'x'*2048)
                return subprocess.CompletedProcess(args,0,'generated','')
            with patch('radeon_edit.uses_radeon',return_value=False),patch.object(b,'status',return_value={'installed':True}),patch.object(b,'_python',return_value=Path('python.exe')),patch.object(b,'_require_job_space'),patch.object(b,'_utf8_child_env',return_value={}),patch('musetalk_bridge.subprocess.run',side_effect=run):
                result=b.sync(video,audio)
            self.assertEqual(Path(result['files'][0]).stat().st_size,2048)
            self.assertFalse(list((root/'Cache/MuseTalk').glob('musetalk_*')))

    def test_exit_zero_without_video_is_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);v=root/'v.mp4';a=root/'a.wav';v.write_bytes(b'v');a.write_bytes(b'a');b=self._bridge(root)
            with patch('radeon_edit.uses_radeon',return_value=False),patch.object(b,'status',return_value={'installed':True}),patch.object(b,'_python',return_value=Path('python.exe')),patch.object(b,'_require_job_space'),patch.object(b,'_utf8_child_env',return_value={}),patch('musetalk_bridge.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')):
                with self.assertRaisesRegex(RuntimeError,'produced no MP4'):b.sync(v,a)
            self.assertFalse(list((root/'Outputs').rglob('*.mp4')))


if __name__=='__main__':unittest.main()
