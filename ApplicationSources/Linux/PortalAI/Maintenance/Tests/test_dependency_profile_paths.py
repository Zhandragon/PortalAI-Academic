"""Dependency maintenance uses synthetic profile roots and mocked child imports."""
from contextlib import redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'Tools')]
import dependency_check as checks
import profile_paths as profiles


ENTRY = ('Synthetic dependency', 'Runtime/BootstrapPython/python.exe', ('Runtime/packages',), ('fixture_module',))
JOURNAL = 'Data/Maintenance/dependency_probe_journal.json'


class DependencyProfilePaths(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.uid, self.epoch = 'a'*32, 'b'*32
        self.workspace = profiles.workspace_root(self.root, self.uid)
        clean = patch.dict(os.environ, {}, clear=True)
        clean.start(); self.addCleanup(clean.stop)

    def write(self, path, contents=b'synthetic data'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    def active(self, state='open'):
        self.write(self.root/'Private/active-session.json', json.dumps({
            'user_id': self.uid, 'epoch': self.epoch, 'state': state,
        }).encode())
        os.environ.update({profiles.UID_ENV:self.uid, profiles.EPOCH_ENV:self.epoch})

    def run_main(self, *options):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['dependency_check', '--root', str(self.root), *options]), redirect_stdout(output):
            code = checks.main()
        return code, output.getvalue()

    def result(self):
        return subprocess.CompletedProcess([], 0, '{"rows":[]}', '')

    def test_active_check_scopes_temp_and_keeps_isolation_flags(self):
        self.active()
        poison = {name:'C:/host-python' for name in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','__PYVENV_LAUNCHER__')}
        with patch.dict(os.environ, poison), patch.object(checks.subprocess,'run',return_value=self.result()) as run:
            self.assertEqual(checks.check(self.root, ENTRY)['status'], 'PASS')
        command = run.call_args.args[0]
        self.assertEqual(command[:4], [str(self.root/ENTRY[1]), '-B', '-I', '-c'])
        env = run.call_args.kwargs['env']
        for name in ('TEMP','TMP','TMPDIR'):
            self.assertEqual(Path(env[name]), self.workspace/'Cache/tmp')
        for name in poison:
            self.assertNotIn(name, env)
        for name in ('HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','HF_DATASETS_OFFLINE','PIP_NO_INDEX'):
            self.assertEqual(env[name], '1')
        self.assertEqual(env[profiles.UID_ENV], self.uid)
        self.assertTrue((self.workspace/'Cache/tmp').is_dir())
        self.assertFalse((self.root/'Cache').exists())

    def test_locked_check_and_main_refuse_before_child_or_shared_writes(self):
        self.active(state='closed')
        with patch.object(checks.subprocess,'run') as run, patch.object(checks,'save') as save:
            with self.assertRaises(profiles.ProfileLocked):
                checks.check(self.root, ENTRY)
            with self.assertRaises(profiles.ProfileLocked):
                self.run_main('--recover-only')
        run.assert_not_called(); save.assert_not_called()
        self.assertFalse((self.root/'Cache').exists())
        self.assertFalse((self.root/'Data').exists())
        self.assertFalse(self.workspace.exists())

    def test_stale_epoch_does_not_adopt_new_login(self):
        self.active()
        os.environ[profiles.EPOCH_ENV] = 'c'*32
        with patch.object(checks.subprocess,'run') as run, self.assertRaises(profiles.ProfileLocked):
            checks.check(self.root, ENTRY)
        run.assert_not_called()
        self.assertFalse(self.workspace.exists())

    def test_legacy_temp_and_quarantine_journal_keep_original_locations(self):
        with patch.object(checks.subprocess,'run',return_value=self.result()) as run:
            self.assertEqual(checks.check(self.root, ENTRY)['status'], 'PASS')
        self.assertEqual(run.call_args.kwargs['env']['TEMP'], str(self.root/'Cache/tmp'))
        self.write(self.root/JOURNAL, b'legacy recovery evidence')
        code, output = self.run_main('--recover-only')
        self.assertEqual(code, 1)
        self.assertIn(str(self.root/JOURNAL), output)
        self.assertEqual((self.root/JOURNAL).read_bytes(), b'legacy recovery evidence')

    def test_active_journal_lookup_is_owner_scoped_and_never_recovers_automatically(self):
        self.active()
        other = profiles.workspace_root(self.root, 'c'*32)/JOURNAL
        self.write(other, b'another owner recovery evidence')
        self.assertEqual(self.run_main('--recover-only')[0], 0)
        own = self.workspace/JOURNAL
        self.write(own, b'owner recovery evidence')
        with patch.object(checks,'check') as check, patch.object(checks,'save') as save:
            code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn(str(own), output)
        check.assert_not_called(); save.assert_not_called()
        self.assertEqual(own.read_bytes(), b'owner recovery evidence')
        self.assertEqual(other.read_bytes(), b'another owner recovery evidence')
        self.assertFalse((self.root/'Data').exists())

    def test_main_report_is_saved_in_current_profile(self):
        self.active()
        with patch.object(checks,'platform_checks',return_value=(ENTRY,)), \
             patch.object(checks.subprocess,'run',return_value=self.result()):
            code, _ = self.run_main()
        self.assertEqual(code, 0)
        report = self.workspace/'Data/Maintenance/dependency_probe_latest.json'
        saved = json.loads(report.read_text())
        self.assertEqual(saved['counts']['PASS'], 1)
        self.assertFalse(saved['deletion_authorized'])
        self.assertFalse((self.root/'Data').exists())

    def execute_child_code(self, origin):
        def run(command, **kwargs):
            output = io.StringIO()
            with patch.object(sys,'argv',['-c',*command[5:]]), \
                 patch.object(sys,'path',list(sys.path)), \
                 patch.object(importlib,'import_module',return_value=SimpleNamespace(__file__=str(origin))), \
                 redirect_stdout(output):
                try:
                    exec(compile(command[4], '<dependency fixture child>', 'exec'), {'__name__':'__main__'})
                except SystemExit as exited:
                    return subprocess.CompletedProcess(command, exited.code, output.getvalue(), '')
            raise AssertionError('Child must emit a verified exit status')
        self.active()
        with patch.object(checks.subprocess,'run',side_effect=run):
            return checks.check(self.root, ENTRY)

    def test_host_module_origin_is_still_rejected(self):
        result = self.execute_child_code(self.root.parent/'host-python/packages/fixture_module.py')
        self.assertEqual(result['status'], 'FAIL')
        self.assertFalse(json.loads(result['detail'])['rows'][0]['ok'])

    def test_owned_module_origin_remains_accepted(self):
        result = self.execute_child_code(self.root/'Runtime/packages/fixture_module.py')
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(json.loads(result['detail'])['rows'][0]['ok'])


if __name__ == '__main__':
    unittest.main()
