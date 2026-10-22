"""Launcher delegation checks with no GUI, account state or real process launch."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import linux_job
import runtime_policy
def _load_launcher():
    # The real Linux entry selects its GUI/Pillow packages at import time. Test
    # discovery runs in a shared Windows interpreter, so that search-path change
    # must stay inside this fixture, before any neighboring tests import Pillow.
    with patch.object(sys,'path',list(sys.path)):
        spec=importlib.util.spec_from_file_location('linux_gui_launcher_test',ROOT/'Launchers/portalai_gui_linux.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


launcher=_load_launcher()


class LinuxLauncher(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict(os.environ,{},clear=True).start()
        patch.object(sys,'platform','linux').start()
        patch.object(sys,'argv',['PortalAI.sh','--fixture']).start()
        self.environment=patch.object(runtime_policy,'portable_env',return_value={}).start()
        self.prepare=patch.object(linux_job,'prepare_delegation').start()
        self.preflight=patch.object(linux_job,'preflight').start()
        self.dispatch=patch.object(launcher.runpy,'run_path').start()
        self.which=patch.object(launcher.shutil,'which',return_value='/usr/bin/systemd-run').start()
        self.execute=patch.object(launcher.os,'execve').start()

    def test_fixture_import_restores_search_path_identity_and_content(self):
        original=sys.path
        before=list(original)
        loaded=_load_launcher()
        self.assertTrue(callable(loaded.main))
        self.assertIs(sys.path,original)
        self.assertEqual(sys.path,before)

    def test_existing_delegation_prepares_then_checks_before_gui_dispatch(self):
        events=[]
        self.prepare.side_effect=lambda:events.append('prepare')
        self.preflight.side_effect=lambda:events.append('preflight')
        self.dispatch.side_effect=lambda *a,**k:events.append('GUI')
        launcher.main()
        self.assertEqual(events,['prepare','preflight','GUI'])
        self.environment.assert_called_once_with(launcher.ROOT,before_login=True)
        self.execute.assert_not_called()

    def test_reexec_discards_stale_cgroup_and_has_one_attempt_fence(self):
        os.environ.update(PORTALAI_CGROUP_ROOT='/sys/fs/cgroup/dead',PORTALAI_PROFILE_ID='a'*32)
        self.prepare.side_effect=RuntimeError('stale cgroup')
        launcher.main()
        executable,argv,env=self.execute.call_args.args
        self.assertEqual(executable,'/usr/bin/systemd-run')
        self.assertEqual(argv[-3:],['--',str(ROOT/'PortalAI.sh'),'--fixture'])
        self.assertNotIn('PORTALAI_CGROUP_ROOT',env)
        self.assertEqual(env['PORTALAI_DELEGATION_ATTEMPTED'],'1')
        self.assertEqual(env['PORTALAI_PROFILE_ID'],'a'*32)
        self.dispatch.assert_not_called()

    def test_memory_or_cancel_preflight_failure_gets_new_scope_before_gui(self):
        self.preflight.side_effect=RuntimeError('missing cgroup.kill')
        launcher.main()
        self.execute.assert_called_once();self.dispatch.assert_not_called()

    def test_failed_second_scope_is_not_retried(self):
        os.environ['PORTALAI_DELEGATION_ATTEMPTED']='1'
        self.prepare.side_effect=RuntimeError('memory unavailable')
        with self.assertRaisesRegex(RuntimeError,'memory unavailable'):launcher.main()
        self.execute.assert_not_called();self.dispatch.assert_not_called()

    def test_no_systemd_never_falls_back_to_unowned_gui(self):
        self.which.return_value=None;self.prepare.side_effect=OSError('not delegated')
        with self.assertRaisesRegex(RuntimeError,'delegated cgroup'):launcher.main()
        self.execute.assert_not_called();self.dispatch.assert_not_called()

    def test_other_platform_refuses_before_environment_changes(self):
        with patch.object(sys,'platform','win32'):
            with self.assertRaisesRegex(RuntimeError,'requires Linux'):launcher.main()
        self.environment.assert_not_called();self.prepare.assert_not_called()


if __name__=='__main__':unittest.main()
