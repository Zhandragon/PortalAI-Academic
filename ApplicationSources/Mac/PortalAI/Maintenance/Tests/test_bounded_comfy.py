"""Bounded ComfyUI startup/lifetime tests without importing a model or starting a server."""
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import bounded_comfy as bounded
import service_manager


class BoundedComfyTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='Portal bounded comfy ')
        self.addCleanup(folder.cleanup);self.root=Path(folder.name).resolve()
        self.profile={'backend':'rocm','max_memory_bytes':1024**3,'min_free_ram_bytes':512*1024**2}
        self.process=Mock();self.process.returncode=None
        self.process.poll.side_effect=lambda:self.process.returncode
        self.job=Mock();self.job.linux=None;self.job.handle=123
        self.job.close.side_effect=lambda:setattr(self.process,'returncode',0)
        self.events=[];self.gate=None
        self.log_bytes=b'bounded test log\n'
        self.addCleanup(patch.stopall)
        self.Popen=patch.object(bounded.subprocess,'Popen',side_effect=self.start).start()
        patch.object(bounded,'WorkerJob',return_value=self.job).start()
        self.job.limit_memory.side_effect=self.limit
        patch.object(bounded,'python_path',return_value=self.root/'runtime-python').start()
        patch.object(bounded,'portable_env',return_value={}).start()
        patch.object(bounded,'memory_info',return_value=(32*1024**3,16*1024**3)).start()
        self.port=patch.object(service_manager,'port_open',side_effect=[False,True]).start()
        patch.object(service_manager,'_listening_pids',return_value=[4321]).start()
        self.owns=patch.object(bounded,'owns_pid',return_value=True).start()
        self.http=patch.object(bounded.urllib.request,'urlopen',side_effect=self.response).start()

    def start(self,command,**kwargs):
        self.request=json.loads(Path(command[-1]).read_text())
        self.gate=Path(self.request['gate'])
        self.assertFalse(self.gate.exists())
        self.worker_env=kwargs['env']
        kwargs['stdout'].write(self.log_bytes)
        kwargs['stdout'].flush()
        self.events.append('spawn')
        return self.process

    def limit(self,size):
        self.assertFalse(self.gate.exists(),'Worker gate opened before OS memory limit')
        self.assertEqual(size,self.profile['max_memory_bytes'])
        self.events.append('limit')

    def response(self,*args,**kwargs):
        self.assertTrue(self.gate.exists())
        self.assertIn('limit',self.events)
        self.events.append('ready')
        return io.BytesIO(b'{"system":{"comfyui_version":"test"}}')

    def test_limit_precedes_gate_and_ready_requires_owned_listener(self):
        with bounded.session(self.profile,root=self.root) as result:
            self.assertIs(result['job'],self.job)
            self.assertTrue(self.gate.exists())
            self.assertEqual(self.events,['spawn','limit','ready'])
            self.assertEqual(self.worker_env['PORTALAI_TORCH_BACKEND'],'rocm')
        self.job.close.assert_called_once()
        self.process.wait.assert_called_once_with(timeout=10)
        self.assertFalse(self.gate.exists())
        self.assertEqual(self.owns.call_count,2)

    def test_cap_failure_keeps_gate_closed_and_reaps_worker(self):
        self.job.limit_memory.side_effect=RuntimeError('cap failed')
        with self.assertRaisesRegex(RuntimeError,'cap failed'):
            with bounded.session(self.profile,root=self.root):self.fail('Must not yield')
        self.http.assert_not_called();self.job.close.assert_called_once()
        self.process.wait.assert_called_once();self.assertFalse(self.gate.exists())

    def test_cap_and_close_failure_still_kills_and_reaps_gated_process(self):
        self.job.limit_memory.side_effect=RuntimeError('cap failed')
        self.job.close.side_effect=RuntimeError('close failed')
        with self.assertRaisesRegex(RuntimeError,'close failed'):
            with bounded.session(self.profile,root=self.root):self.fail('Must not yield')
        self.process.kill.assert_called_once();self.process.wait.assert_called_once()
        self.http.assert_not_called()

    def test_job_constructor_failure_reaps_gated_worker(self):
        with patch.object(bounded,'WorkerJob',side_effect=RuntimeError('job failed')):
            with self.assertRaisesRegex(RuntimeError,'job failed'):
                with bounded.session(self.profile,root=self.root):self.fail('Must not yield')
        self.process.kill.assert_called_once();self.process.wait.assert_called_once()
        self.http.assert_not_called()

    def test_preexisting_port_is_never_adopted_or_killed(self):
        self.port.side_effect=None;self.port.return_value=True
        with self.assertRaisesRegex(RuntimeError,'already occupied'):
            with bounded.session(self.profile,root=self.root):self.fail('Must not yield')
        self.Popen.assert_not_called();self.http.assert_not_called();self.job.close.assert_not_called()

    def test_foreign_listener_racing_startup_is_not_adopted(self):
        self.owns.return_value=False
        with self.assertRaisesRegex(RuntimeError,'outside this bounded'):
            with bounded.session(self.profile,root=self.root):self.fail('Must not yield')
        self.http.assert_not_called();self.job.close.assert_called_once()

    def test_listener_change_during_http_is_rejected(self):
        with patch.object(service_manager,'_listening_pids',side_effect=[[4321],[4322]]):
            with self.assertRaisesRegex(RuntimeError,'changed during readiness'):
                with bounded.session(self.profile,root=self.root):self.fail('Must not yield')
        self.job.close.assert_called_once()

    def test_non_comfy_success_response_is_not_readiness(self):
        self.http.side_effect=lambda *a,**k:io.BytesIO(b'{"ok":true}')
        with self.assertRaisesRegex(ValueError,'Unexpected ComfyUI'):
            with bounded.session(self.profile,root=self.root):self.fail('Must not yield')
        self.job.close.assert_called_once()

    def test_ram_reserve_failure_cleans_up_without_http(self):
        with patch.object(bounded,'memory_info',return_value=(1024**3,1)):
            with self.assertRaisesRegex(RuntimeError,'RAM reserve'):
                with bounded.session(self.profile,root=self.root):self.fail('Must not yield')
        self.http.assert_not_called();self.job.close.assert_called_once()

    def test_startup_timeout_cleans_up(self):
        with patch.object(bounded.time,'monotonic',side_effect=[0,2]):
            with self.assertRaises(TimeoutError):
                with bounded.session(self.profile,root=self.root,timeout=1):self.fail('Must not yield')
        self.job.close.assert_called_once();self.process.wait.assert_called_once()

    def test_native_startup_crash_reports_signal_and_cause_before_cleanup(self):
        self.process.returncode=-4
        self.log_bytes=(b'startup\n'*1000+b'Fatal Python error: Illegal instruction\n'
            b'Current thread in kornia_rs\n'+b'  File importlib\n'*400+b'  File comfy_amd_entry.py\n')
        with self.assertRaises(RuntimeError) as caught:
            with bounded.session(self.profile,root=self.root):self.fail('Must not yield')
        self.assertIn('exited (-4)',str(caught.exception))
        self.assertIn('Fatal Python error: Illegal instruction',str(caught.exception))
        self.assertIn('kornia_rs',str(caught.exception))
        self.http.assert_not_called();self.job.close.assert_called_once();self.process.wait.assert_called_once()

    def test_body_failure_preserves_error_and_cleans_up(self):
        with self.assertRaisesRegex(RuntimeError,'workflow failed'):
            with bounded.session(self.profile,root=self.root):raise RuntimeError('workflow failed')
        self.job.close.assert_called_once();self.process.wait.assert_called_once()

    def test_backend_flags_respect_windows_rocm_and_linux_selection(self):
        for backend in ('cuda','cpu','rocm-cpu-validation','garbage'):
            with self.assertRaises(ValueError):bounded.backend_flags({'backend':backend},windows=True)
        self.assertNotIn('--cpu',bounded.backend_flags({'backend':'rocm'},windows=True))
        self.assertEqual(bounded.backend_flags({'backend':'cpu'},windows=False),['--cpu'])
        for backend in ('cuda','rocm'):
            flags=bounded.backend_flags({'backend':backend},windows=False)
            self.assertIn('--disable-triton-backend',flags);self.assertNotIn('--cpu',flags)

    def test_linux_cuda_selection_is_preserved_in_child_environment(self):
        self.profile['backend']='cuda'
        with patch.object(bounded,'os',SimpleNamespace(name='posix')):
            with bounded.session(self.profile,root=self.root):
                self.assertEqual(self.worker_env['PORTALAI_TORCH_BACKEND'],'cuda')
                self.assertNotIn('--cpu',self.request['command'])

    def test_retained_startup_diagnostics_are_bounded(self):
        self.log_bytes=b'a'*(256*1024)+b'end-of-log'
        with bounded.session(self.profile,root=self.root):pass
        kept=(self.root/'Agent/.runtime/scaled-comfy.log').read_bytes()
        self.assertEqual(len(kept),128*1024)
        self.assertTrue(kept.endswith(b'end-of-log'))

    def test_extra_args_cannot_override_resource_or_network_policy(self):
        for args in (['--port','9000'],['--listen','0.0.0.0'],['--cpu'],['--highvram'],['--user-directory']):
            with self.assertRaises(ValueError):bounded.checked_extra_args(args,self.root)
        with self.assertRaises(ValueError):
            bounded.checked_extra_args(['--temp-directory',str(self.root.parent/'outside')],self.root)
        args=['--disable-metadata','--output-directory',str(self.root/'Cache/output')]
        self.assertEqual(bounded.checked_extra_args(args,self.root),args)

    def test_invalid_memory_profile_does_not_start_worker(self):
        with self.assertRaises(ValueError):
            with bounded.session({**self.profile,'max_memory_bytes':1},root=self.root):self.fail('Must not yield')
        self.Popen.assert_not_called()


class LinuxMembershipTests(unittest.TestCase):
    def test_listener_must_be_in_this_worker_group_or_descendant(self):
        import linux_job
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder).resolve();job=SimpleNamespace(linux=SimpleNamespace(group=base/'scope/job'))
            with patch.object(linux_job,'MOUNT',base):
                for member,expected in (('/scope/job',True),('/scope/job/child',True),('/scope/job-other',False),('/scope/other',False),('/scope/job/../other',False)):
                    with patch.object(Path,'read_text',return_value='0::'+member+'\n'):
                        self.assertEqual(bounded.owns_pid(job,123),expected,member)


class DiagnosticTests(unittest.TestCase):
    def test_native_crash_retains_cause_first_frames_and_last_frames(self):
        from process_diagnostics import excerpt
        text=('Comfy startup\n'*400+'Fatal Python error: Illegal instruction\n'
              'Current thread in kornia_rs native import\n'+'  File importlib\n'*400+
              '  File comfy_amd_entry.py\n\nExtension modules: '+('torch numpy '*1000))
        result=excerpt(text,1200)
        self.assertLessEqual(len(result),1200)
        self.assertIn('Fatal Python error: Illegal instruction',result)
        self.assertIn('kornia_rs native import',result)
        self.assertIn('comfy_amd_entry.py',result)
        self.assertNotIn('Extension modules:',result)

    def test_python_error_preserves_traceback_and_final_exception(self):
        from process_diagnostics import excerpt
        text='Traceback (most recent call last):\n'+'  File repeated.py\n'*400+'ModuleNotFoundError: missing-package'
        result=excerpt(text,1200)
        self.assertTrue(result.startswith('Traceback'))
        self.assertTrue(result.endswith('ModuleNotFoundError: missing-package'))

    def test_file_read_remains_bounded(self):
        from process_diagnostics import file_excerpt
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'log';path.write_text('old-noise'*(100*1024)+'\nFatal Python error: Segmentation fault\nNative failing frame')
            result=file_excerpt(path,1200)
        self.assertIn('Fatal Python error: Segmentation fault',result)
        self.assertIn('Native failing frame',result)
        self.assertLessEqual(len(result),1200)


if __name__=='__main__':unittest.main()
