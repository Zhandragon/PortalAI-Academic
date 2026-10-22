"""Delegation and guardian protocol checks; real kernel checks live in the guest suite."""
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import linux_job


class LinuxJobTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='Portal cgroup test ')
        self.addCleanup(folder.cleanup)
        self.base=Path(folder.name).resolve()
        (self.base/'cgroup.controllers').write_text('cpu memory pids')
        (self.base/'cgroup.subtree_control').write_text('')
        (self.base/'cgroup.procs').write_text('')
        self.addCleanup(patch.stopall)
        patch.object(linux_job,'delegated_root',return_value=self.base).start()
        patch.dict(os.environ,{},clear=False).start()

    def test_new_scope_moves_only_controller_and_enables_memory(self):
        with patch.object(linux_job,'current_group',return_value=self.base):
            self.assertEqual(linux_job.prepare_delegation(),self.base)
        self.assertEqual((self.base/'portalai-controller/cgroup.procs').read_text(),str(os.getpid()))
        self.assertEqual((self.base/'cgroup.subtree_control').read_text(),'+memory')
        self.assertEqual(os.environ['PORTALAI_CGROUP_ROOT'],str(self.base))

    def test_nested_worker_is_not_moved_out_of_its_job(self):
        with patch.object(linux_job,'current_group',return_value=self.base/'portalai-job-123-a'):
            linux_job.prepare_delegation()
        self.assertFalse((self.base/'portalai-controller').exists())
        self.assertEqual((self.base/'cgroup.subtree_control').read_text(),'+memory')

    def test_other_processes_are_not_moved_to_enable_memory(self):
        (self.base/'cgroup.procs').write_text('424242\n')
        with patch.object(linux_job,'current_group',return_value=self.base/'controller'):
            with self.assertRaisesRegex(RuntimeError,'Other processes'):
                linux_job.prepare_delegation()
        self.assertEqual((self.base/'cgroup.procs').read_text(),'424242\n')
        self.assertEqual((self.base/'cgroup.subtree_control').read_text(),'')

    def test_missing_memory_controller_fails_closed(self):
        (self.base/'cgroup.controllers').write_text('pids')
        with patch.object(linux_job,'current_group',return_value=self.base/'controller'):
            with self.assertRaisesRegex(RuntimeError,'memory controller'):
                linux_job.prepare_delegation()

    def test_enabled_memory_is_not_reconfigured(self):
        (self.base/'cgroup.subtree_control').write_text('memory pids')
        with patch.object(linux_job,'current_group',return_value=self.base/'controller'):
            linux_job.prepare_delegation()
        self.assertEqual((self.base/'cgroup.subtree_control').read_text(),'memory pids')

    def guardian_call(self,command,confirmed=True):
        worker=self.base/('portalai-job-123-'+'a'*32)
        guardian_group=self.base/'portalai-guardians'
        def ready(*args,**kwargs):
            self.assertEqual((guardian_group/'cgroup.procs').read_text(),str(os.getpid()))
        with patch.object(linux_job,'current_group',return_value=guardian_group if confirmed else worker), \
             patch.object(linux_job.sys,'stdin',SimpleNamespace(buffer=io.BytesIO(command))), \
             patch('builtins.print',side_effect=ready) as printed, \
             patch.object(linux_job,'destroy') as destroy:
            if confirmed:
                linux_job.guardian(worker)
                printed.assert_called_once_with('READY',flush=True)
            else:
                with self.assertRaisesRegex(RuntimeError,'did not leave'):
                    linux_job.guardian(worker)
                printed.assert_not_called()
            return destroy.call_args_list

    def test_guardian_moves_out_before_ready_and_destroys_on_eof(self):
        calls=self.guardian_call(b'')
        self.assertEqual(len(calls),1)

    def test_guardian_cancel_destroys_nested_worker(self):
        self.assertEqual(len(self.guardian_call(b'cancel\n')),1)

    def test_guardian_release_preserves_confirmed_effects(self):
        self.assertEqual(self.guardian_call(b'release\n'),[])

    def test_failed_guardian_migration_never_opens_start_gate(self):
        self.guardian_call(b'',confirmed=False)

    def test_headless_start_prepares_before_dispatch_but_stop_remains_available(self):
        spec=importlib.util.spec_from_file_location('portalai_missions_test',ROOT/'Launchers/portalai_missions_linux.py')
        launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
        events=[]
        with patch.object(sys,'platform','linux'),patch.object(sys,'argv',['portalai-missions']), \
             patch('runtime_policy.portable_env',return_value={}),patch.object(os,'chdir'), \
             patch.object(linux_job,'preflight',return_value={}), \
             patch.object(linux_job,'prepare_delegation',side_effect=lambda:events.append('prepare')), \
             patch.object(launcher.runpy,'run_path',side_effect=lambda *a,**k:events.append('dispatch')):
            launcher.main(['supervisor','run'])
            self.assertEqual(events,['prepare','dispatch'])
            events.clear()
            launcher.main(['supervisor','stop'])
            self.assertEqual(events,['dispatch'])


if __name__=='__main__':unittest.main()
