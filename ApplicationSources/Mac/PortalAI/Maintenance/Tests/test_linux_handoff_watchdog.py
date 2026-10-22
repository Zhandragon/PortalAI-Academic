"""Linux recovery ownership and stop ordering, without launching any processes."""
from contextlib import ExitStack, nullcontext
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import linux_job
import linux_process
import platform_runtime
import qwen_vram_watchdog as watchdog
import service_manager as service


class AcknowledgementTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='Portal watchdog test ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.mount=self.root/'cgroups';self.base=self.mount/'scope'
        self.group=self.base/'portalai-guardians'
        self.state={'watchdog_pid':4242,'generation_token':'generation-one',
            'state_path':str(self.root/'handoff.json'),
            'watchdog_ready_path':str(self.root/'handoff.ready')}
        self.row={'pid':4242,'start_ticks':789,'argv':[str(self.root/'Runtime/python'),
            str(self.root/'Agent/qwen_vram_watchdog.py'),'--state',self.state['state_path']]}
        self.ack={'pid':4242,'start_ticks':789,'generation':'generation-one','group':str(self.group)}
        self.membership='0::/scope/portalai-guardians\n'
        read_text=Path.read_text
        def read(path,*args,**kwargs):
            if path.as_posix().endswith('/proc/4242/cgroup'):return self.membership
            return read_text(path,*args,**kwargs)
        self.stack=self.enterContext(ExitStack())
        self.stack.enter_context(patch.object(service,'root_dir',return_value=self.root))
        self.stack.enter_context(patch.object(linux_job,'delegated_root',return_value=self.base))
        self.stack.enter_context(patch.object(linux_job,'MOUNT',self.mount))
        self.stack.enter_context(patch.object(linux_process,'identity',return_value=self.row))
        self.owned=self.stack.enter_context(patch.object(linux_process,'owned',return_value=True))
        self.stack.enter_context(patch.object(Path,'read_text',read))

    def check(self):
        Path(self.state['watchdog_ready_path']).write_text(json.dumps(self.ack))
        service._wait_linux_handoff_watchdog(self.state)

    def test_ready_requires_matching_process_and_independent_cgroup(self):
        self.check()
        self.owned.assert_called_once_with(self.row,self.root)

    def test_stale_pid_start_or_generation_ack_is_rejected(self):
        for field,value in (('pid',4243),('start_ticks',790),('generation','old'),('group',str(self.base))):
            with self.subTest(field=field):
                original=self.ack[field];self.ack[field]=value
                with self.assertRaisesRegex(RuntimeError,'ownership'):
                    self.check()
                self.ack[field]=original

    def test_ack_does_not_substitute_for_actual_migration(self):
        self.membership='0::/scope/portalai-job-12-deadbeef\n'
        with self.assertRaisesRegex(RuntimeError,'ownership'):
            self.check()

    def test_foreign_executable_cannot_acknowledge(self):
        self.owned.return_value=False
        with self.assertRaisesRegex(RuntimeError,'ownership'):
            self.check()

    def test_wrong_watchdog_script_or_state_cannot_acknowledge(self):
        argv=self.row['argv'][:]
        for index in (1,3):
            with self.subTest(argument=index):
                self.row['argv']=argv[:];self.row['argv'][index]='foreign-file'
                with self.assertRaisesRegex(RuntimeError,'ownership'):
                    self.check()

    def test_missing_ack_times_out_without_polling_forever(self):
        with self.assertRaisesRegex(TimeoutError,'left running'):
            service._wait_linux_handoff_watchdog(self.state,timeout=0)


class HandoffOrderingTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='Portal handoff test ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        (self.root/'Agent').mkdir()
        (self.root/'Agent/qwen_vram_watchdog.py').touch()
        self.runtime=self.root/'Agent/.runtime';self.runtime.mkdir()
        self.events=[]
        self.stack=self.enterContext(ExitStack())
        for name,value in (
            ('root_dir',self.root),('_runtime_dir',self.runtime),
            ('_listener_identity',{'open':True,'portable_qwen':True,'listeners':[{'pid':99}]}),
            ('_process_command_line','captured exact llama command')):
            self.stack.enter_context(patch.object(service,name,return_value=value))
        self.stack.enter_context(patch.object(service,'os',SimpleNamespace(name='posix',getpid=os.getpid)))
        self.stack.enter_context(patch.object(service,'_qwen_lifecycle_mutex',return_value=nullcontext()))
        self.stack.enter_context(patch.object(platform_runtime,'python_path',return_value=self.root/'Runtime/python'))
        for name in ('_write_qwen_generation','_qwen_handoff_log'):
            self.stack.enter_context(patch.object(service,name))
        self.clear=self.stack.enter_context(patch.object(service,'_clear_generation_if_current'))
        self.mark=self.stack.enter_context(patch.object(service,'_mark_handoff_done'))
        self.launch=self.stack.enter_context(patch.object(service,'launch_detached',return_value=4242))
        self.wait=self.stack.enter_context(patch.object(service,'_wait_linux_handoff_watchdog',
            side_effect=lambda state:self.events.append('ack')))
        self.stop=self.stack.enter_context(patch.object(service,'_stop_qwen_listener',
            side_effect=lambda:self.events.append('stop') or [99]))
        self.stack.enter_context(patch.object(service.time,'sleep'))

    def test_model_stop_follows_ack_and_captured_command_is_preserved(self):
        state=service.qwen_gpu_handoff_begin('test')
        self.assertEqual(self.events,['ack','stop'])
        self.assertEqual(state['command_line'],'captured exact llama command')
        self.assertEqual(state['killed_pids'],[99])
        self.assertIn('--ready',self.launch.call_args.args[0])
        saved=json.loads(Path(state['state_path']).read_text())
        self.assertEqual(saved['watchdog_pid'],4242)
        self.clear.assert_not_called()

    def test_failed_ack_keeps_model_running_and_disarms_watchdog(self):
        self.wait.side_effect=TimeoutError('No guardian acknowledgement')
        with self.assertRaises(TimeoutError):service.qwen_gpu_handoff_begin('test')
        self.stop.assert_not_called();self.mark.assert_called_once()
        self.assertEqual(self.mark.call_args.args[1],'watchdog-start-failed')
        self.clear.assert_called_once()
        self.assertEqual(list(self.runtime.glob('*.json')),[])

    def test_launch_failure_never_stops_model(self):
        self.launch.side_effect=RuntimeError('Wrapper unavailable')
        with self.assertRaisesRegex(RuntimeError,'Wrapper unavailable'):
            service.qwen_gpu_handoff_begin('test')
        self.wait.assert_not_called();self.stop.assert_not_called()

    def test_windows_retains_original_launch_without_linux_ack(self):
        with patch.object(service,'os',SimpleNamespace(name='nt',getpid=os.getpid)):
            state=service.qwen_gpu_handoff_begin('windows-test')
        self.wait.assert_not_called();self.stop.assert_called_once()
        self.assertIsInstance(self.launch.call_args.args[0],str)
        self.assertNotIn('watchdog_ready_path',state)


class OwnerDeathTests(unittest.TestCase):
    def test_linux_zombie_is_dead_before_parent_reaps_it(self):
        with patch.object(watchdog,'os',SimpleNamespace(name='posix')):
            for state,alive in (('Z',False),('S',True),('R',True)):
                with self.subTest(state=state),patch.object(Path,'read_text',return_value=f'42 (a process) {state} 1 2 3'):
                    self.assertEqual(watchdog._pid_alive(42),alive)

    def test_missing_linux_process_is_dead(self):
        with patch.object(watchdog,'os',SimpleNamespace(name='posix')), \
             patch.object(Path,'read_text',side_effect=FileNotFoundError):
            self.assertFalse(watchdog._pid_alive(42))


if __name__=='__main__':unittest.main()
