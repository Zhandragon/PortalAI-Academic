"""Live validation must use the current private profile and resist logout races."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Tools'), str(ROOT/'Agent')]
from smoke_profile import SmokeProfile
from profile_paths import UID_ENV, EPOCH_ENV, ProfileLocked


class SmokeProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.uid, self.epoch = 'a'*32, 'b'*32
        (self.root/'Private').mkdir()
        self.marker = self.root/'Private/active-session.json'
        self.state = {'user_id': self.uid, 'epoch': self.epoch, 'state': 'open'}
        self.marker.write_text(json.dumps(self.state))
        self.env = patch.dict(os.environ, {UID_ENV:self.uid, EPOCH_ENV:self.epoch})
        self.env.start(); self.addCleanup(self.env.stop)

    def revoke(self):
        self.marker.write_text(json.dumps({**self.state, 'state':'closed'}))

    def test_reports_and_outputs_use_active_workspace(self):
        smoke = SmokeProfile(self.root)
        target = smoke.save('result.json', {'passed':True})
        workspace = self.root/'Private/Users'/self.uid/'Workspace'
        self.assertTrue(target.is_relative_to(workspace/'Data/Maintenance/Smoke'))
        self.assertEqual(smoke.outputs('Images'), workspace/'Outputs/Images')
        self.assertFalse((self.root/'Maintenance/Reports').exists())

    def test_locked_or_changed_login_cannot_create_reports(self):
        smoke = SmokeProfile(self.root)
        self.revoke()
        with self.assertRaises(ProfileLocked): smoke.save('result.json', {})
        self.assertFalse((self.root/'Private/Users').exists())
        with self.assertRaises(ProfileLocked): SmokeProfile(self.root)

    def test_revocation_at_publish_removes_only_this_report(self):
        smoke = SmokeProfile(self.root)
        target = smoke.path('result.json')
        original = Path.replace
        def replace(source, dest):
            value = original(source, dest)
            if Path(dest) == target: self.revoke()
            return value
        with patch.object(Path, 'replace', replace):
            with self.assertRaises(ProfileLocked): smoke.save('result.json', {})
        self.assertFalse(target.exists())
        self.assertFalse(list(target.parent.glob('*.tmp')))

    def test_foreign_replacement_survives_revocation(self):
        smoke = SmokeProfile(self.root)
        target = smoke.path('result.json')
        original = Path.replace
        def replace(source, dest):
            value = original(source, dest)
            if Path(dest) == target:
                original(target, target.with_suffix('.owned'))
                target.write_text('foreign sentinel')
                self.revoke()
            return value
        with patch.object(Path, 'replace', replace):
            with self.assertRaises(ProfileLocked): smoke.save('result.json', {})
        self.assertEqual(target.read_text(), 'foreign sentinel')

    def test_legacy_fixture_keeps_private_data_layout(self):
        other = self.root/'Legacy';other.mkdir()
        with patch.dict(os.environ, {}, clear=True):
            smoke = SmokeProfile(other)
            self.assertEqual(smoke.outputs('Music'), other/'Outputs/Music')
            self.assertTrue(smoke.save('report.json', {}).is_relative_to(other/'Data/Maintenance/Smoke'))

    def test_escaped_report_or_output_is_refused(self):
        smoke = SmokeProfile(self.root)
        for path in ('../outside.json', '/outside.json', 'C:/outside.json'):
            with self.assertRaises(ValueError):smoke.path(path)
            with self.assertRaises(ValueError):smoke.outputs(path)


if __name__ == '__main__': unittest.main()
