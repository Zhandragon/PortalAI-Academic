"""Post-crash test harness must not supersede a user Stop or a newer model."""
from contextlib import nullcontext
import importlib.util
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('crash_smoke_guard',ROOT/'Tools/smoke_crash_lifecycle.py')
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)


class CrashSmokeGuardTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(prefix='Portal smoke guard ')
        self.addCleanup(folder.cleanup);self.root=Path(folder.name)
        self.file=self.root/'plan';self.file.write_bytes(b'new user metadata')
        self.command=['portable-llama','-m','small-model','-c','8192']
        self.identity={'open':True,'portable_qwen':True,'listeners':[
            {'pid':12,'portable_qwen':True,'command_line':shlex.join(self.command)}]}
        self.saved={self.file:b'old metadata'};self.report={};self.guard=Mock()
        self.addCleanup(patch.stopall)
        patch.object(smoke,'ROOT',self.root).start()
        patch.object(smoke,'_argv',side_effect=shlex.split).start()
        patch.object(smoke.service,'_qwen_lifecycle_mutex',side_effect=lambda:nullcontext()).start()
        self.current=patch.object(smoke,'_owned_listener',return_value=self.identity).start()
        self.stop=patch.object(smoke.service,'_stop_qwen_listener').start()
        patch.object(smoke.service,'port_open',return_value=False).start()
        self.remember=patch.object(smoke.service,'_remember_qwen_launch').start()
        self.atomic=patch.object(smoke,'atomic_json').start()

    def cleanup(self):
        smoke.cleanup_temporary(self.command,self.identity,self.guard,self.saved,self.report)

    def test_stop_keeps_new_metadata_and_model_untouched(self):
        self.guard.side_effect=smoke.PreparationCancelled('User Stop')
        self.cleanup()
        self.stop.assert_not_called();self.current.assert_not_called()
        self.assertEqual(self.file.read_bytes(),b'new user metadata')
        self.assertEqual(self.report['cleanup_skipped'],'User Stop')
        self.assertFalse(self.report['passed'])

    def test_same_command_new_pid_is_not_our_cleanup_target(self):
        self.current.return_value={**self.identity,'listeners':[{**self.identity['listeners'][0],'pid':13}]}
        self.cleanup();self.stop.assert_not_called()
        self.assertEqual(self.file.read_bytes(),b'new user metadata')
        self.assertFalse(self.report['passed'])

    def test_changed_arguments_are_not_matched_by_model_path_substring(self):
        self.current.return_value={**self.identity,'listeners':[
            {**self.identity['listeners'][0],'command_line':shlex.join(self.command+['--parallel','4'])}]}
        self.cleanup();self.stop.assert_not_called()

    def test_exact_model_is_stopped_before_prior_metadata_is_restored(self):
        self.stop.side_effect=lambda:self.assertEqual(self.file.read_bytes(),b'new user metadata')
        self.cleanup();self.stop.assert_called_once()
        self.assertEqual(self.file.read_bytes(),b'old metadata')
        self.assertTrue(self.report['temporary_model_stopped'])

    def startup_patches(self):
        self.process=Mock(pid=12);self.process.poll.return_value=None
        self.spawn=patch.object(smoke,'_spawn',return_value=self.process).start()
        patch.object(smoke.service,'acquire_gpu_lease',return_value='lease').start()
        self.release=patch.object(smoke.service,'release_gpu_lease').start()
        patch.object(smoke.service,'_qwen_health_ready',return_value=True).start()
        self.plan={'command':self.command}

    def test_stop_before_start_never_creates_process(self):
        self.startup_patches();self.guard.side_effect=smoke.PreparationCancelled('Stop')
        with self.assertRaises(smoke.PreparationCancelled):smoke.start_temporary(self.plan,self.guard)
        self.spawn.assert_not_called();self.remember.assert_not_called()

    def test_stop_during_loading_terminates_only_spawned_handle(self):
        self.startup_patches();self.current.return_value={'open':False}
        self.guard.side_effect=[None,None,smoke.PreparationCancelled('Stop')]
        with self.assertRaises(smoke.PreparationCancelled):smoke.start_temporary(self.plan,self.guard)
        self.process.terminate.assert_called_once();self.process.wait.assert_called_once()
        self.stop.assert_not_called();self.remember.assert_not_called();self.release.assert_called_once()

    def test_wrong_pid_cannot_satisfy_readiness(self):
        self.startup_patches()
        self.current.side_effect=[{'open':False},{**self.identity,'listeners':[{**self.identity['listeners'][0],'pid':13}]}]
        with self.assertRaisesRegex(RuntimeError,'different model'):smoke.start_temporary(self.plan,self.guard)
        self.process.terminate.assert_called_once();self.remember.assert_not_called()

    def test_exact_healthy_model_commits_metadata_then_releases_lease(self):
        self.startup_patches();self.current.side_effect=[{'open':False},self.identity]
        result=smoke.start_temporary(self.plan,self.guard)
        self.assertEqual(result,self.identity);self.remember.assert_called_once()
        self.atomic.assert_called_once();self.process.terminate.assert_not_called()
        self.release.assert_called_once_with('lease')


if __name__=='__main__':unittest.main()
