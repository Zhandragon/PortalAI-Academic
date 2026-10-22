"""Inspect the diagnostic boundary without executing model or GPU code."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
import smoke_vace_reference_cpu as smoke
import vace_cpu_entry as entry
from validation_artifacts import ValidationArtifacts


class CpuSmokeTests(unittest.TestCase):
    def test_all_writable_comfy_paths_are_synthetic_and_backend_is_cpu(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            command,paths=smoke.build_command(folder,45678)
            self.assertIn('--cpu',command);self.assertIn('--disable-all-custom-nodes',command)
            self.assertIn('--fp16-unet',command);self.assertNotIn('--force-fp16',command)
            self.assertIn('--disable-api-nodes',command)
            for key in ('base','input','output','temp','user'):
                self.assertEqual(Path(command[command.index('--'+key+'-directory')+1]),paths[key])
                self.assertTrue(paths[key].is_relative_to(folder))
            self.assertEqual(Path(command[0]),ROOT/'Generative/ComfyUI_windows_portable/python_embeded/python.exe')
            self.assertIn(str(ROOT/'Tools/vace_cpu_entry.py'),command)

    def test_graph_builder_does_not_initialize_production_profile_client(self):
        with patch.object(smoke.ComfyBridge,'__init__',side_effect=AssertionError('production config')):
            graph=smoke.configure(smoke.SyntheticGraph(),{'prompt':'cube','width':128,'height':128,
                 'frames':5,'fps':5,'seed':52},'synthetic.png')
        self.assertEqual(graph['16']['inputs']['image'],'synthetic.png')
        self.assertNotIn('control_video',graph['10']['inputs'])

    def test_runner_requires_explicit_synthetic_artifacts_and_bounded_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifacts=ValidationArtifacts(ROOT,temporary)
            with patch.object(smoke.os,'name','nt'):
                for timeout in (0,601):
                    with self.assertRaisesRegex(ValueError,'timeout'):smoke.run(artifacts,timeout)
                artifacts.synthetic=False
                with self.assertRaisesRegex(ValueError,'explicit synthetic'):smoke.run(artifacts)

    def test_native_failure_is_not_hidden_by_transport_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            log=Path(temporary)/'comfy.log'
            log.write_text('CPU active\nWindows fatal exception: access violation\n  File torch/storage.py, line 471\n')
            process=Mock();process.poll.return_value=0xffffffff
            result=smoke.failure_details(TimeoutError('timed out'),process,log)
        self.assertEqual(result['error'],'Windows fatal exception: access violation')
        self.assertEqual(result['transport_error'],'timed out')
        self.assertEqual(result['worker_exit_code_hex'],'0xffffffff')
        self.assertEqual(result['failure_kind'],'native_process_failure')
        self.assertIn('torch/storage.py',result['log_tail'])

    def test_exit_and_log_evidence_are_bounded_without_mislabeling_healthy_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            log=Path(temporary)/'comfy.log';log.write_text('x'*20000+'\nCPU still active')
            process=Mock();process.poll.return_value=None
            result=smoke.failure_details(TimeoutError('timed out'),process,log)
            self.assertIsNone(result['worker_exit_code_before_cleanup'])
            self.assertEqual(result['failure_kind'],'diagnostic_error')
            self.assertLessEqual(len(result['log_tail']),12000)
            process.poll.return_value=3
            result=smoke.failure_details(RuntimeError('worker exited'),process,log)
        self.assertEqual(result['failure_kind'],'worker_exit')
        self.assertEqual(result['worker_exit_code_hex'],'0x3')

    def test_pread_wrapper_is_cpu_only_and_restores_originals_on_error(self):
        loader=Mock();torch_loader=Mock()
        original=loader.safe_open;torch_original=torch_loader.safe_open
        with self.assertRaisesRegex(RuntimeError,'test end'):
            with entry.positional_cpu_reader(loader,torch_loader):
                loader.safe_open('model.safetensors',framework='pt',device='cpu')
                original.assert_called_with('model.safetensors',framework='pt',device='cpu',backend='pread')
                loader.safe_open('model.safetensors',framework='pt',device='cuda')
                original.assert_called_with('model.safetensors',framework='pt',device='cuda')
                torch_loader.safe_open('model.safetensors',framework='pt',device='cpu',backend='mmap')
                torch_original.assert_called_with('model.safetensors',framework='pt',device='cpu',backend='mmap')
                loader.safe_open('model.safetensors','pt','cpu','mmap')
                original.assert_called_with('model.safetensors','pt','cpu','mmap')
                torch_loader.safe_open('model.safetensors','pt','cpu','pread')
                torch_original.assert_called_with('model.safetensors','pt','cpu','pread')
                loader.safe_open('model.safetensors',framework='np')
                original.assert_called_with('model.safetensors',framework='np')
                raise RuntimeError('test end')
        self.assertIs(loader.safe_open,original);self.assertIs(torch_loader.safe_open,torch_original)

    def test_entry_refuses_missing_cpu_flags_before_importing_model_libraries(self):
        with patch.object(entry.sys,'argv',['probe']):
            with self.assertRaisesRegex(ValueError,'CPU diagnostic flags'):entry.main()

    def test_entry_defers_torch_import_until_comfy_sets_allocator_policy(self):
        import types
        module=types.ModuleType('safetensors');module.safe_open=Mock()
        with patch.object(entry.sys,'argv',['probe','--cpu','--fp16-unet']), \
             patch.dict(entry.sys.modules,{'safetensors':module}), \
             patch.object(entry.runpy,'run_path') as run:
            entry.main()
        run.assert_called_once()


if __name__=='__main__':unittest.main()
