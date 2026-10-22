"""Comfy's allocator policy precedes tensor imports; no real GPU or account state."""
import builtins
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'Agent'))
import comfy_amd_entry as entry
import linux_ml


class ComfyEntryOrderTests(unittest.TestCase):
    def test_linux_layer_activation_does_not_preimport_torch(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            layer=root/'Runtime/LinuxTorch/cu128'
            (layer/'torch').mkdir(parents=True)
            (layer/'torch/__init__.py').write_text('# synthetic package')
            receipt=root/'Maintenance/Imports/linux-torch-cu128.json'
            receipt.parent.mkdir(parents=True)
            receipt.write_text('{"verified":true}')
            original_import=builtins.__import__
            def importing(name,*args,**kwargs):
                self.assertFalse(name=='torch' or name.startswith('torch.'),name)
                return original_import(name,*args,**kwargs)
            with patch.object(sys,'platform','linux'), patch.object(sys,'version_info',(3,12)), \
                 patch.object(sys,'path',list(sys.path)), patch.dict(sys.modules), \
                 patch.dict(linux_ml.os.environ,{},clear=True), \
                 patch.object(linux_ml,'compatibility_layer',return_value=root/'compat'), \
                 patch('runtime_policy.portable_env',return_value={}), \
                 patch('builtins.__import__',side_effect=importing):
                for name in ('torch','torchvision','torchaudio'):sys.modules.pop(name,None)
                self.assertEqual(linux_ml.activate(root,'cuda'),layer)

    @contextmanager
    def fixture(self, *, windows=False, hip=None, available=True, arguments=(),
                allocator_error=None, run_error=None):
        events=[]
        env={}
        platform=SimpleNamespace(name='nt' if windows else 'posix', environ=env, chdir=Mock())
        original_import=builtins.__import__
        tensor=SimpleNamespace(version=SimpleNamespace(hip=hip),
                               cuda=SimpleNamespace(is_available=Mock(return_value=available)))
        comfy=ModuleType('comfy');comfy.options=SimpleNamespace(
            enable_args_parsing=lambda:events.append('arguments'))
        allocator=ModuleType('cuda_malloc')
        def importing(name, *args, **kwargs):
            if name=='comfy.options':return comfy
            if name=='cuda_malloc':
                self.assertIn('arguments',events)
                self.assertNotIn('--portalai-cpu-validation',sys.argv)
                events.append('allocator')
                if allocator_error:raise allocator_error
                # Stand in for upstream honoring an explicit disable flag.
                env['selected_allocator']='native' if '--disable-cuda-malloc' in sys.argv else 'cudaMallocAsync'
                return allocator
            if name=='torch':
                events.append('torch')
                if not windows:self.assertIn('selected_allocator',env)
                return tensor
            return original_import(name,*args,**kwargs)
        @contextmanager
        def reader(rocm):
            events.append(('reader',rocm))
            try:yield
            finally:events.append('reader-cleanup')
        def run(*args,**kwargs):
            events.append('main')
            if run_error:raise run_error
        with patch.object(entry,'os',platform), patch.object(entry,'portable_env',return_value={}), \
             patch.object(entry,'activate',side_effect=lambda *a,**k:events.append('windows-layer')), \
             patch.object(linux_ml,'activate',side_effect=lambda *a,**k:events.append('linux-layer')), \
             patch.object(entry.runpy,'run_path',side_effect=run), \
             patch.object(sys,'argv',['comfy_amd_entry.py',*arguments]), \
             patch.object(sys,'path',list(sys.path)), patch.dict(sys.modules), \
             patch('comfy_safetensors.windows_rocm_cpu_reader',reader), \
             patch('builtins.__import__',side_effect=importing):
            sys.modules.pop('torch',None)
            yield events,env,tensor

    def test_linux_allocator_precedes_first_torch_import(self):
        with self.fixture() as (events,env,_):
            entry.main()
            self.assertEqual(events[:4],['linux-layer','arguments','allocator','torch'])
            self.assertEqual(env['selected_allocator'],'cudaMallocAsync')
            self.assertEqual(events[-3:],[('reader',False),'main','reader-cleanup'])

    def test_linux_explicit_allocator_disable_reaches_upstream_policy(self):
        with self.fixture(arguments=['--disable-cuda-malloc']) as (_,env,_):
            entry.main()
            self.assertEqual(env['selected_allocator'],'native')

    def test_diagnostic_flag_removed_before_upstream_argument_parsing(self):
        with self.fixture(arguments=['--portalai-cpu-validation','--cpu'],available=False) as (events,_,tensor):
            entry.main()
            self.assertIn('main',events)
            tensor.cuda.is_available.assert_not_called()

    def test_linux_implicit_cpu_fallback_still_refused(self):
        with self.fixture(available=False) as (events,_,_):
            with self.assertRaisesRegex(RuntimeError,'implicit CPU fallback'):entry.main()
            self.assertNotIn('main',events)

    def test_allocator_failure_does_not_import_torch_or_dispatch(self):
        with self.fixture(allocator_error=RuntimeError('allocator fixture failed')) as (events,_,_):
            with self.assertRaisesRegex(RuntimeError,'allocator fixture failed'):entry.main()
            self.assertNotIn('torch',events);self.assertNotIn('main',events)

    def test_loaded_torch_is_refused_before_late_allocator_mutation(self):
        with self.fixture() as (events,_,_):
            sys.modules['torch']=ModuleType('torch')
            with self.assertRaisesRegex(RuntimeError,'fresh worker'):entry.main()
            self.assertEqual(events,['linux-layer'])

    def test_windows_rocm_route_does_not_run_linux_allocator_prelude(self):
        with self.fixture(windows=True,hip='7.2') as (events,_,_):
            entry.main()
            self.assertEqual(events,['windows-layer','torch',('reader',True),'main','reader-cleanup'])

    def test_windows_non_rocm_and_normal_cpu_guard_still_refuse(self):
        for hip,arguments,error in ((None,(),'non-ROCm'),('7.2',('--cpu',),'dedicated diagnostic')):
            with self.fixture(windows=True,hip=hip,arguments=arguments) as (events,_,_):
                with self.assertRaisesRegex((RuntimeError,ValueError),error):entry.main()
                self.assertNotIn('main',events)

    def test_scoped_reader_cleanup_survives_upstream_startup_failure(self):
        with self.fixture(run_error=RuntimeError('main fixture failed')) as (events,_,_):
            with self.assertRaisesRegex(RuntimeError,'main fixture failed'):entry.main()
            self.assertEqual(events[-1],'reader-cleanup')


if __name__=='__main__':unittest.main()
